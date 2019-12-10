import asyncio
import logging
import random
from typing import NamedTuple

from aiohttp import ClientError

from krake.client.core import CoreApi
from krake.client.kubernetes import KubernetesApi
from krake.data.core import ReasonCode, resource_ref
from krake.data.kubernetes import ApplicationState, Cluster, ClusterBinding

from .. import Controller, Reflector
from ..exceptions import ControllerError, application_error_mapping
from .constraints import match_cluster_constraints
from .metrics import MetricError, fetch_query

logger = logging.getLogger(__name__)


class UnsuitableDeploymentError(ControllerError):
    """Raised in case when there is not enough resources for spawning an application
    on any of the deployments.
    """

    code = ReasonCode.NO_SUITABLE_RESOURCE


# We cannot use @functools.total_ordering because tuple already implements
# rich comparison operators preventing the decorator from generating the
# comparators.
class ClusterRank(NamedTuple):
    """Named tuple for ordering clusters based on a rank"""

    rank: float
    cluster: Cluster

    def __lt__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank < o.rank

    def __le__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank <= o.rank

    def __gt__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank > o.rank

    def __ge__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank >= o.rank

    def __eq__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank == o.rank

    def __ne__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank != o.rank


class Stickiness(NamedTuple):
    """Additional metric added clusters."""

    weight: float
    value: float


class Scheduler(Controller):
    """The scheduler is a controller that receives all pending and updated
    applications and selects the "best" backend for each one of them based
    on metrics of the backends and application specifications.

    Args:
        worker_count (int, optional): the amount of worker function that
            should be run as background tasks.
        reschedule (float, optional): number of seconds after which a resource
            should be rescheduled.
        ssl_context (ssl.SSLContext, optional): SSL context that should be
            used to communicate with the API server.
        debounce (float, optional): number of seconds the scheduler should wait
            before it reacts to a state change.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.

    """

    def __init__(
        self,
        api_endpoint,
        worker_count=10,
        reschedule_after=60,
        stickiness=0.1,
        ssl_context=None,
        debounce=0,
        loop=None,
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.kubernetes_api = None
        self.core_api = None
        self.reflector = None
        self.worker_count = worker_count
        self.reschedule_after = reschedule_after
        self.stickiness = stickiness

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.kubernetes_api = KubernetesApi(self.client)
        self.core_api = CoreApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        self.reflector = Reflector(
            listing=self.kubernetes_api.list_all_applications,
            watching=self.kubernetes_api.watch_all_applications,
            on_list=self.received_kubernetes_app,
            on_add=self.received_kubernetes_app,
            on_update=self.received_kubernetes_app,
            on_delete=self.received_kubernetes_app,
        )
        self.register_task(self.reflector, name="Reflector")

    async def cleanup(self):
        self.reflector = None
        self.kubernetes_api = None
        self.core_api = None

    async def received_kubernetes_app(self, app):
        """Handler for Kubernetes application reflector.

        Args:
            app (krake.data.kubernetes.Application): Application received from the API

        """
        if app.metadata.deleted:
            # TODO: If an application is deleted, the scheduling of other
            #   applications should potentially revised.
            logger.debug("Cancel rescheduling of deleted %r", app)
            await self.queue.cancel(app.metadata.uid)
        elif app.status.scheduled and app.metadata.modified <= app.status.scheduled:
            await self.reschedule_kubernetes_application(app)
        elif app.status.state == ApplicationState.FAILED:
            logger.debug("Reject failed %r", app)
        else:
            logger.debug("Accept %r", app)
            await self.queue.put(app.metadata.uid, app)

    async def handle_resource(self, run_once=False):
        """Infinite loop which fetches and hand over the resources to the right
        coroutine. The specific exceptions and error handling have to be added here.

        This function is meant to be run as background task. Lock the handling of a
        resource with the :attr:`lock` attribute.

        Args:
            run_once (bool, optional): if True, the function only handles one resource,
                then stops. Otherwise, continue to handle each new resource on the
                queue indefinitely.

        """
        while True:
            key, app = await self.queue.get()
            try:
                logger.debug("Handling resource %r", app)
                await self.resource_received(app)
            except ControllerError as err:
                await self.error_handler(app, error=err)
            finally:
                await self.queue.done(key)
            if run_once:
                break  # TODO: should we keep this? Only useful for tests

    async def resource_received(self, app):
        # TODO: API for supporting different application types
        # TODO: Evaluate spawning a new cluster

        await self.schedule_kubernetes_application(app)
        await self.reschedule_kubernetes_application(app)

    async def schedule_kubernetes_application(self, app):
        logger.info("Schedule %r", app)

        clusters = await self.kubernetes_api.list_all_clusters()
        cluster = await self.select_kubernetes_cluster(app, clusters.items)

        if cluster is None:
            logger.info("Unable to schedule %r", app.metadata.name)
            raise UnsuitableDeploymentError("No cluster available")

        scheduled_to = resource_ref(cluster)

        # Check if the scheduling decision changed
        if app.status.scheduled_to == scheduled_to:
            logger.debug("No change for %r", app)
            return

        if app.status.scheduled_to:
            logger.info(
                "Migrate %r from %s to %s", app, app.status.scheduled_to, scheduled_to
            )
        else:
            logger.info("Scheduled %r to %r", app, cluster)
        await self.kubernetes_api.update_application_binding(
            namespace=app.metadata.namespace,
            name=app.metadata.name,
            body=ClusterBinding(cluster=scheduled_to),
        )

    async def reschedule_kubernetes_application(self, app):
        # Put the application into the work queue with a certain delay. This
        # ensures the rescheduling of the application. Only put it if there is
        # not already another version of the resource in the queue. This check
        # is needed to ensure that we do not overwrite state changes with the
        # current one which might be outdated.
        if app.metadata.uid not in self.queue.dirty:
            logger.debug("Reschedule %r in %s secs", app, self.reschedule_after)
            await self.queue.put(app.metadata.uid, app, delay=self.reschedule_after)

    async def select_kubernetes_cluster(self, app, clusters):
        """Select suitable kubernetes cluster for application binding.

        Args:
            app (krake.data.kubernetes.Application): Application object for binding
            clusters (List[krake.data.kubernetes.Cluster]): Clusters between which
                the "best" one should be chosen.

        Returns:
            Cluster: Cluster suitable for application binding

        """
        matching = [
            cluster for cluster in clusters if match_cluster_constraints(app, cluster)
        ]

        if not matching:
            logger.info("Unable to match application constraints to any cluster")
            return None

        # Partition list if matching clusters into a list if clusters with
        # metrics and without metrics. Clusters with metrics are preferred
        # over clusters without metrics.
        with_metrics = [cluster for cluster in matching if cluster.spec.metrics]

        # Only use clusters without metrics when there are no clusters with
        # metrics.
        if not with_metrics:
            ranked = [
                self.calculate_kubernetes_cluster_rank((), cluster, app)
                for cluster in clusters
            ]
        else:
            # Rank the clusters based on their metric and return the cluster with
            # a minimal rank.
            ranked = await self.rank_kubernetes_clusters(app, with_metrics)

        if not ranked:
            logger.info("Unable to rank any cluster")
            return None

        # Find all maximal ranked clusters
        best = max(ranked)
        maximum = [rank for rank in ranked if rank == best]

        # Select randomly between best clusters
        return random.choice(maximum).cluster

    async def rank_kubernetes_clusters(self, app, clusters):
        """Rank kubernetes clusters based on metrics values and weights.

        Args:
            app (krake.data.kubernetes.Application): Application object for binding
            clusters (List[Cluster]): List of clusters to rank

        Returns:
            List[ClusterRank]: Ranked list of clusters

        """
        ranked_clusters = []
        for cluster in clusters:
            try:
                metrics = await self._fetch_metrics(cluster)
            except (MetricError, ClientError) as err:
                # If there is any issue with a metric, skip this cluster for
                # evaluation.
                logger.error(err)
                continue

            for metric, value, weight in metrics:
                logger.debug(
                    "Received metric %r with value %r for cluster %r",
                    metric.metadata.name,
                    value,
                    cluster.metadata.name,
                )

            rank = self.calculate_kubernetes_cluster_rank(metrics, cluster, app)
            ranked_clusters.append(rank)

        return ranked_clusters

    async def _fetch_metrics(self, cluster):
        assert cluster.spec.metrics, "Cluster does not have any metric assigned"
        fetching = []

        for metric_spec in cluster.spec.metrics:
            metric = await self.core_api.read_metric(name=metric_spec.name)
            metrics_provider = await self.core_api.read_metrics_provider(
                name=metric.spec.provider.name
            )
            fetching.append(
                fetch_query(
                    self.client.session, metric, metrics_provider, metric_spec.weight
                )
            )

        return await asyncio.gather(*fetching)

    def calculate_kubernetes_cluster_rank(self, metrics, cluster, app):
        """Calculate weighted sum of metrics values.

        Args:
            metrics (List[.metrics.QueryResult]): List of metric query results
            cluster (krake.data.kubernetes.Cluster): Cluster that is ranked
            app (krake.data.kubernetes.Application): Application object that
                should be scheduled.

        Returns:
            ClusterRank: rank of the passed cluster based on metrics and
            application.

        """
        sticky = self.calculate_kubernetes_cluster_stickiness(cluster, app)

        if not metrics:
            return ClusterRank(rank=sticky.weight * sticky.value, cluster=cluster)

        norm = sum(metric.weight for metric in metrics) + sticky.weight
        rank = (
            sum(metric.value * metric.weight for metric in metrics)
            + (sticky.value * sticky.weight)
        ) / norm

        return ClusterRank(rank=rank, cluster=cluster)

    def calculate_kubernetes_cluster_stickiness(self, cluster, app):
        """Return extra metric for clusters to make the application "stick" to
        it by increasing its rank.

        If the application is already scheduled to the passed cluster, a
        stickiness of ``1.0`` with a configurable weight is returned.
        Otherwise, a stickiness of ``0`` is returned.

        Args:
            cluster (krake.data.kubernetes.Cluster): Cluster that is ranked
            app (krake.data.kubernetes.Application): Application object that
                should be scheduled.

        Returns:
            Stickiness: Value and its weight that should be added to the
            cluster rank.

        """
        if resource_ref(cluster) != app.status.scheduled_to:
            return Stickiness(weight=0, value=0)

        return Stickiness(weight=self.stickiness, value=1.0)

    async def error_handler(self, app, error=None):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Callback updates kubernetes application status to the failed state and
        describes the reason of the failure.

        Args:
            app (krake.data.kubernetes.Application): Application object processed
                when the error occurred
            error (Exception, optional): The exception whose reason will be propagated
                to the end-user. Defaults to None.
        """
        reason = application_error_mapping(app.status.state, app.status.reason, error)
        app.status.reason = reason

        # If an important error occurred, simply delete the Application
        if reason.code.value >= 100:
            app.status.state = ApplicationState.DELETING
        else:
            app.status.state = ApplicationState.FAILED

        kubernetes_api = KubernetesApi(self.client)
        await kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )
