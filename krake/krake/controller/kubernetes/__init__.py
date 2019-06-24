"""Module for Krake controller responsible for
:class:`krake.data.kubernetes.Application` resources.
"""
import logging

from krake.data.kubernetes import ApplicationState
from .. import Controller, Worker


logger = logging.getLogger(__name__)


class KubernetesController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in ``SCHEDULED`` state.
    """

    async def list_and_watch(self):
        """List and watching Kubernetes applications in the ``SCHEDULED``
        state.
        """
        logger.debug("List Application")
        for app in await self.client.kubernetes.application.list():
            logger.debug("Received %r", app)
            if app.status.state == ApplicationState.SCHEDULED:
                await self.queue.put(app.id, app)

        while True:
            logger.debug("Watching Application")
            async for app in self.client.kubernetes.application.watch():
                logger.debug("Received %r", app)
                if app.status.state == ApplicationState.SCHEDULED:
                    await self.queue.put(app.id, app)


class KubernetesWorker(Worker):
    pass
