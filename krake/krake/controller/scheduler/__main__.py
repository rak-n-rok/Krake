"""Module for Krake controller responsible for binding Krake
applications to specific backends and entry point of Krake scheduler.

.. code:: bash

    python -m krake.controller.scheduler --help

Configuration is loaded from the ``controllers.scheduler`` section:

.. code:: yaml

    controllers:
      scheduler:
        api_endpoint: http://localhost:8080
        worker_count: 5

"""
import asyncio
import logging
import pprint
from functools import total_ordering
from typing import NamedTuple
from argparse import ArgumentParser

from aiohttp import ClientConnectorError

from krake import load_config, setup_logging
from krake.data.core import resource_ref, ReasonCode, MetricsProvider, Metric
from krake.controller.scheduler.metrics_provider import MetricValueError
from krake.data.kubernetes import ApplicationState, Cluster, ClusterBinding
from krake.client.kubernetes import KubernetesApi
from krake.client.core import CoreApi
from krake.controller import Controller, Worker, run
from krake.controller.exceptions import on_error, ControllerError

from .exceptions import on_error, ControllerError, application_error_mapping
from .metrics import (
    MissingMetricsDefinition,
    get_metrics_providers_objs,
    merge_obj,
    fetch_query_tasks,
)
from . import Controller, Worker, run, create_ssl_context


logger = logging.getLogger("krake.controller.scheduler")


class UnsuitableDeploymentError(ControllerError):
    """Raised in case when there is not enough resources for spawning an application
        on any of the deployments.
    """

    code = ReasonCode.NO_SUITABLE_RESOURCE


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kubernetes_api = KubernetesApi(self.client)
        self.core_api = CoreApi(self.client)
        self.metrics_default = (
            self.config_defaults.get("default_metrics")
            if self.config_defaults
            else None
        )
        self.metrics_providers_default = (
            self.config_defaults.get("default_metrics_providers")
            if self.config_defaults
            else None
        )

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
    def match_constraints(app, cluster):
        """Evaluate if all application constraints annotations match cluster
        annotations.

        Args:
            app (krake.data.kubernetes.Application): Application object for binding
            cluster (Cluster): Cluster

        Returns:
            bool: True if all application constraints annotations match cluster
                annotations, else False

        """
        return all(
            [
                annotation in cluster.spec.annotations
                for annotation in app.spec.constraints.annotations
            ]
        )

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
            if self.match_constraints(app, cluster)
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
        session = self.client.session
        metrics_db, metrics_providers_db = await asyncio.gather(
            self.core_api.list_metrics(), self.core_api.list_metrics_providers()
        )
        metrics_all = merge_obj(metrics_db.items, self.metrics_default, Metric)
        metrics_providers_all = merge_obj(
            metrics_providers_db.items, self.metrics_providers_default, MetricsProvider
        )
        ranked_clusters = []
        for cluster in clusters:
            try:
                metrics, metrics_providers = get_metrics_providers_objs(
                    cluster, metrics_all, metrics_providers_all
                )
            except MissingMetricsDefinition as err:
                logger.error(err)
                continue

            metrics_tasks = fetch_query_tasks(session, metrics, metrics_providers)

            try:
                metrics_fetched = await asyncio.gather(*metrics_tasks)
            except (ClientConnectorError, MetricValueError) as err:
                logger.error(err)
                continue

            if logger.level == logging.DEBUG:
                for metric in metrics_fetched:
                    logger.debug(
                        f"Scheduler received metric {metric.metadata.name} "
                        f"with value {metric.spec.value} "
                        f"for cluster {cluster.metadata.name}"
                    )

            ranked_clusters.append(
                ClusterRank(
                    rank=self.weighted_sum_of_metrics(metrics_fetched), cluster=cluster
                )
            )

        return ranked_clusters

    @staticmethod
    def weighted_sum_of_metrics(metrics):
        """Calculate weighted sum of metrics values.

        Args:
            metrics (List[Metric]): List of metrics

        Returns:
            int: Sum of metrics values * metrics weights

        """
        return sum([metric.spec.value * metric.spec.weight for metric in metrics])

    async def error_occurred(self, app, error=None):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Callback updates kubernetes application status to the failed state and
        describes the reason of the failure.

        Args:
            app (krake.data.kubernetes.Application): Application object processed
                when the error occurred
            reason (str, optional): The reason of the exception which will be propagate
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


parser = ArgumentParser(description="Krake scheduler")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)

    setup_logging(config["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(config))
    scheduler_config = config["controllers"]["scheduler"]

    tls_config = scheduler_config.get("tls")
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    scheduler = Scheduler(
        api_endpoint=scheduler_config["api_endpoint"],
        worker_factory=SchedulerWorker,
        worker_count=scheduler_config["worker_count"],
        ssl_context=ssl_context,
        debounce=scheduler_config.get("debounce", 0),
        config_defaults={
            "default_metrics": config["default-metrics"],
            "default_metrics_providers": config["default-metrics-providers"],
        },
    )
    run(scheduler)


if __name__ == "__main__":
    main()
