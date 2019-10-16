import asyncio
import logging
from functools import total_ordering
from typing import NamedTuple

from aiohttp import ClientConnectorError, ClientResponseError

from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import ApplicationState, Cluster, ClusterBinding
from krake.client.kubernetes import KubernetesApi
from krake.client.core import CoreApi

from ..exceptions import on_error, ControllerError, application_error_mapping
from .. import Controller, Worker
from .metrics import MetricValueError, fetch_query


logger = logging.getLogger(__name__)


class UnsuitableDeploymentError(ControllerError):
    """Raised in case when there is not enough resources for spawning an application
    on any of the deployments.
    """

    code = ReasonCode.NO_SUITABLE_RESOURCE


class MissingMetricsDefinition(ControllerError):
    """Raised in case required metric definition is missing."""

    code = ReasonCode.MISSING_METRIC_DEFINITION


class Scheduler(Controller):
    """The scheduler is a controller watching all pending and updated
    applications and select the "best" backend.
    """

    states = (ApplicationState.PENDING, ApplicationState.UPDATED)

    async def list_and_watch(self):

        kubernetes_api = KubernetesApi(self.client)

        async def list_apps():
            logger.info("List Kubernetes applications")
            app_list = await kubernetes_api.list_all_applications()
            for app in app_list.items:
                logger.debug("Received %r", app)
                if app.status.state in self.states:
                    await self.queue.put(app.metadata.uid, app)

        async def watch_apps(watcher):
            logger.info("Watching Kubernetes applications")
            async for event in watcher:
                app = event.object
                logger.debug("Received %r", app)
                if app.status.state in self.states:
                    await self.queue.put(app.metadata.uid, app)

        async with kubernetes_api.watch_all_applications() as watcher:
            await asyncio.gather(list_apps(), watch_apps(watcher))


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


class SchedulerWorker(Worker):
    """Worker for :class:`Scheduler` responsible for selecting the "best"
    backend for each application based on metrics of the backends and
    application specifications.
    """

    def __init__(self, client=None):
        super().__init__(client=client)
        self.kubernetes_api = KubernetesApi(self.client)
        self.core_api = CoreApi(self.client)

    @on_error(ControllerError)
    async def resource_received(self, app):

        # TODO: Global optimization instead of incremental
        # TODO: API for supporting different application types
        cluster = await self.select_kubernetes_cluster(app)

        if cluster is None:
            logger.info(
                "Unable to schedule Kubernetes application %r", app.metadata.name
            )
            raise UnsuitableDeploymentError("No cluster available")

        else:
            logger.info(
                "Schedule Kubernetes application %r to cluster %r",
                app.metadata.name,
                cluster.metadata.name,
            )
            await self.kubernetes_api.update_application_binding(
                namespace=app.metadata.namespace,
                name=app.metadata.name,
                body=ClusterBinding(cluster=resource_ref(cluster)),
            )

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

    async def select_kubernetes_cluster(self, app):
        """Select suitable kubernetes cluster for application binding.

        Args:
            app: (krake.data.kubernetes.Application): Application object for binding

        Returns:
            Cluster: Cluster suitable for application binding

        """
        # TODO: Evaluate spawning a new cluster
        clusters_all = await self.kubernetes_api.list_all_clusters()

        clusters = [
            cluster
            for cluster in clusters_all.items
            if self.match_cluster_constraints(app, cluster)
        ]

        if not clusters:
            logger.info("Unable to match application constraints to any cluster")
            return None

        clusters_ranked = await self.rank_kubernetes_clusters(clusters)

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
            except (
                MissingMetricsDefinition,
                ClientConnectorError,
                ClientResponseError,
                MetricValueError,
            ) as err:
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
        if not cluster.spec.metrics:
            raise MissingMetricsDefinition(
                f"Missing metrics definition for cluster {cluster.metadata.name!r}."
            )

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

    async def error_occurred(self, app, error=None):
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
