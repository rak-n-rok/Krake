import pytz

from krake.api.database import Session
from krake.client import Client
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState, Cluster
from krake.controller.garbage_collector import GarbageCollector

from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_resources_reception(config, db, loop):
    app_updated = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__is_scheduled=False
    )
    app_deleting = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    cluster_running = ClusterFactory()
    cluster_deleted = ClusterFactory(metadata__deleted=fake.date_time(tzinfo=pytz.utc))

    await db.put(app_updated)
    await db.put(app_deleting)

    await db.put(cluster_running)
    await db.put(cluster_deleted)

    gc = GarbageCollector(worker_count=0, db_host=db.host, db_port=db.port)

    async with Client(url="http://localhost:8080", loop=loop) as client:
        await gc.prepare(client)  # need to be called explicitly

    async with Session(host=gc.db_host, port=gc.db_port) as session:
        for reflector in gc.reflectors:
            await reflector.list_resource(session)

    assert gc.queue.size() == 2
    key_1, value_1 = await gc.queue.get()
    key_2, value_2 = await gc.queue.get()

    assert key_1 in (app_deleting.metadata.uid, cluster_deleted.metadata.uid)
    assert key_2 in (app_deleting.metadata.uid, cluster_deleted.metadata.uid)
    assert key_1 != key_2


async def test_cluster_deletion(config, db, loop):
    cluster = ClusterFactory(metadata__deleted=fake.date_time(tzinfo=pytz.utc))

    await db.put(cluster)

    apps = [
        ApplicationFactory(
            metadata__finalizers=["kubernetes_resources_deletion"],
            metadata__owners=[resource_ref(cluster)],
            status__state=ApplicationState.RUNNING,
            status__scheduled_to=resource_ref(cluster),
        )
        for _ in range(0, 3)
    ]
    for app in apps:
        await db.put(app)

    # Ensure that the Applications are marked as deleted
    stored_apps = []
    for app in apps:
        gc = GarbageCollector(db_host=db.host, db_port=db.port)
        await gc.resource_received(cluster)

        stored_app = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored_app.metadata.deleted is not None

        # Mark the application as being "cleaned up"
        removed_finalizer = stored_app.metadata.finalizers.pop(-1)
        assert removed_finalizer == "kubernetes_resources_deletion"
        await db.put(stored_app)
        stored_apps.append(stored_app)

    # Ensure that the Application resources are deleted from database
    for app in stored_apps:
        gc = GarbageCollector(db_host=db.host, db_port=db.port)
        await gc.resource_received(app)

        stored_app = await db.get(
            Application,
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
        )
        assert stored_app is None

    stored_cluster = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored_cluster is None
