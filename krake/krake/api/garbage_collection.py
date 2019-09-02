"""This module defines the Garbage Collector present as a background task on the API
application. When a resource is marked as deleted, the GC mark all its dependents as
deleted. After cleanup is done by the Controller, it handles the final deletion of
resources.

Configuration is loaded from the ``controllers.garbage_collector`` section:

.. code:: yaml

    controllers:
      garbage_collector:
        api_endpoint: http://localhost:8080
        worker_count: 5

"""

import asyncio
import logging

from aiohttp import ClientResponseError, ClientConnectorError
from krake.api.database import Session
from krake.apidefs.kubernetes import ClusterResource, ApplicationResource
from krake.controller import Controller, Worker
from krake.client import Client
from krake.client.kubernetes import KubernetesApi
from krake.data.core import resource_ref, WatchEventType

from ..utils import camel_to_snake_case

logger = logging.getLogger("krake.api.garbage_collector")

RESOURCES = [ClusterResource, ApplicationResource]


class GarbageCollector(Controller):
    """The Garbage Collector is a Controller that is watching all kind of resources
    stored in the database. It is the only component with the right to remove the
    "cascading_deletion" finalizer.
    """

    resources = RESOURCES

    async def list_and_watch(self):
        """Create a task to list and watch each persistent resource
        """
        # TODO: not only KubernetesAPI, also OpenStack
        kubernetes_api = KubernetesApi(self.client)
        tasks = [
            self.list_watch_resource(resource, kubernetes_api)
            for resource in self.resources
        ]
        await asyncio.gather(*tasks)

    async def list_watch_resource(self, resource_def, api):
        """List and watch a specific kind of resource from the API. Consider only the
        resources marked for deletion. Add them to the worker queue.

        Args:
            resource_def (krake.api.core.ResourceRef):
            api: API handler for watched resource

        """

        def marked_for_deletion(resource):
            return resource.metadata.deleted

        async def list_resource():
            logger.info("List %r %r", resource_def.api, resource_def.singular)

            # TODO change
            name_list = f"list_all_{camel_to_snake_case(resource_def.plural)}"
            api_list_resources = getattr(api, name_list)

            resource_list = await api_list_resources()
            for resource in filter(marked_for_deletion, resource_list.items):
                logger.debug("Received %r", resource)
                await self.queue.put(resource.metadata.uid, resource)

        async def watch_resource(watcher):
            logger.info("Watching %r %r", resource_def.api, resource_def.singular)
            async for event in watcher:
                resource = event.object
                if (
                    marked_for_deletion(resource)
                    and event.type != WatchEventType.DELETED
                ):
                    logger.debug("Received %r", resource)
                    await self.queue.put(resource.metadata.uid, resource)

        # TODO change
        name = f"watch_all_{camel_to_snake_case(resource_def.plural)}"
        api_watch_resources = getattr(api, name)

        async with api_watch_resources() as watcher:
            await asyncio.gather(list_resource(), watch_resource(watcher))


class GarbageWorker(Worker):
    """Worker for :class:`GarbageCollector` responsible for marking the dependents
    of a resource as deleted, and for deleting all resources without any finalizer.
    """

    def __init__(self, client=None, etcd_host="localhost", etcd_port=2379):
        super(GarbageWorker, self).__init__(client=client)
        self.etcd_host = etcd_host
        self.etcd_port = etcd_port

    api_mapping = {}

    def _get_api(self, resource_api):
        """Get an API handler using its name

        Args:
            resource_api (str): the name of the API handler

        Returns:
            The corresponding API handler

        """
        api_name = f"{resource_api.title()}Api"
        api = globals()[api_name](self.client)  # TODO change!!!
        return api

    async def resource_received(self, resource):
        """Handle the resources marked for deletion. Only one action is performed:
         * if the resource has no finalizer, its dependencies will be updated, and the
         resource will be deleted;
         * if the resource has DIRECT dependents, mark all of them as deleted;
         * when no dependent is present, or all have been deleted, remove the
         "cascading_deletion" finalizer on the resource and update it.

        Args:
            resource (any): a resource marked for deletion

        """
        # Delete a resource with no finalizer
        if not resource.metadata.finalizers:
            await self._delete_resource(resource)
            return

        # Check if there are dependents
        dependents_list = await self._get_dependents(resource)
        if dependents_list:
            await self._mark_dependents(dependents_list)
        else:
            await self._remove_finalizer(resource)

    async def _delete_resource(self, resource):
        """Update the dependencies of a resource before removing it from the database.

        Args:
            resource: the resource to permanently remove.

        """
        await self._update_dependencies(resource)

        # Delete from database
        # TODO change!!!
        async with Session(host=self.etcd_host, port=self.etcd_port) as session:
            await session.delete(resource)

    async def _update_dependencies(self, resource):
        """Retrieve and update all dependencies of a resource WITHOUT modifying them.

        Args:
            resource: the resource whose dependencies will be updated.

        """
        if not resource.status.depends:
            return

        for dependency_ref in resource.status.depends:
            api = self._get_api(dependency_ref.api)
            name = f"read_{camel_to_snake_case(dependency_ref.kind)}"
            api_get_dependency = getattr(api, name)

            dependency = await api_get_dependency(
                namespace=dependency_ref.namespace, name=dependency_ref.name
            )

            # TODO change
            name = f"update_{camel_to_snake_case(dependency.kind)}"
            api_update_dependency = getattr(api, name)

            await api_update_dependency(  # TODO change
                namespace=dependency.metadata.namespace,
                name=dependency.metadata.name,
                body=dependency,
            )

    async def _mark_dependents(self, resource_list):
        """Mark all given resources as deleted.

        Args:
            resource_list (list): list of resources to mark as deleted.

        """
        for resource in resource_list:
            api = self._get_api(resource.api)
            name = f"delete_{camel_to_snake_case(resource.kind)}"
            api_delete_resource = getattr(api, name)

            await api_delete_resource(
                namespace=resource.metadata.namespace, name=resource.metadata.name
            )

    async def _get_dependents(self, entity):
        """Retrieve all direct dependents of a resource.

        Args:
            entity: the given resource

        Returns:
            list: a list of all dependents of the given resource

        """
        all_dependents = []
        # TODO change!!!
        async with Session(host=self.etcd_host, port=self.etcd_port) as session:

            def _in_depends(resource):
                return (
                    resource.status.depends
                    and resource_ref(entity) in resource.status.depends
                    and resource.metadata.deleted is None
                )

            for resource_def in RESOURCES:

                # TODO change
                for operation in resource_def.operations:
                    if operation.name == "Create":
                        resource = operation.body
                        break
                else:
                    raise ValueError("Body not found")

                all_resources = session.all(resource)

                # add all elements of current resource that have entity as dependency
                all_dependents.extend(
                    [
                        resource
                        async for resource, _ in all_resources
                        if _in_depends(resource)
                    ]
                )

        return all_dependents

    async def _remove_finalizer(self, resource):
        """Remove the "cascading_deletion" finalizer from a resource if present,
        then update it

        Args:
            resource: the resource to update

        """
        if resource.metadata.finalizers[-1] == "cascading_deletion":
            # Remove the last finalizer
            resource.metadata.finalizers.pop(-1)

            # TODO change
            api = self._get_api(resource.api)
            name = f"update_{camel_to_snake_case(resource.kind)}"
            api_update_dependency = getattr(api, name)

            await api_update_dependency(
                namespace=resource.metadata.namespace,
                name=resource.metadata.name,
                body=resource,
            )


async def register_garbage_collection(app):
    """This function needs to be registered as a handler for the "on_startup" signal
    of an aiohttp web application.
    Store the Garbage Collection task as an aiohttp background task.

    Args:
        app: the application that fired the signal. The created task will be
        registered to this web application.

    """
    config = app["config"]
    gc_config = config["controllers"]["garbage_collector"]
    etcd_host = config["etcd"]["host"]
    etcd_port = config["etcd"]["port"]

    app["gc"] = app.loop.create_task(run_gc(gc_config, etcd_host, etcd_port))


async def cleanup_garbage_collection(app):
    """This function needs to be registered as a handler for the "on_cleanup" signal
    of an aiohttp web application.
    Cancel the Garbage Collection task.

    Args:
        app: the application that fired the signal.

    """
    app["gc"].cancel()
    try:
        await app["gc"]
    except asyncio.CancelledError:
        logger.info("Garbage Collector has been cancelled")


async def run_gc(config, etcd_host, etcd_port):
    """Start the Garbage Collector and restart it in case of failure.

    Args:
        config (dict): configuration of the Garbage Collector Controller
        etcd_host (str): host of the etcd database for direct access
        etcd_port (int): port of the etcd database for direct access

    """
    while True:
        try:
            await start_garbage_collector(config, etcd_host, etcd_port)
        except asyncio.TimeoutError:
            logger.warn("Timeout")
        except ClientConnectorError as err:
            logger.error(err)
            await asyncio.sleep(1)
        except Exception as err:
            logger.error(
                f"The Garbage Collector has encountered an error: "
                f"{type(err)}, {err.args}"
            )
            await asyncio.sleep(1)


async def start_garbage_collector(config, etcd_host, etcd_port):
    """When the API is started, create the Garbage Collector and await it.

    Args:
        config (dict): configuration of the Garbage Collector Controller
        etcd_host (str): host of the etcd database for direct access
        etcd_port (int): port of the etcd database for direct access

    """
    api_endpoint = config["api_endpoint"]

    await _is_api_ready(api_endpoint)

    controller = GarbageCollector(
        api_endpoint=api_endpoint,
        worker_factory=_create_garbage_worker(etcd_host, etcd_port),
        worker_count=config["worker_count"],
    )
    async with controller:
        logger.info("Garbage Collector is started")
        await controller


async def _is_api_ready(api_endpoint, timeout=10):
    """Block until the API can be reached.

    Args:
        api_endpoint (str): the complete endpoint of the API
        timeout (int, optional): the amount of seconds to wait for the API to be up

    Raises:
        asyncio.TimeoutError: if the API cannot be reached after the timeout

    """

    async def wait_for_api():
        while True:
            client = Client(url=api_endpoint)
            try:
                # Only stops when a connection is possible
                await client.open()
                await client.session.get(api_endpoint)
                return
            except ClientResponseError as err:
                if err.status != 404:
                    raise
            finally:
                await client.close()

            # Try again if the error status was 404
            await asyncio.sleep(1)

    await asyncio.wait_for(wait_for_api(), timeout)


def _create_garbage_worker(etcd_host, etcd_port):
    """Factory to create an instance of :class:`GarbageWorker` with the etcd
    connection parameters.

    Args:
        etcd_host (str): host of the etcd database for direct access
        etcd_port (int): port of the etcd database for direct access

    Returns:
        function: the factory to create the workers

    """

    def worker_factory(client):
        return GarbageWorker(client, etcd_host=etcd_host, etcd_port=etcd_port)

    return worker_factory
