import asyncio
import logging
import random
from functools import total_ordering
from typing import NamedTuple
from aiohttp import ClientError

from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import ApplicationState, Cluster, ClusterBinding
from krake.client.kubernetes import KubernetesApi
from krake.client.core import CoreApi

from ..exceptions import ControllerError, application_error_mapping
from .. import Controller, Reflector
from .metrics import MetricError, fetch_query


logger = logging.getLogger(__name__)


class UnsuitableDeploymentError(ControllerError):
    """Raised in case when there is not enough resources for spawning an application
    on any of the deployments.
    """

    code = ReasonCode.NO_SUITABLE_RESOURCE


@total_ordering
class ClusterRank(NamedTuple):
    """Named tuple for ordering clusters based on a rank"""

    rank: float
    cluster: Cluster

    def __lt__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank < o.rank

    def __eq__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank == o.rank


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
            logger.info("No change for %r", app)
            return

        if app.status.scheduled_to:
            logger.info(
                "Migrate %r from %s to %s", app, app.status.scheduled_to, scheduled_to
            )
        else:
            logger.info("Scheduled %r to cluster %r", app, cluster)
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

    @staticmethod
    def match_cluster_constraints(app, cluster):
        """Evaluate if all application constraints labels match cluster labels.

        Args:
            app (krake.data.kubernetes.Application): Application that should be
                bound.
            cluster (krake.data.kubernetes.Cluster): Cluster to which the
                application should be bound.

        Returns:
            bool: True if the cluster fulfills all application cluster constraints

        """
        if not app.spec.constraints:
            return True

        # Cluster constraints
        if app.spec.constraints.cluster:
            # Label constraints for the cluster
            if app.spec.constraints.cluster.labels:
                for constraint in app.spec.constraints.cluster.labels:
                    if constraint.match(cluster.metadata.labels or {}):
                        logger.debug(
                            "Cluster %s does not match constraint %r",
                            resource_ref(cluster),
                            constraint,
                        )
                    else:
                        logger.debug(
                            "Cluster %s does not match constraint %r",
                            resource_ref(cluster),
                            constraint,
                        )
                        return False

        logger.debug(
            "Cluster %s fulfills constraints of application %r",
            resource_ref(cluster),
            resource_ref(app),
        )

        return True

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
            cluster
            for cluster in clusters
            if self.match_cluster_constraints(app, cluster)
        ]

        if not matching:
            logger.info("Unable to match application constraints to any cluster")
            return None

        # Partition list if matching clusters into a list if clusters with
        # metrics and without metrics. Clusters with metrics are preferred
        # over clusters without metrics.
        with_metrics = [cluster for cluster in matching if cluster.spec.metrics]
        without_metrics = [cluster for cluster in matching if not cluster.spec.metrics]

        # Only use clusters without metrics when there are no clusters with
        # metrics.
        if not with_metrics:
            # TODO: Use a more advanced selection
            return random.choice(without_metrics)

        # Rank the clusters based on their metric and return the cluster with
        # a minimal rank.
        clusters_ranked = await self.rank_kubernetes_clusters(with_metrics)

        if not clusters_ranked:
            logger.info("Unable to rank any cluster")
            return None

        return min(clusters_ranked).cluster

    async def rank_kubernetes_clusters(self, clusters):
        """Rank kubernetes clusters based on metrics values and weights.

        Args:
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

            for metric, value in metrics:
                logger.debug(
                    "Received metric %r with value %r for cluster %r",
                    metric.metadata.name,
                    value,
                    cluster.metadata.name,
                )

            ranked_clusters.append(
                ClusterRank(rank=self.weighted_sum_of_metrics(metrics), cluster=cluster)
            )

        return ranked_clusters

    async def _fetch_metrics(self, cluster):
        assert cluster.spec.metrics, "Cluster does not have any metric assigned"
        fetching = []

        for name in cluster.spec.metrics:
            metric = await self.core_api.read_metric(name=name)
            metrics_provider = await self.core_api.read_metrics_provider(
                name=metric.spec.provider.name
            )
            fetching.append(fetch_query(self.client.session, metric, metrics_provider))

        return await asyncio.gather(*fetching)

    @staticmethod
    def weighted_sum_of_metrics(metrics):
        """Calculate weighted sum of metrics values.

        Args:
            metrics (List[Tuple[Metric, float]]): List of metric value tuples

        Returns:
            int: Sum of metrics values * metrics weights

        """
        return sum(value * metric.spec.weight for metric, value in metrics)

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
            app.status.state = ApplicationState.DELETED
        else:
            app.status.state = ApplicationState.FAILED

        kubernetes_api = KubernetesApi(self.client)
        await kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )
