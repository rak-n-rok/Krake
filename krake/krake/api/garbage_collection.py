"""This module defines the Garbage Collector present as a background task on the API
application. When a resource is marked as deleted, the GC mark all its dependents as
deleted. After cleanup is done by the Controller, it handles the final deletion of
resources.

Important: the Garbage Collector does not handle conflicts: the API is the one that
should decide if a resource can be marked as deleted even if it has dependents. The
Garbage Collector only handles resources after they are marked.

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
from krake.apidefs import get_collected_resources
from krake.controller import Controller, Worker
from krake.client import Client
from krake.client.core import CoreApi
from krake.client.kubernetes import KubernetesApi
from krake.data.core import resource_ref, WatchEventType

from ..utils import camel_to_snake_case

logger = logging.getLogger("krake.api.garbage_collector")


def _create_api_mapping(list_apis):
    """From all API clients supported by the Garbage Collector, create a mapping
    that match the API name to them.

    Args:
        list_apis (list): the list of supported API clients.

    Returns:
        dict: the mapping "<api_name>: <api_client>"

    """
    return {api.api_name: api for api in list_apis}


_api_client_mapping = _create_api_mapping([CoreApi, KubernetesApi])


class GarbageCollector(Controller):
    """The Garbage Collector is a Controller that is watching all kind of resources
    stored in the database. It is the only component with the right to remove the
    "cascading_deletion" finalizer.
    """

    resources = get_collected_resources()

    async def list_and_watch(self):
        """Create a task to list and watch each persistent resource
        """
        logger.debug(
            "Handling deletion of: %s",
            [cls.singular for cls in self.resources.values()],
        )
        tasks = [
            self.list_watch_resource(resource) for resource in self.resources.values()
        ]
        await asyncio.gather(*tasks)

    async def list_watch_resource(self, resource_def):
        """List and watch a specific kind of resource from the API. Consider only the
        resources marked for deletion. Add them to the worker queue.

        Args:
            resource_def (krake.api.core.ResourceRef):

        """

        def marked_for_deletion(resource):
            return resource.metadata.deleted

        async def list_resource():
            logger.info("List %r %r", resource_def.api, resource_def.singular)

            list_resources = _api_client_handler(
                self.client, resource_def, "list_all", plural=resource_def.plural
            )

            resource_list = await list_resources()
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

        watch_resources = _api_client_handler(
            self.client, resource_def, "watch_all", plural=resource_def.plural
        )

        async with watch_resources() as watcher:
            await asyncio.gather(list_resource(), watch_resource(watcher))


def _api_client_handler(client, resource, verb, plural=None):
    """Get the API client handler that corresponds to a given resource and verb.
    If the plural form of the resource is given, it is used instead of the kind.

    Args:
        client (krake.client.Client): client used to create the API handler
        resource: the resource targeted
        verb (str): the verb corresponding to the wanted operation
        plural (str, optional): the plural form of the name of the resource

    Returns:
        callable: the handler for the given resource that does the :attr:`verb`
            operation

    """
    if plural:
        name = f"{verb}_{camel_to_snake_case(plural)}"
    else:
        name = f"{verb}_{camel_to_snake_case(resource.kind)}"

    api = _api_client_mapping[resource.api](client)
    return getattr(api, name)


class GarbageWorker(Worker):
    """Worker for :class:`GarbageCollector` responsible for marking the dependents
    of a resource as deleted, and for deleting all resources without any finalizer.
    """

    def __init__(self, client=None, etcd_host="localhost", etcd_port=2379):
        super(GarbageWorker, self).__init__(client=client)
        self.etcd_host = etcd_host
        self.etcd_port = etcd_port

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
        async with Session(host=self.etcd_host, port=self.etcd_port) as session:
            logger.debug(
                "%s %r completely deleted", resource.kind, resource.metadata.name
            )
            await session.delete(resource)

    async def _update_dependencies(self, resource):
        """Retrieve and update all dependencies of a resource WITHOUT modifying them.

        Args:
            resource: the resource whose dependencies will be updated.

        """
        if not resource.status.depends:
            return

        for dependency_ref in resource.status.depends:
            get_dependency = _api_client_handler(self.client, dependency_ref, "read")
            dependency = await get_dependency(
                namespace=dependency_ref.namespace, name=dependency_ref.name
            )

            update_dependency = _api_client_handler(self.client, dependency, "update")
            await update_dependency(
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
            delete_resource = _api_client_handler(self.client, resource, "delete")
            await delete_resource(
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
        async with Session(host=self.etcd_host, port=self.etcd_port) as session:

            def _in_depends(resource):
                return (
                    resource.status.depends
                    and resource_ref(entity) in resource.status.depends
                    and resource.metadata.deleted is None
                )

            for resource in get_collected_resources():
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

            update_dependency = _api_client_handler(self.client, resource, "update")
            await update_dependency(
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
        callable: the factory to create the workers

    """

    def worker_factory(client):
        return GarbageWorker(client, etcd_host=etcd_host, etcd_port=etcd_port)

    return worker_factory
