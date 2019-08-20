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
import logging
import pprint
from functools import total_ordering
from typing import NamedTuple
from argparse import ArgumentParser

from krake import load_config, setup_logging
from krake.data.core import ReasonCode
from krake.data.kubernetes import ApplicationState, Cluster

from .exceptions import on_error, ControllerError
from . import Controller, Worker, run


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
        logger.info("List Kubernetes application")

        # List all Kubernetes applications
        for app in await self.client.kubernetes.application.list(namespace="all"):
            if app.status.state in self.states:
                await self.queue.put(app.metadata.uid, app)

        logger.info("Watching Kubernetes application")
        async with self.client.kubernetes.application.watch(namespace="all") as watcher:
            async for app in watcher:
                if app.status.state in self.states:
                    await self.queue.put(app.metadata.uid, app)


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
            await self.client.kubernetes.application.update_binding(
                namespace=app.metadata.namespace,
                name=app.metadata.name,
                cluster=cluster,
            )

    async def select_kubernetes_cluster(self, app):
        # TODO: Evaluate  a new cluster
        clusters = await self.client.kubernetes.cluster.list(namespace="all")

        if not clusters:
            return None

        ranked = [await self.rank_kubernetes_cluster(cluster) for cluster in clusters]
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
            error (Exception, optional): The exception whose reason will be propagated
                to the end-user. Defaults to None.
        """
        app.status.state = ApplicationState.FAILED
        app.status.reason = error

        await self.client.kubernetes.application.update_status(
            namespace=app.metadata.namespace, name=app.metadata.name, status=app.status
        )


parser = ArgumentParser(description="Krake scheduler")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)
    setup_logging(config["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(config))

    scheduler = Scheduler(
        api_endpoint=config["controllers"]["scheduler"]["api_endpoint"],
        worker_factory=SchedulerWorker,
        worker_count=config["controllers"]["scheduler"]["worker_count"],
    )
    run(scheduler)


if __name__ == "__main__":
    main()
