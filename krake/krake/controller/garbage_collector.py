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
from functools import partial
from itertools import chain

from krake import setup_logging, load_config
from krake.api.database import Session, EventType
from krake.controller import Controller, run, Worker
from krake.data.core import resource_ref
from krake.client.kubernetes import KubernetesApi
from krake.data.kubernetes import Application, Cluster

logger = logging.getLogger("krake.api.garbage_collector")

_garbage_collected = {KubernetesApi.api_name: [Application, Cluster]}


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
        logger.debug(
            "Handling deletion of: %s",
            [cls.kind for cls in chain(*self.resources.values())],
        )
        tasks = [
            self.list_watch_resource(resource)
            for resource in chain(*self.resources.values())
        ]
        assert tasks
        await asyncio.gather(*tasks)

    async def list_watch_resource(self, api_object):
        """List and watch a specific kind of resource from the API.

        Args:
            api_object (krake.data.serializable.ApiObject): the definition of the
            resource to list and watch

        """
        async with Session(host=self.db_host, port=self.db_port) as session:

            async with session.watch(api_object) as watcher:
                await asyncio.gather(
                    self.list_resource(api_object, session),
                    self.watch_resource(api_object, watcher),
                )

    async def list_resource(self, apidef, session):
        """List the resources of the given API definition. Consider only
        the resources marked for deletion. Add them to the worker queue.

        Args:
            apidef: the API definition of the kind of resource to list
            session (krake.api.database.Session): an opened database session

        """
        logger.info("List %s %s", apidef.api, apidef.kind)

        async for resource in session.all(apidef):
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
        logger.info("Watching %s %s", apidef.api, apidef.kind)
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
        if not resource.metadata.owners:
            return

        for dependency_ref in resource.metadata.owners:
            cls = self._get_class_by_name(dependency_ref.api, dependency_ref.kind)
            dependency = await self.session.get(
                cls=cls, namespace=dependency_ref.namespace, name=dependency_ref.name
            )
            await self.session.put(dependency)

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

        def _in_owners(instance):
            return (
                instance.metadata.owners
                and resource_ref(entity) in instance.metadata.owners
            )

        # add all elements of current resource that have entity as dependency
        dependents = [
            dependent
            for resource in chain(*self.resources.values())
            async for dependent in self.session.all(resource)
            if _in_owners(dependent)
        ]

        return dependents


def main(config):
    krake_conf = load_config(config)

    db_host = krake_conf["etcd"]["host"]
    db_port = krake_conf["etcd"]["port"]

    gc_config = krake_conf["controllers"]["garbage_collector"]

    create_garbage_worker = partial(GarbageWorker, db_host=db_host, db_port=db_port)

    controller = GarbageCollector(
        api_endpoint=gc_config["api_endpoint"],
        worker_factory=create_garbage_worker,
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
