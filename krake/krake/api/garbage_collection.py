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

from krake import setup_logging, load_config
from krake.api.database import Session, EventType
from krake.controller import Controller, run, Worker
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, Cluster

logger = logging.getLogger("krake.api.garbage_collector")

_garbage_collected = [Application, Cluster]


class GarbageCollector(Controller):
    """The Garbage Collector is a Controller that is watching all kind of resources
    stored in the database.
    """

    def __init__(self, *args, db_host="localhost", db_port=2379, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_host = db_host
        self.db_port = db_port
        self.resources = _garbage_collected

    async def list_and_watch(self):
        """Create a task to list and watch each persistent resource
        """
        logger.debug("Handling deletion of: %s", [cls.kind for cls in self.resources])
        tasks = [self.list_watch_resource(resource) for resource in self.resources]
        assert tasks
        await asyncio.gather(*tasks)

    async def list_watch_resource(self, apidef):
        """List and watch a specific kind of resource from the API.

        Args:
            apidef (krake.api.core.ResourceRef):

        """
        async with Session(host=self.db_host, port=self.db_port) as session:

            async with session.watch(apidef) as watcher:
                await asyncio.gather(
                    self.list_resource(apidef, session),
                    self.watch_resource(apidef, watcher),
                )

    async def list_resource(self, apidef, session):
        """List the resources of the given API definition. Consider only
        the resources marked for deletion. Add them to the worker queue.

        Args:
            apidef: the API definition of the kind of resource to list
            session (krake.api.database.Session): an opened database session

        """
        logger.info("List %r %r", apidef.api, apidef.kind)

        resource_list = session.all(apidef)

        async for resource, _ in resource_list:
            if resource.metadata.deleted:
                logger.debug("Received %r", resource)
                await self.queue.put(resource.metadata.uid, resource)

    async def watch_resource(self, apidef, watcher):
        """Watch the resources of the given API definition. Consider only
        the resources marked for deletion, but not the deleted ones.
        Add them to the worker queue.

        Args:
            apidef: the API definition of the kind of resource to list
            watcher (krake.api.database.Watcher): a watcher on the database

        """
        logger.info("Watching %r %r", apidef.api, apidef.kind)
        async for event, resource, rev in watcher:
            if event != EventType.DELETE and resource.metadata.deleted:
                logger.debug("Received %r", resource)
                await self.queue.put(resource.metadata.uid, resource)


class GarbageWorker(Worker):
    """Worker for :class:`GarbageCollector` responsible for marking the dependents
    of a resource as deleted, and for deleting all resources without any finalizer.
    """

    def __init__(self, client=None, db_host="localhost", db_port=2379):
        super(GarbageWorker, self).__init__(client=client)
        self.db_host = db_host
        self.db_port = db_port
        self.session = None
        self.resources = _garbage_collected

    async def resource_received(self, resource):
        """Handle the resources marked for deletion. Only one action is performed:
         * if the resource has DIRECT dependents, mark all of them as deleted;
         * if the resource has no finalizer, its dependencies will be updated, and the
         resource will be deleted;

        Args:
            resource (any): a resource marked for deletion

        """
        logger.debug(
            "Worker received %s %s %s",
            resource.api,
            resource.kind,
            resource.metadata.name,
        )
        async with Session(host=self.db_host, port=self.db_port) as session:
            self.session = session

            # Check if there are dependents
            dependents_list = await self._get_dependents(resource)
            if dependents_list:
                await self._mark_dependents(dependents_list)
                self.session = None
                return

            # Delete a resource with no finalizer
            if not resource.metadata.finalizers:
                await self._delete_resource(resource)

            self.session = None

    async def _delete_resource(self, resource):
        """Remove a resource from the database before updating its dependencies

        Args:
            resource: the resource to permanently remove.

        """
        # Delete from database
        logger.debug("%s %r completely deleted", resource.kind, resource.metadata.name)
        await self.session.delete(resource)

        await self._update_dependencies(resource)

    async def _update_dependencies(self, resource):
        """Retrieve and update all dependencies of a resource WITHOUT modifying them.

        Args:
            resource: the resource whose dependencies will be updated.

        """
        if not resource.status.depends:
            return

        for dependency_ref in resource.status.depends:
            cls = self._get_class_by_name(dependency_ref.kind)
            dependency, _ = await self.session.get(
                cls=cls, namespace=dependency_ref.namespace, name=dependency_ref.name
            )
            await self.session.put(dependency)

    def _get_class_by_name(self, name):
        """From the managed resources, get the resource class that is
        referenced by the given name.

        Args:
            name (str): the name of a class

        Returns:
            type: the class that corresponds to the given name

        Raises:
            ValueError: if the class cannot be found in the managed ones.

        """
        for cls in self.resources:
            if cls.__name__ == name:
                return cls
        else:
            raise ValueError(f"Class '{name}' not found.")

    async def _mark_dependents(self, resource_list):
        """Mark all given resources as deleted.

        Args:
            resource_list (list): list of resources to mark as deleted.

        """
        for resource in resource_list:
            if resource.metadata.deleted:
                continue
            resource.metadata.deleted = datetime.now()
            await self.session.put(resource)

    async def _get_dependents(self, entity):
        """Retrieve all direct dependents of a resource.

        Args:
            entity: the given resource

        Returns:
            list: a list of all dependents of the given resource

        """
        all_dependents = []

        def _in_depends(instance):
            return (
                instance.status.depends
                and resource_ref(entity) in instance.status.depends
            )

        for resource in self.resources:
            all_resources = self.session.all(resource)

            # add all elements of current resource that have entity as dependency
            all_dependents.extend(
                [
                    resource
                    async for resource, _ in all_resources
                    if _in_depends(resource)
                ]
            )

        return all_dependents


def _create_garbage_worker(db_host, db_port):
    """Factory to create an instance of :class:`GarbageWorker` with the
    database connection parameters.

    Args:
        db_host (str): host of the database for direct access
        db_port (int): port of the database for direct access

    Returns:
        callable: the factory to create the workers

    """

    def worker_factory(client):
        return GarbageWorker(client, db_host=db_host, db_port=db_port)

    return worker_factory


def main(config):
    krake_conf = load_config(config)

    db_host = krake_conf["etcd"]["host"]
    db_port = krake_conf["etcd"]["port"]

    gc_config = krake_conf["controllers"]["garbage_collector"]

    controller = GarbageCollector(
        api_endpoint=gc_config["api_endpoint"],
        worker_factory=_create_garbage_worker(db_host, db_port),
        worker_count=gc_config["worker_count"],
        db_host=db_host,
        db_port=db_port,
        debounce=gc_config.get("debounce", 0),
    )
    setup_logging(krake_conf["log"])
    run(controller)


if __name__ == "__main__":
    parser = ArgumentParser(description="Garbage Collector for Krake")
    parser.add_argument("-c", "--config", help="Path to configuration YAML file")
    main(**vars(parser.parse_args()))
