"""This module defines the Garbage Collector present as a background task on the API
application. When a resource is marked as deleted, the GC mark all its dependents as
deleted. After cleanup is done by the respective Controller, the gc handles the final
deletion of resources.

Marking a resource as deleted (by setting the deleted timestamp of its metadata) is
irreversible: if the garbage collector receives such a resource, it will start the
complete deletion process, with no further user involvement.

The configuration should have the following structure:

.. code:: yaml

    api_endpoint: http://localhost:8080
    worker_count: 5
    debounce: 1
    tls:
      enabled: false
      client_ca: tmp/pki/ca.pem
      client_cert: tmp/pki/system:gc.pem
      client_key: tmp/pki/system:gc-key.pem

"""

import logging
from argparse import ArgumentParser
from collections import defaultdict
from copy import deepcopy

from krake import setup_logging, load_config, search_config
from krake.apidefs.kubernetes import ApplicationResource, ClusterResource
from krake.controller import Controller, run, Reflector, create_ssl_context
from krake.data.core import resource_ref
from krake.client.kubernetes import KubernetesApi
from krake.data.kubernetes import Application, Cluster

logger = logging.getLogger("krake.controller.garbage_collector")


class DependencyGraph(object):
    """Representation of the dependencies of all Krake resources by an acyclic
    directed graph. This graph can be used to get the dependents of any resource that
    the graph received.

    If an instance of a resource A depends on a resource B, A will have B in its owner
    list. In this case,
     * A depends on B
     * B is a dependency of A
     * A is a dependent of B

    The nodes of the graph are :class:`krake.data.core.ResourceRef`, created from the
    actual resources. The edges are directed links from a dependency to its dependents.

    :class:`krake.data.core.ResourceRef` are used instead of the resource directly, as
    they are hashable and can be used as key of a dictionary. Otherwise, we would need
    to make any newly added resource as hashable for the sake of the dependency graph.

    The actual resources are still referenced in the :attr:`_resources`. It allows the
    access to the actual owners of a resource, not their
    :class:`krake.data.core.ResourceRef`.
    """

    def __init__(self):
        self._relationships = defaultdict(list)
        self._resources = {}

    def get_direct_dependents(self, resource):
        """Get the dependents of a resource, but only the ones directly dependent, no
        recursion is performed.

        Args:
            resource (krake.data.serializable.Serializable): the resource for which#
                the search will be performed.

        Returns:
            list: the list of :class:`krake.data.core.ResourceRef` to the dependents
                of the given resource (=that depends on the resource).

        """
        references = self._relationships[resource_ref(resource)]
        return [self._resources[reference] for reference in references]

    def add_resource(self, resource):
        """Add a resource and its dependencies relationships to the graph.

        Args:
            resource (krake.data.serializable.Serializable): the resource to add to
                the graph.

        """
        resource = deepcopy(resource)
        res_ref = resource_ref(resource)
        self._resources[res_ref] = resource

        # No need to add the value explicitly here,
        # as it is lazy created in the cycles check

        for owner in resource.metadata.owners:
            self._relationships[owner].append(res_ref)

        self._check_for_cycles(res_ref)

    def remove_resource(self, resource, check_dependents=True):
        """If a resource has no dependent, remove it from the dependency graph,
        and from the dependents of other resources.

        Args:
            resource (krake.data.serializable.Serializable): the resource to remove.
            check_dependents (bool, optional): if False, does not check if the
                resource to remove has dependents, and simply remove it along with the
                 dependents.

        Raises:
            ValueError: if the resource to remove has dependents.

        """
        res_ref = resource_ref(resource)
        del self._resources[res_ref]

        if check_dependents and self._relationships[res_ref]:
            raise ValueError("Cannot remove a resource which holds dependents")

        del self._relationships[res_ref]

        # Remove "pointers" to the resources from any dependency
        # All dependents need to be checked because the owners
        # may not be consistent anymore (e.g with migration).
        for dependents in self._relationships.values():
            if res_ref in dependents:
                dependents.remove(res_ref)

    def update_resource(self, resource):
        """Update the dependency relationships of a resource on the graph.

        Args:
            resource (krake.data.serializable.Serializable): the resource whose
                ownership may need to be modified.

        """
        resource = deepcopy(resource)
        stored = self._resources[resource_ref(resource)]

        # If no update has been done on the dependency relations of the resource,
        # simply update its reference.
        if resource.metadata.owners == stored.metadata.owners:
            self._resources[resource_ref(resource)] = resource
            return

        dependents = self.get_direct_dependents(resource)

        # This action removes the dependents entirely,
        # that is why they need to be stored beforehand.
        self.remove_resource(resource, check_dependents=False)
        self.add_resource(resource)

        dependents_references = [resource_ref(resource) for resource in dependents]
        self._relationships[resource_ref(resource)] = dependents_references

    def _check_for_cycles(self, reference, visited=None):
        """Verify if a cycle exists in the graph.

        Args:
            reference (krake.data.core.ResourceRef): the resource from which the
                search should be started.
            visited (set, optional): the set of already visited nodes. Should be empty
                when calling the function.

        Raises:
            RuntimeError: raised if a cycle has been discovered.

        """
        if not visited:
            visited = set()

        if reference in visited:
            raise RuntimeError(f"Cycle in dependency graph for resource {reference}")

        visited.add(reference)
        # Empty relationships are lazy created here
        for dependent in self._relationships[reference]:
            self._check_for_cycles(dependent, visited)

    def get_owners(self, resource):
        """Retrieve the actual owners (not references) of a resource.

        Args:
            resource (krake.data.serializable.Serializable): the instances of the
                owners of this resource will be retrieved.

        Returns:
            list: the list of owners of the given resource.

        """
        owners_refs = resource.metadata.owners
        return [self._resources[owner_ref] for owner_ref in owners_refs]


class GarbageCollector(Controller):
    """Controller responsible for marking the dependents
    of a resource as deleted, and for deleting all resources without any finalizer.

    Args:
        api_endpoint (str): URL to the API
        worker_count (int, optional): the amount of worker function that should be
            run as background tasks.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.
        ssl_context (ssl.SSLContext, optional): if given, this context will be
            used to communicate with the API endpoint.
        debounce (float, optional): value of the debounce for the
            :class:`WorkQueue`.

    """

    def __init__(
        self, api_endpoint, worker_count=10, loop=None, ssl_context=None, debounce=0
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.apis = {}
        self.reflectors = []
        self.worker_count = worker_count

        self.resources = {
            KubernetesApi: [
                (Application, ApplicationResource),
                (Cluster, ClusterResource),
            ]
        }
        self.graph = DependencyGraph()

    async def prepare(self, client):
        assert client is not None
        self.client = client

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        # Create one reflector for each kind of resource managed by the GC.
        for api_cls, kind_list in self.resources.items():
            api = api_cls(self.client)

            # For each selected resource of the current API
            for kind, client_resource in kind_list:
                self.apis[kind] = api

                resource_plural = client_resource.plural.lower()
                list_resources = getattr(api, f"list_all_{resource_plural}")
                watch_resources = getattr(api, f"watch_all_{resource_plural}")

                reflector = Reflector(
                    listing=list_resources,
                    watching=watch_resources,
                    on_list=self.on_received_new,
                    on_add=self.on_received_new,
                    on_update=self.on_received_update,
                    on_delete=self.on_received_deleted,
                    loop=self.loop,
                    resource_plural=client_resource.plural,
                )
                self.reflectors.append(reflector)

                name = f"{kind.api}_{kind.kind}_Reflector"
                self.register_task(reflector, name=name)

    @staticmethod
    def is_in_deletion(resource):
        """Check if a resource needs to be deleted or not.

        Args:
            resource (krake.data.serializable.Serializable): the resource to check.

        Returns:
            bool: True if the given resource is in deletion state, False otherwise.

        """
        if (
            resource.metadata.deleted
            and resource.metadata.finalizers
            and resource.metadata.finalizers[-1] == "cascade_deletion"
        ):
            return True

        logger.debug("Rejected resource %r", resource)
        return False

    async def on_received_new(self, resource):
        """To be called when a resource is received for the first time by the garbage
        collector. Add the resource to the dependency graph and handle the resource if
        accepted.

        Args:
            resource (krake.data.serializable.Serializable): the newly added resource.

        """
        self.graph.add_resource(resource)
        await self.simple_on_receive(resource, condition=self.is_in_deletion)

    async def on_received_update(self, resource):
        """To be called when a resource is updated on the API. Update the resource on
        the dependency graph and handle the resource if accepted.

        Args:
            resource (krake.data.serializable.Serializable): the updated resource.

        """
        self.graph.update_resource(resource)
        await self.simple_on_receive(resource, condition=self.is_in_deletion)

    async def on_received_deleted(self, resource):
        """To be called when a resource is deleted on the API. Remove the resource
        from the dependency graph and add its dependencies to the Worker queue.

        Args:
            resource (krake.data.serializable.Serializable): the deleted resource.

        """
        for dependency in self.graph.get_owners(resource):
            await self.queue.put(dependency.metadata.uid, dependency)

        self.graph.remove_resource(resource)

    async def cleanup(self):
        self.reflectors = []
        self.apis = {}
        self.graph = None

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
        """Core functionality of the garbage collector. Mark the given resource's
        direct dependents as to be deleted, or remove the deletion finalizer if the
        resource has no dependent.

        Args:
            resource (krake.data.serializable.Serializable): a resource in deletion
                state.

        """
        logger.debug("Received %r", resource_ref(resource))

        dependents = self.graph.get_direct_dependents(resource)
        if dependents:
            await self._mark_dependents(dependents)
        else:
            logger.debug("Resource has no dependent anymore: %s", resource)
            await self._remove_cascade_deletion_finalizer(resource)

    async def _mark_dependents(self, dependents):
        """Request the deletion of a list of resources.

        Args:
            dependents (list): the list of resources to delete.

        """
        for dependent in dependents:
            api = self.apis[type(dependent)]
            kind = dependent.kind.lower()
            delete_resource = getattr(api, f"delete_{kind}")

            logger.info("Mark dependent as deleted: %s", resource_ref(dependent))
            await delete_resource(
                namespace=dependent.metadata.namespace, name=dependent.metadata.name
            )

    async def _remove_cascade_deletion_finalizer(self, resource):
        """Update the given resource to remove its garbage-collector-specific
        finalizer.

        Args:
            resource (krake.data.serializable.Serializable): the finalizer will be
                removed from this resource.

        """
        api = self.apis[type(resource)]
        kind = resource.kind.lower()
        update_resource = getattr(api, f"update_{kind}")

        finalizer = resource.metadata.finalizers.pop(-1)
        assert finalizer == "cascade_deletion"
        logger.info("Resource ready for deletion: %s", resource_ref(resource))
        await update_resource(
            namespace=resource.metadata.namespace,
            name=resource.metadata.name,
            body=resource,
        )


def main(config):
    gc_config = load_config(config or search_config("garbage_collector.yaml"))

    setup_logging(gc_config["log"])

    tls_config = gc_config.get("tls")
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = GarbageCollector(
        api_endpoint=gc_config["api_endpoint"],
        worker_count=gc_config["worker_count"],
        ssl_context=ssl_context,
        debounce=gc_config.get("debounce", 0),
    )
    setup_logging(gc_config["log"])
    run(controller)


if __name__ == "__main__":
    parser = ArgumentParser(description="Garbage Collector for Krake")
    parser.add_argument("-c", "--config", help="Path to configuration YAML file")

    args = parser.parse_args()
    main(**vars(args))
