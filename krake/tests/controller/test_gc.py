import pytest
import pytz
from factory import Factory, SubFactory

from krake.api.database import Session
from krake.client import Client
from krake.data.core import resource_ref, Metadata
from krake.data.kubernetes import Application, ApplicationState, Cluster
from krake.controller.gc import DependencyGraph, GarbageCollector

from factories.core import MetadataFactory
from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory
from krake.data.serializable import Serializable


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


class UpperResource(Serializable):
    api: str = "upper_api"
    kind: str = "Upper"
    metadata: Metadata


class UpperResourceFactory(Factory):
    class Meta:
        model = UpperResource

    metadata = SubFactory(MetadataFactory)


def test_dependency_graph():
    graph = DependencyGraph()

    up = UpperResourceFactory()
    graph.add_resource(up)

    cluster = ClusterFactory(metadata__owners=[resource_ref(up)])
    graph.add_resource(cluster)

    cluster_ref = resource_ref(cluster)

    apps = [
        ApplicationFactory(
            metadata__owners=[cluster_ref], status__scheduled_to=cluster_ref
    )
        for _ in range(0, 3)
    ]

    for app in apps:
        graph.add_resource(app)

    assert len(graph._relationships) == 5
    assert graph.get_direct_dependents(up) == [cluster]
    assert graph.get_direct_dependents(cluster) == apps

    for app in apps:
        assert len(graph.get_direct_dependents(app)) == 0

    graph.remove_resource(apps[0])
    assert len(graph._relationships) == 4
    assert graph.get_direct_dependents(up) == [cluster]
    assert graph.get_direct_dependents(cluster) == apps[1:]

    for app in apps:
        assert len(graph.get_direct_dependents(app)) == 0

    with pytest.raises(ValueError):
        graph.remove_resource(up)


def test_dependency_graph_wrong_order():
    up = UpperResourceFactory()
    cluster = ClusterFactory(metadata__owners=[resource_ref(up)])

    cluster_ref = resource_ref(cluster)

    app = ApplicationFactory(
        metadata__owners=[cluster_ref], status__scheduled_to=cluster_ref
    )

    graph = DependencyGraph()
    graph.add_resource(app)
    graph.add_resource(cluster)
    graph.add_resource(up)

    assert len(graph._relationships) == 3
    assert graph.get_direct_dependents(up) == [cluster]
    assert graph.get_direct_dependents(cluster) == [app]
    assert graph.get_direct_dependents(app) == []

    # Verify that adding objects in any order does not change the result.
    right_order_graph = DependencyGraph()
    right_order_graph.add_resource(up)
    right_order_graph.add_resource(cluster)
    right_order_graph.add_resource(app)

    assert right_order_graph._resources == graph._resources
    assert right_order_graph._relationships == graph._relationships

    # check that the graph only copied the resources
    for key in right_order_graph._resources:
        assert right_order_graph._resources[key] is not graph._resources[key]


def test_error_on_cycle_in_dependency_graph():
    # Create a cycle in dependency
    up = UpperResourceFactory()
    cluster = ClusterFactory(metadata__owners=[resource_ref(up)])
    apps = [
        ApplicationFactory(metadata__owners=[resource_ref(cluster)])
        for _ in range(0, 3)
    ]
    up.metadata.owners.append(resource_ref(apps[0]))

    graph = DependencyGraph()
    graph.add_resource(up)
    graph.add_resource(cluster)

    # Add resources without cycle
    for app in apps[1:]:
        graph.add_resource(app)

    # Add resource with cycle
    with pytest.raises(RuntimeError):
        graph.add_resource(apps[0])


def test_update_resource_dependency_graph():
    up_1 = UpperResourceFactory()
    cluster_1 = ClusterFactory(metadata__owners=[resource_ref(up_1)])
    cluster_2 = ClusterFactory(metadata__owners=[resource_ref(up_1)])
    app_1 = ApplicationFactory(metadata__owners=[resource_ref(cluster_1)])

    graph = DependencyGraph()
    graph.add_resource(up_1)
    graph.add_resource(cluster_1)
    graph.add_resource(cluster_2)
    graph.add_resource(app_1)

    # Replace ownership
    app_1.metadata.owners = [resource_ref(cluster_2)]
    graph.update_resource(app_1)

    assert graph.get_direct_dependents(cluster_2) == [app_1]
    assert graph.get_direct_dependents(cluster_1) == []

    # Remove ownership
    cluster_2.metadata.owners = []
    graph.update_resource(cluster_2)

    assert graph.get_direct_dependents(cluster_2) == [app_1]
    assert graph.get_direct_dependents(up_1) == [cluster_1]

    # Add new ownership
    up_2 = UpperResourceFactory()
    graph.add_resource(up_2)

    cluster_2.metadata.owners = [resource_ref(up_2)]
    graph.update_resource(cluster_2)

    assert graph.get_direct_dependents(cluster_2) == [app_1]
    assert graph.get_direct_dependents(up_2) == [cluster_2]


def test_dependency_owners():
    ups = [UpperResourceFactory() for _ in range(2)]
    cluster = ClusterFactory(metadata__owners=[resource_ref(up) for up in ups])

    graph = DependencyGraph()
    for up in ups:
        graph.add_resource(up)
    graph.add_resource(cluster)

    owners = graph.get_owners(cluster)

    assert owners == ups


