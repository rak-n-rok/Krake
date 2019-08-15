import logging
from functools import partial
from krake.client.openstack import OpenStackApi
from krake.data.openstack import MagnumClusterState

from . import Controller, create_ssl_context, run, Reflector


_DELETION_FINIALIZER = "magnum_cluster_deletion"


logger = logging.getLogger("krake.controller.openstack")


class MagnumClusterController(Controller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.openstack_api = None
        self.reflector = None
        self.worker_count = worker_count

    async def prepare(self, client):
        self.client = client
        self.openstack_api = OpenStackApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        def scheduled_or_deleting(cluster):
            # Always cleanup deleted clusters even if they are in FAILED
            # state.
            if cluster.metadata.deleted:
                if (
                    cluster.metadata.finalizers
                    and cluster.metadata.finalizers[-1] == _DELETION_FINIALIZER
                ):
                    logger.debug("Accept deleted %r", cluster)
                    return True

                logger.debug("Reject deleted %r without finalizer", cluster)
                return False

            # Ignore all other failed clusters
            if cluster.status.state == MagnumClusterState.FAILED:
                logger.debug("Reject failed %r", cluster)
                return False

            # Accept scheduled clusters
            if cluster.status.project:
                logger.debug("Accept scheduled %r", cluster)
                return True

            logger.debug("Reject %r", cluster)
            return False

        receive_app = partial(self.simple_on_receive, condition=scheduled_or_deleting)

        self.reflector = Reflector(
            listing=self.openstack_api.list_all_magnum_clusters,
            watching=self.openstack_api.watch_all_magnum_clusters,
            on_list=receive_app,
            on_add=receive_app,
            on_update=receive_app,
            on_delete=receive_app,
        )
        self.register_task(self.reflector, name="Reflector")

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
            key, cluster = await self.queue.get()
            copy = deepcopy(cluster)

            try:
                await self.resource_received(copy)
            except ControllerError as err:
                await self.error_handler(copy, error=err)
            finally:
                await self.queue.done(key)
            if run_once:
                break  # TODO: should we keep this? Only useful for tests

    async def resource_received(self, cluster):
        logger.debug("Handle %r", cluster)
