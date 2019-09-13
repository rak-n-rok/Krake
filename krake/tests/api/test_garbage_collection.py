import asyncio
import pytz

from krake.api.app import create_app
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState, ClusterState, Cluster
from krake.controller import Worker
from krake.api.garbage_collection import GarbageCollector, GarbageWorker
from krake.client import Client
from krake.test_utils import server_endpoint

from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_resources_reception(aiohttp_server, config, db, loop):
    app_updated = ApplicationFactory(status__state=ApplicationState.UPDATED)
    app_deleting = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    cluster_updated = ClusterFactory(status__state=ClusterState.UPDATED)
    cluster_deleting = ClusterFactory(
        status__state=ClusterState.RUNNING,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    server = await aiohttp_server(create_app(config))

    class SimpleWorker(Worker):
        def __init__(self):
            self.done = loop.create_future()

        async def resource_received(self, resource):
            assert resource in [app_deleting, cluster_deleting]

            if not self.done.done():
                self.done.set_result(None)

    worker = SimpleWorker()

    async with GarbageCollector(
        api_endpoint=server_endpoint(server),
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
        db_host=db.host,
        db_port=db.port,
    ) as controller:

        await db.put(app_updated)
        await db.put(app_deleting)

        await db.put(cluster_updated)
        await db.put(cluster_deleting)

        await asyncio.wait(
            [controller, worker.done], timeout=1, return_when=asyncio.FIRST_COMPLETED
        )
    assert worker.done.done()


async def test_cluster_deletion(aiohttp_server, config, db, loop):
    cluster = ClusterFactory(metadata__deleted=fake.date_time(tzinfo=pytz.utc))

    await db.put(cluster)

    apps = [
        ApplicationFactory(
            metadata__finalizers=["cleanup"],
            status__state=ApplicationState.RUNNING,
            status__cluster=resource_ref(cluster),
            status__depends=[resource_ref(cluster)],
        )
        for _ in range(0, 3)
    ]
    for app in apps:
        await db.put(app)

    server = await aiohttp_server(create_app(config))

    for app in apps:
        # Ensure that the Applications are marked as deleted
        async with Client(url=server_endpoint(server), loop=loop) as client:
            worker = GarbageWorker(client=client, db_host=db.host, db_port=db.port)
            await worker.resource_received(cluster)

        stored_app, _ = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored_app.metadata.deleted is not None

        # Mark the application as being "cleaned up"
        removed_finalizer = stored_app.metadata.finalizers.pop(-1)
        assert removed_finalizer == "cleanup"
        await db.put(stored_app)

        # Ensure that the Application resources are deleted from database
        async with Client(url=server_endpoint(server), loop=loop) as client:
            worker = GarbageWorker(client=client, db_host=db.host, db_port=db.port)
            await worker.resource_received(stored_app)

        stored_app, _ = await db.get(
            Application,
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
        )
        assert stored_app is None

    # Ensure that the cluster resource is deleted from database
    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = GarbageWorker(client=client, db_host=db.host, db_port=db.port)
        await worker.resource_received(cluster)

    stored_cluster, _ = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored_cluster is None
