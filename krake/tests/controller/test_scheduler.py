from krake.api.app import create_app
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import ApplicationState, Application
from krake.controller.scheduler import Scheduler
from krake.client import Client
from krake.test_utils import server_endpoint

from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_kubernetes_reception(aiohttp_server, config, db, loop):
    # Test that the Reflector present on the Scheduler actually put the
    # right received Applications on the WorkQueue.
    scheduled = ApplicationFactory(status__state=ApplicationState.SCHEDULED)
    updated = ApplicationFactory(status__state=ApplicationState.UPDATED)
    pending = ApplicationFactory(status__state=ApplicationState.PENDING)

    server = await aiohttp_server(create_app(config))

    await db.put(scheduled)
    await db.put(updated)
    await db.put(pending)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        scheduler.client = client
        scheduler.create_background_tasks()  # need to be called explicitly
        await scheduler.reflector.list_resource()

    assert scheduler.queue.size() == 2
    key_1, value_1 = await scheduler.queue.get()
    key_2, value_2 = await scheduler.queue.get()

    assert key_1 in (pending.metadata.uid, updated.metadata.uid)
    assert key_2 in (pending.metadata.uid, updated.metadata.uid)
    assert key_1 != key_2


async def test_kubernetes_scheduling(aiohttp_server, config, db, loop):
    cluster = ClusterFactory()
    app = ApplicationFactory(status__state=ApplicationState.UPDATED)

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        scheduler.client = client
        scheduler.create_background_tasks()
        await scheduler.resource_received(app)

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.cluster == resource_ref(cluster)


async def test_kubernetes_scheduling_error(aiohttp_server, config, db, loop):
    app = ApplicationFactory(status__state=ApplicationState.UPDATED)

    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        scheduler.client = client
        scheduler.create_background_tasks()
        await scheduler.queue.put(app.metadata.uid, app)
        await scheduler.handle_resource(run_once=True)

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.reason.code == ReasonCode.NO_SUITABLE_RESOURCE
