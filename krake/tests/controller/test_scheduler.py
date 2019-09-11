import asyncio

from krake.api.app import create_app
from krake.data.core import ReasonCode
from krake.data.kubernetes import Application, ApplicationState
from krake.controller import Worker
from krake.controller.scheduler import Scheduler, SchedulerWorker
from krake.client import Client
from krake.test_utils import server_endpoint

from factories.kubernetes import ApplicationFactory, ClusterFactory
from . import SimpleWorker


async def test_kubernetes_reception(aiohttp_server, config, db, loop):
    scheduled = ApplicationFactory(status__state=ApplicationState.SCHEDULED)
    updated = ApplicationFactory(status__state=ApplicationState.UPDATED)
    pending = ApplicationFactory(status__state=ApplicationState.PENDING)

    # Only PENDING and UPDATED applications are expected
    worker = SimpleWorker(
        expected={pending.metadata.uid, updated.metadata.uid}, loop=loop
    )
    server = await aiohttp_server(create_app(config))

    async with Scheduler(
        api_endpoint=server_endpoint(server),
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
    ) as scheduler:

        await db.put(scheduled)
        await db.put(updated)
        await db.put(pending)

        # There could be an error in the scheduler or the worker. Hence, we
        # wait for both.
        await asyncio.wait(
            [scheduler, worker.done], timeout=1, return_when=asyncio.FIRST_COMPLETED
        )

    assert worker.done.done()
    await worker.done  # If there is any exception, retrieve it here


async def test_kubernetes_scheduling(aiohttp_server, config, db, loop):
    cluster = ClusterFactory()
    app = ApplicationFactory(status__state=ApplicationState.UPDATED)

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)


async def test_kubernetes_scheduling_error_handling(aiohttp_server, config, db, loop):
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)
