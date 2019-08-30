"""This module defines the Garbage Collector present as a background task on the API
application. When a resource is marked as deleted, the GC mark all its dependents as
deleted. After cleanup is done by the Controller, it handles the final deletion of
resources.
"""

import asyncio
import logging
from argparse import ArgumentParser

from krake import setup_logging, load_config
from krake.api.database import Session
from krake.apidefs.kubernetes import ClusterResource, ApplicationResource
from krake.controller import Controller, run, Worker
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


def main(args):
    config = load_config("krake.yaml")
    controller = GarbageCollector(
        api_endpoint="http://localhost:8080",
        worker_factory=GarbageWorker,
        worker_count=5,
    )
    setup_logging(config["log"])
    run(controller)


if __name__ == "__main__":
    parser = ArgumentParser(description="Kubernetes application controller")
    main(parser.parse_args())
