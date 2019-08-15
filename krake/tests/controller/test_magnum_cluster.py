import pytz

from krake.api.app import create_app
from krake.client import Client
from krake.test_utils import server_endpoint
from krake.data.core import resource_ref
from krake.data.openstack import MagnumClusterState
from krake.controller.magnum import MagnumClusterController

from factories.openstack import ProjectFactory, MagnumClusterFactory
from factories import fake


async def test_magnum_cluster_reception(aiohttp_server, config, db, loop):
    # Pending and not scheduled
    pending = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)

    # Pending and scheduled
    scheduled = MagnumClusterFactory(
        status__state=MagnumClusterState.PENDING, status__is_scheduled=True
    )
    # Running
    running = MagnumClusterFactory(status__state=MagnumClusterState.RUNNING)

    # Failed
    failed = MagnumClusterFactory(status__state=MagnumClusterState.FAILED)

    # Running and deleted without finalizers
    deleted = MagnumClusterFactory(
        status__state=MagnumClusterState.RUNNING,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    # Running, not scheduled and deleted with finalizers
    deleted_with_finalizer = MagnumClusterFactory(
        status__state=MagnumClusterState.RUNNING,
        metadata__finalizers=["magnum_cluster_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    # Failed and deleted with finalizers
    deleted_and_failed_with_finalizer = MagnumClusterFactory(
        status__state=MagnumClusterState.FAILED,
        metadata__finalizers=["magnum_cluster_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    assert pending.status.project is None
    assert scheduled.status.project is not None

    await db.put(pending)
    await db.put(scheduled)
    await db.put(running)
    await db.put(failed)
    await db.put(deleted)
    await db.put(deleted_with_finalizer)
    await db.put(deleted_and_failed_with_finalizer)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = MagnumClusterController(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await controller.prepare(client)  # need to be called explicitly
        await controller.reflector.list_resource()

    assert pending.metadata.uid not in controller.queue.dirty
    assert scheduled.metadata.uid in controller.queue.dirty
    assert failed.metadata.uid not in controller.queue.dirty
    assert deleted.metadata.uid not in controller.queue.dirty
    assert deleted_with_finalizer.metadata.uid in controller.queue.dirty
    assert deleted_and_failed_with_finalizer.metadata.uid in controller.queue.dirty


async def test_app_creation(aiohttp_server, config, db, loop):
    # routes = web.RouteTableDef()

    # @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    # async def _(request):
    #     return web.Response(status=404)

    # @routes.post("/apis/apps/v1/namespaces/default/deployments")
    # async def _(request):
    #     return web.Response(status=200)

    # kubernetes_app = web.Application()
    # kubernetes_app.add_routes(routes)

    # kubernetes_server = await aiohttp_server(kubernetes_app)

    project = ProjectFactory()

    cluster = MagnumClusterFactory(
        status__state=MagnumClusterState.PENDING,
        status__project=resource_ref(project),
        spec__master_count=None,
        spec__node_count=None,
    )
    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0
        )
        await controller.prepare(client)
        await controller.resource_received(cluster)

    # stored = await db.get(
    #     Application, namespace=app.metadata.namespace, name=app.metadata.name
    # )
    # assert stored.status.manifest == app.spec.manifest
    # assert stored.status.state == ApplicationState.RUNNING
    # assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"
