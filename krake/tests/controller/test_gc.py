import pytest
import pytz
from factory import Factory, SubFactory
from krake.api.app import create_app

from krake.client import Client
from krake.data.core import resource_ref, Metadata
from krake.data.kubernetes import Application, ApplicationState, Cluster
from krake.controller.gc import DependencyGraph, GarbageCollector

from factories.core import MetadataFactory
from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory
from krake.data.serializable import Serializable
from krake.test_utils import server_endpoint


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
            metadata__owners=[cluster_ref],
            status__scheduled_to=cluster_ref,
            status__state=ApplicationState.RUNNING,
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
        metadata__owners=[cluster_ref],
        status__scheduled_to=cluster_ref,
        status__state=ApplicationState.RUNNING,
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
    cluster_ref = resource_ref(cluster)

    apps = [
        ApplicationFactory(
            metadata__owners=[cluster_ref],
            status__scheduled_to=cluster_ref,
            status__state=ApplicationState.RUNNING,
        )
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
    cluster_1_ref = resource_ref(cluster_1)

    app_1 = ApplicationFactory(
        metadata__owners=[cluster_1_ref],
        status__scheduled_to=cluster_1_ref,
        status__state=ApplicationState.RUNNING,
    )

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


async def test_resources_reception(aiohttp_server, config, db, loop):
    app_migrating = ApplicationFactory(status__state=ApplicationState.MIGRATING)
    app_deleting = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cleanup", "cascade_deletion"],
    )

    cluster_alive = ClusterFactory()
    cluster_deleting = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )

    await db.put(app_migrating)
    await db.put(app_deleting)

    await db.put(cluster_alive)
    await db.put(cluster_deleting)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        gc = GarbageCollector(server_endpoint(server), worker_count=0)
        await gc.prepare(client)  # need to be called explicitly
        for reflector in gc.reflectors:
            await reflector.list_resource()

    assert gc.queue.size() == 2
    key_1, value_1 = await gc.queue.get()
    key_2, value_2 = await gc.queue.get()

    assert key_1 in (app_deleting.metadata.uid, cluster_deleting.metadata.uid)
    assert key_2 in (app_deleting.metadata.uid, cluster_deleting.metadata.uid)
    assert key_1 != key_2


async def test_new_event_reception(aiohttp_server, config, db, loop):
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    cluster_added = ClusterFactory()
    cluster_deleting = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        await gc.on_received_new(cluster_added)
        assert resource_ref(cluster_added) in gc.graph._resources
        assert gc.queue.size() == 0

        await gc.on_received_new(cluster_deleting)
        assert resource_ref(cluster_deleting) in gc.graph._resources
        assert gc.queue.size() == 1


async def test_update_event_reception(aiohttp_server, config, db, loop):
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    cluster = ClusterFactory()

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        await gc.on_received_new(cluster)
        assert resource_ref(cluster) in gc.graph._resources
        assert gc.queue.size() == 0

        cluster.metadata.deleted = fake.date_time(tzinfo=pytz.utc)
        cluster.metadata.finalizers.append("cascade_deletion")

        await gc.on_received_update(cluster)
        assert resource_ref(cluster) in gc.graph._resources
        assert gc.queue.size() == 1


async def test_delete_event_reception(aiohttp_server, config, db, loop):
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    ups = [UpperResourceFactory() for _ in range(2)]

    cluster = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__owners=[resource_ref(up) for up in ups],
    )

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        # Add resources to the dependency graph
        for up in ups:
            await gc.on_received_new(up)
        await gc.on_received_new(cluster)

        await gc.on_received_deleted(cluster)
        assert resource_ref(cluster) not in gc.graph._resources
        assert gc.queue.size() == 2


async def test_several_dependents_deletion(aiohttp_server, config, db, loop):
    # Test the deletion of a resource that holds several dependents. The resource and
    # all its dependents should be deleted.
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    cluster = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    gc.graph.add_resource(cluster)

    cluster_ref = resource_ref(cluster)
    apps = [
        ApplicationFactory(
            metadata__finalizers=["kubernetes_resources_deletion"],
            metadata__owners=[cluster_ref],
            status__state=ApplicationState.RUNNING,
            status__scheduled_to=cluster_ref,
        )
        for _ in range(0, 3)
    ]

    await db.put(cluster)
    for app in apps:
        gc.graph.add_resource(app)
        await db.put(app)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        await gc.resource_received(cluster)

        # Ensure that the Applications are marked as deleted
        stored_apps = []
        for app in apps:
            stored_app = await db.get(
                Application, namespace=app.metadata.namespace, name=app.metadata.name
            )
            assert stored_app.metadata.deleted is not None
            assert "cascade_deletion" in stored_app.metadata.finalizers

            # Mark the application as being "cleaned up"
            stored_app.metadata.finalizers.remove("kubernetes_resources_deletion")
            await db.put(stored_app)
            stored_apps.append(stored_app)

        # Ensure that the Application resources are deleted from database
        for app in stored_apps:
            await gc.resource_received(app)

            stored_app = await db.get(
                Application,
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
            )
            assert stored_app is None
            await gc.on_received_deleted(app)  # Simulate DELETED event
            await gc.resource_received(cluster)

        # Ensure that the Cluster is deleted from the database
        stored_cluster = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        assert stored_cluster is None
        await gc.on_received_deleted(cluster)  # Simulate DELETED event

        assert not gc.graph._resources
        assert not gc.graph._relationships


async def test_three_layers_deletion(aiohttp_server, config, db, loop):
    # Test the deletion of a resource, whose dependent holds a dependent.
    # All direct and indirect dependents should be deleted.

    upper = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    middle = ClusterFactory(metadata__owners=[resource_ref(upper)])
    lower = ClusterFactory(metadata__owners=[resource_ref(middle)])

    await db.put(upper)
    await db.put(middle)
    await db.put(lower)

    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    gc.graph.add_resource(upper)
    gc.graph.add_resource(middle)
    gc.graph.add_resource(lower)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        # First step: Update direct dependents of upper

        await gc.resource_received(upper)

        # Get the versions of the resources updated by the API
        stored_middle = await db.get(
            Cluster, namespace=middle.metadata.namespace, name=middle.metadata.name
        )
        assert stored_middle.metadata.deleted is not None

        stored_lower = await db.get(
            Cluster, namespace=lower.metadata.namespace, name=lower.metadata.name
        )
        assert stored_lower.metadata.deleted is None

        await gc.on_received_update(stored_middle)
        await gc.on_received_update(stored_lower)

        assert gc.queue.size() == 1  # Only middle in queue

        # Second step: Update direct dependents of middle

        key, stored_middle = await gc.queue.get()
        await gc.resource_received(stored_middle)
        await gc.queue.done(key)

        stored_lower = await db.get(
            Cluster, namespace=lower.metadata.namespace, name=lower.metadata.name
        )
        assert stored_lower.metadata.deleted is not None

        await gc.on_received_update(stored_lower)

        assert gc.queue.size() == 1  # Only lower in queue

        # Third step: lower is to be deleted

        key, stored_lower = await gc.queue.get()
        await gc.resource_received(stored_lower)
        await gc.queue.done(key)

        await gc.on_received_deleted(stored_lower)

        assert gc.queue.size() == 1  # middle should be in queue

        # Fourth step: middle is to be deleted

        key, stored_middle = await gc.queue.get()
        await gc.resource_received(stored_middle)
        await gc.queue.done(key)

        await gc.on_received_deleted(stored_middle)

        assert gc.queue.size() == 1  # upper should be in queue

        # Fifth step: upper is to be deleted

        key, stored_upper = await gc.queue.get()
        await gc.resource_received(stored_upper)
        await gc.queue.done(key)

        await gc.on_received_deleted(stored_upper)

        assert gc.queue.size() == 0

        # Last checks: all resources are deleted

        stored_lower = await db.get(
            Cluster, namespace=lower.metadata.namespace, name=lower.metadata.name
        )
        assert stored_lower is None

        stored_middle = await db.get(
            Cluster, namespace=middle.metadata.namespace, name=middle.metadata.name
        )
        assert stored_middle is None

        stored_upper = await db.get(
            Cluster, namespace=upper.metadata.namespace, name=upper.metadata.name
        )
        assert stored_upper is None

        assert not gc.graph._resources
