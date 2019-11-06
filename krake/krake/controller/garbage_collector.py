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
from argparse import ArgumentParser
from datetime import datetime
from itertools import chain

from aiohttp import ClientConnectorError
from krake import setup_logging, load_config, search_config
from krake.api.database import Session, EventType, TransactionError
from krake.controller import Controller, run
from krake.data.core import resource_ref
from krake.client.kubernetes import KubernetesApi
from krake.data.kubernetes import Application, Cluster

logger = logging.getLogger("krake.api.garbage_collector")

_garbage_collected = {KubernetesApi.api_name: [Application, Cluster]}


class DatabaseReflector(object):
    """Reimplementation of the :class:`krake.controller.Reflector` to watch the
    database using a session, instead of watching the API. One instance can only
    be used to list and watch one kind of resource.

    Args:
        on_receive (coroutine):
        api_def: the API definition of the kind of resource to list and watch.
        db_host (str): the host to connect to the database
        db_port (int): the port to connect to the database
    """

    def __init__(self, on_receive, api_def, db_host="localhost", db_port=2379):
        self.db_host = db_host
        self.db_port = db_port
        self.on_receive = on_receive
        self.api_def = api_def

    async def list_and_watch(self):
        """List and watch a specific kind of resource from the API.
        """
        async with Session(host=self.db_host, port=self.db_port) as session:

            async with session.watch(self.api_def) as watcher:
                await asyncio.gather(
                    self.list_resource(session), self.watch_resource(watcher)
                )

    async def list_resource(self, session):
        """List the resources of the given API definition. Consider only
        the resources marked for deletion. Add them to the worker queue.

        Args:
            session (krake.api.database.Session): an opened database session

        """
        logger.info("List %s %s", self.api_def.api, self.api_def.kind)

        async for resource in session.all(self.api_def):
            if resource.metadata.deleted:
                logger.debug("Received %r", resource)
                await self.on_receive(resource)

    async def watch_resource(self, watcher):
        """Watch the resources of the given API definition. Consider only
        the resources marked for deletion, but not the deleted ones.
        Add them to the worker queue.

        Args:
            watcher (krake.api.database.Watcher): a watcher on the database

        """
        logger.info("Watching %s %s", self.api_def.api, self.api_def.kind)
        async for event, resource, rev in watcher:
            if event != EventType.DELETE and resource.metadata.deleted:
                logger.debug("Received %r", resource)
                await self.on_receive(resource)

    async def __call__(self, max_retry=0):
        """Start the Reflector. Encapsulate the connections with a retry logic.

        Args:
            max_retry (int, optional): the number of times the connection should be
            retried. If 0 is given, it means it should be retried indefinitely

        """
        count = 0
        while count < max_retry or max_retry == 0:
            try:
                await self.list_and_watch()
            except ClientConnectorError as err:
                logger.error(err)
                await asyncio.sleep(1)
            finally:
                count += 1


class GarbageCollector(Controller):
    """Controller responsible for marking the dependents
    of a resource as deleted, and for deleting all resources without any finalizer.

    Args:
        worker_count (int, optional): the amount of worker function that should be
            run as background tasks.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.
        debounce (float, optional): value of the debounce for the :class:`WorkQueue`.
        db_host (str): the host to connect to the database
        db_port (int): the port to connect to the database

    """

    def __init__(
        self, worker_count=10, loop=None, debounce=0, db_host="localhost", db_port=2379
    ):
        # api_endpoint is set to an arbitrary value because it is not used, but needed
        # by the Controller initializer
        # TODO Will be removed with GC V2
        super().__init__("http://localhost", loop=loop, debounce=debounce)
        self.reflectors = []
        self.resources = _garbage_collected
        self.db_host = db_host
        self.db_port = db_port
        self.worker_count = worker_count

    async def prepare(self, client):
        assert client is not None
        self.client = client

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        # Create one reflector for each resource managed by the GC.
        for resource in chain(*self.resources.values()):
            reflector = DatabaseReflector(
                on_receive=self.simple_on_receive,
                api_def=resource,
                db_host=self.db_host,
                db_port=self.db_port,
            )
            self.reflectors.append(reflector)
            name = f"{resource.api}_{resource.kind}_Reflector"
            self.register_task(reflector, name=name)

    async def cleanup(self):
        self.reflectors = []

    async def handle_resource(self):
        """Infinite loop which fetches and hand over the resources to the right
        coroutine. This function is meant to be run as background task.
        """
        while True:
            key, resource = await self.queue.get()
            try:
                logger.debug("Handling resource %s", resource)
                await self.resource_received(resource)
            finally:
                await self.queue.done(key)

    async def resource_received(self, resource):
        """Handle the resources marked for deletion. Only one action is performed:
         * if the resource has DIRECT dependents, mark all of them as deleted;
         * if the resource has no finalizer, its dependencies will be updated, and the
         resource will be deleted;

        Args:
            resource (any): a resource marked for deletion

        """
        logger.debug("Received %r", resource_ref(resource))
        async with Session(host=self.db_host, port=self.db_port) as session:
            # If a transaction errors occurs -- which means that that the
            # etcd key was modified in between -- fetch the new version
            # from the store and retry the operation until. This is
            # repeated until the operation succeeds.
            while True:
                try:
                    # session is not an attribute of the GC because it needs to be
                    # started and stopped, but the GC holds several worker function,
                    # which can all access it.
                    return await self._cleanup(resource, session)
                except TransactionError as err:
                    logger.warning("Transaction error: %s. Reload resource.", err)
                    cls = self._get_class_by_name(resource.api, resource.kind)
                    resource = await session.get(
                        cls=cls,
                        namespace=resource.metadata.namespace,
                        name=resource.metadata.name,
                    )

    async def _cleanup(self, resource, session):
        # Check if there are dependents
        dependents = await self._get_dependents(resource, session)
        if dependents:
            logger.info("Delete dependencies of %s", resource_ref(resource))
            await self._mark_dependents(dependents, session)
            return

        # Delete a resource with no finalizer
        if not resource.metadata.finalizers:
            await self._delete_resource(resource, session)

    async def _delete_resource(self, resource, session):
        """Remove a resource from the database before updating its dependencies

        Args:
            resource: the resource to permanently remove.
            session (krake.api.database.Session): the database session to manage data

        """
        # Delete from database
        logger.info("%s completely deleted", resource_ref(resource))
        await session.delete(resource)

        await self._update_dependencies(resource, session)

    async def _update_dependencies(self, resource, session):
        """Retrieve and update all dependencies of a resource WITHOUT modifying them.

        Args:
            resource: the resource whose dependencies will be updated.
            session (krake.api.database.Session): the database session to manage data

        """
        if not resource.metadata.owners:
            return

        for dependency_ref in resource.metadata.owners:
            cls = self._get_class_by_name(dependency_ref.api, dependency_ref.kind)
            dependency = await session.get(
                cls=cls, namespace=dependency_ref.namespace, name=dependency_ref.name
            )
            if dependency.metadata.deleted:
                logger.info("Reenqueue %s", resource_ref(dependency))
                await self.resource_received(dependency)

    def _get_class_by_name(self, api_name, cls_name):
        """From the garbage collected resources, get the resource class that
        belongs to the given API name and referenced by the given class name.

        Args:
            api_name (str): the name of an API
            cls_name (str): the name of a class

        Returns:
            type: the class that corresponds to the given name

        Raises:
            ValueError: if the class cannot be found in the managed ones.

        """
        cls_list = self.resources.get(api_name)
        if cls_list is None:
            raise ValueError(f"API '{api_name}' not found.")

        for cls in cls_list:
            if cls.__name__ == cls_name:
                return cls
        else:
            raise ValueError(f"Class '{cls_name}' not found.")

    async def _mark_dependents(self, dependents, session):
        """Mark all given resources as deleted.

        Args:
            dependents (list): list of resources to mark as deleted.
            session (krake.api.database.Session): the database session to manage data

        """
        for dependent in dependents:
            if not dependent.metadata.deleted:
                logger.info("Delete dependent %s", resource_ref(dependent))
                dependent.metadata.deleted = datetime.now()
                await session.put(dependent)

    async def _get_dependents(self, entity, session):
        """Retrieve all direct dependents of a resource.

        Args:
            entity: the given resource
            session (krake.api.database.Session): the database session to manage data

        Returns:
            list: a list of all dependents of the given resource

        """

        def _in_owners(instance):
            return (
                instance.metadata.owners
                and resource_ref(entity) in instance.metadata.owners
            )

        # add all elements of current resource that have entity as dependency
        dependents = [
            dependent
            for resource in chain(*self.resources.values())
            async for dependent in session.all(resource)
            if _in_owners(dependent)
        ]

        return dependents


def main(config):
    gc_config = load_config(config or search_config("garbage_collector.yaml"))

    db_host = gc_config["etcd"]["host"]
    db_port = gc_config["etcd"]["port"]

    controller = GarbageCollector(
        worker_count=gc_config["worker_count"],
        db_host=db_host,
        db_port=db_port,
        debounce=gc_config.get("debounce", 0),
    )
    setup_logging(gc_config["log"])
    run(controller)


parser = ArgumentParser(description="Garbage Collector for Krake")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


if __name__ == "__main__":
    args = parser.parse_args()
    main(**vars(args))
