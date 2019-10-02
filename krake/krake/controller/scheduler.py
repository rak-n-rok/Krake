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
from functools import total_ordering, partial
from typing import NamedTuple
from argparse import ArgumentParser

from krake import load_config, setup_logging
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import ApplicationState, Cluster, ClusterBinding
from krake.client.kubernetes import KubernetesApi

from .exceptions import ControllerError, application_error_mapping
from . import Controller, create_ssl_context, run, Reflector

logger = logging.getLogger("krake.controller.scheduler")


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
        worker_count (int, optional): the amount of worker function that should be
            run as background tasks.
    """

    def __init__(
        self, api_endpoint, worker_count=10, loop=None, ssl_context=None, debounce=0
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.kubernetes_api = None
        self.reflector = None
        self.worker_count = worker_count

    def create_background_tasks(self):
        assert self.client is not None

        self.kubernetes_api = KubernetesApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        def accept_applications(app):
            return app.status.state in (
                ApplicationState.PENDING,
                ApplicationState.UPDATED,
            )

        receive_app = partial(self.simple_on_receive, condition=accept_applications)

        self.reflector = Reflector(
            listing=self.kubernetes_api.list_all_applications,
            watching=self.kubernetes_api.watch_all_applications,
            on_list=receive_app,
            on_add=receive_app,
            on_update=receive_app,
            on_delete=receive_app,
        )
        self.register_task(self.reflector, name="Reflector")

    async def clean_background_tasks(self):
        self.reflector = None
        self.kubernetes_api = None

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
        """Logic for handling a received resource. No error handling is
        performed here.

        Args:
            app (krake.data.kubernetes.Application): a newly received
                Application to handle.

        """

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

    async def error_handler(self, app, error=None):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Callback updates kubernetes application status to the failed state and
        describes the reason of the failure.

        Args:
            app (krake.data.kubernetes.Application): Application object processed
                when the error occurred
            error (str, optional): The reason of the exception which will be propagate
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


def main(config):
    krake_conf = load_config(config)

    setup_logging(krake_conf["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(krake_conf))
    scheduler_config = krake_conf["controllers"]["scheduler"]

    tls_config = scheduler_config.get("tls")
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    scheduler = Scheduler(
        api_endpoint=scheduler_config["api_endpoint"],
        worker_count=scheduler_config["worker_count"],
        ssl_context=ssl_context,
        debounce=scheduler_config.get("debounce", 0),
    )
    run(scheduler)


if __name__ == "__main__":
    parser = ArgumentParser(description="Garbage Collector for Krake")
    parser.add_argument("-c", "--config", help="Path to configuration YAML file")
    main(**vars(parser.parse_args()))
