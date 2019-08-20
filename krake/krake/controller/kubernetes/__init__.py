import logging
from .. import Controller

logger = logging.getLogger("krake.controller.kubernetes.cluster")


class KubernetesController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in "SCHEDULED" and "DELETING" state.
    """

    async def list_and_watch(self):
        """List and watching Kubernetes applications in the ``SCHEDULED``
        state.
        """
        resource_client = getattr(self.client.kubernetes, self.resource_name)

        logger.info("List Resource")
        for resource in await resource_client.list(namespace="all"):
            logger.debug("Received %r", resource)
            if resource.status.state in self.states:
                await self.queue.put(resource.metadata.uid, resource)

        logger.info("Watching Resource")
        async with resource_client.watch(namespace="all") as watcher:
            async for resource in watcher:
                logger.debug("Received %r", resource)
                if resource.status.state in self.states:
                    await self.queue.put(resource.metadata.uid, resource)
