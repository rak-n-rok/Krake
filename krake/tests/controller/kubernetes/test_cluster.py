import asyncio
import pytz

from krake.api.app import create_app
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ClusterState, ApplicationState
from krake.controller import Worker
from krake.controller.kubernetes.cluster import ClusterController, ClusterWorker
from krake.client import Client
from krake.test_utils import server_endpoint

from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_cluster_reception(aiohttp_server, config, db, loop):
    """
    Verify that the ClusterController hands over the Cluster being deleted to the
    Workers.
    """
    creating = ClusterFactory(status__state=ClusterState.PENDING)
    running = ClusterFactory(status__state=ClusterState.RUNNING)
    deleting = ClusterFactory(metadata__deleted=fake.date_time(tzinfo=pytz.utc))

    server = await aiohttp_server(create_app(config))

    class SimpleWorker(Worker):
        def __init__(self):
            self.done = loop.create_future()

        async def resource_received(self, cluster):
            assert cluster == deleting

            if not self.done.done():
                self.done.set_result(None)

    worker = SimpleWorker()

    async with ClusterController(
        api_endpoint=server_endpoint(server),
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
    ) as controller:

        await db.put(creating)
        await db.put(running)
        await db.put(deleting)

        await asyncio.wait(
            [controller, worker.done], timeout=0.5, return_when=asyncio.FIRST_COMPLETED
        )
    assert worker.done.done()


async def test_cluster_deletion(aiohttp_server, config, db, loop):
    cluster = ClusterFactory(
        metadata__finalizers=["cleanup.clusters.kubernetes"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__cluster=resource_ref(cluster)
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = ClusterWorker(client=client)
        await worker.resource_received(cluster)

    # Ensure that the application resource is deleted from database
    stored_app, _ = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored_app is None

    # Ensure that the cluster resource is deleted from database
    stored_cluster, _ = await db.get(
        Application, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored_cluster is None
