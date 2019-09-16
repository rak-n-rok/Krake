import logging

from krake.data.kubernetes import ApplicationState
from .. import Controller, Worker


logger = logging.getLogger(__name__)


class KubernetesController(Controller):
    async def list_and_watch(self):
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
