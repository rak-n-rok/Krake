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

from krake import load_config, setup_logging
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import ApplicationState, Cluster, ClusterBinding
from krake.client.kubernetes import KubernetesApi

from .exceptions import on_error, ControllerError, application_error_mapping
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

    async def select_kubernetes_cluster(self, app):
        # TODO: Evaluate spawning a new cluster
        clusters = await self.kubernetes_api.list_all_clusters()

        if not clusters.items:
            return None

        ranked = [
            await self.rank_kubernetes_cluster(cluster) for cluster in clusters.items
        ]
        return min(ranked).cluster

    async def rank_kubernetes_cluster(self, cluster):
        # TODO: Implement ranking function
        return ClusterRank(rank=0.5, cluster=cluster)

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
    )
    run(scheduler)


if __name__ == "__main__":
    main()
