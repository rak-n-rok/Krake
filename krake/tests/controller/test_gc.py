import pytest
import pytz
from factory import Factory, SubFactory
from krake.api.app import create_app

from krake.client import Client
from krake.data.core import resource_ref, Metadata
from krake.data.kubernetes import ApplicationState
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

    error_message = "Cannot remove a resource which holds dependents"
    with pytest.raises(ValueError, match=error_message):
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
    with pytest.raises(RuntimeError, match=apps[0].metadata.name):
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

    await gc.queue.done(key_1)
    await gc.queue.done(key_2)


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
        assert gc.queue.size() == 0


async def is_marked_for_deletion(resource, db):
    """Check that a resource present on the database has been marked for deletion.

    Args:
        resource: the resource to check
        db: the database session

    Returns:
        tuple: a tuple (<marked_for_deletion>, <stored_resource>)
            marked_for_deletion: True if the resource given is marked for deletion,
                False otherwise
            stored_resource: the version of the resource present in the database

    """
    cls = resource.__class__
    stored = await db.get(
        cls, namespace=resource.metadata.namespace, name=resource.metadata.name
    )
    marked = (
        "cascade_deletion" in stored.metadata.finalizers
        and stored.metadata.deleted is not None
    )
    return marked, stored


async def is_completely_deleted(resource, db):
    """Check that a resource has been completely removed from the database.

    Args:
        resource: the resource to check
        db: the database session

    Returns:
        bool: True if the resource given has been deleted, False otherwise

    """
    cls = resource.__class__
    stored = await db.get(
        cls, namespace=resource.metadata.namespace, name=resource.metadata.name
    )
    return stored is None


async def test_cascade_deletion(aiohttp_server, config, db, loop):
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
        for _ in range(3)
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
            marked, stored_app = await is_marked_for_deletion(app, db)
            assert marked

            # Mark the application as being "cleaned up"
            stored_app.metadata.finalizers.remove("kubernetes_resources_deletion")
            await db.put(stored_app)
            stored_apps.append(stored_app)

        # Ensure that the Application resources are deleted from database
        for app in stored_apps:
            await gc.resource_received(app)

            assert await is_completely_deleted(app, db)

            await gc.on_received_deleted(app)  # Simulate DELETED event
            await gc.resource_received(cluster)

        # Ensure that the Cluster is deleted from the database
        assert await is_completely_deleted(cluster, db)
        await gc.on_received_deleted(cluster)  # Simulate DELETED event

        assert not gc.graph._resources
        assert not gc.graph._relationships


async def test_several_dependents_one_deleted(db, aiohttp_server, config, loop):
    """Test the deletion of one object that is owned by an upper, which itself owns
    other dependents:

            A
           / \
          B  C
          |  |
          D  E

    If B is deleted, only B and D needs to be deleted
    """
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    cluster_a = ClusterFactory()
    cluster_a_ref = resource_ref(cluster_a)

    cluster_b = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
        metadata__owners=[cluster_a_ref],
    )
    cluster_b_ref = resource_ref(cluster_b)

    cluster_c = ClusterFactory(metadata__owners=[cluster_a_ref])
    cluster_c_ref = resource_ref(cluster_c)

    app_d = ApplicationFactory(
        metadata__finalizers=["kubernetes_resources_deletion"],
        metadata__owners=[cluster_b_ref],
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=cluster_b_ref,
    )

    app_e = ApplicationFactory(
        metadata__finalizers=["kubernetes_resources_deletion"],
        metadata__owners=[cluster_c_ref],
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=cluster_c_ref,
    )

    all_resources = (cluster_a, cluster_b, cluster_c, app_d, app_e)
    for resource in all_resources:
        await db.put(resource)
        gc.graph.add_resource(resource)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        await gc.resource_received(cluster_b)

        # Ensure that "Application D" and "Cluster B" are marked as deleted
        stored_app_d = None
        for resource in all_resources:
            marked, stored = await is_marked_for_deletion(resource, db)
            if stored.metadata.name not in (
                app_d.metadata.name,
                cluster_b.metadata.name,
            ):
                assert not marked
            else:
                assert marked

            if stored.metadata.name == app_d.metadata.name:
                # Mark the "Application D" as being "cleaned up"
                stored.metadata.finalizers.remove("kubernetes_resources_deletion")
                await db.put(stored)
                stored_app_d = stored

        await gc.resource_received(stored_app_d)

        assert await is_completely_deleted(stored_app_d, db)

        # Simulate DELETED event
        await gc.on_received_deleted(stored_app_d)
        assert gc.queue.size() == 1  # Only "Cluster B" should be in the queue

        key, new_cluster_b = await gc.queue.get()
        await gc.resource_received(new_cluster_b)
        await gc.queue.done(key)

        # Ensure that the Cluster is deleted from the database
        assert await is_completely_deleted(new_cluster_b, db)

        # Simulate DELETED event
        await gc.on_received_deleted(new_cluster_b)
        assert gc.queue.size() == 0  # No other resources should be put in the queue

        assert len(gc.graph._resources) == 3
        assert len(gc.graph._relationships) == 3
        assert len(gc.graph._relationships[resource_ref(app_e)]) == 0


async def ensure_dependency_to_delete(gc, to_be_deleted, dependency_number):
    """Handle one resource from queue that needs to be deleted, and check if its
    dependency is put in queue afterwards.

    Args:
        gc (GarbageCollector): the garbage collector that handles the resource
        to_be_deleted: the resource to handle, that is supposed to be in the queue
            before using this function
        dependency_number (int): the number of dependencies of the resource that are
            supposed to be put into the queue when the resource is deleted

    """
    key, from_queue = await gc.queue.get()
    assert from_queue.metadata.deleted is not None

    await gc.resource_received(from_queue)
    await gc.queue.done(key)

    await gc.on_received_deleted(from_queue)

    assert (
        gc.queue.size() == dependency_number
    ), f"{resource_ref(to_be_deleted)} has not been deleted"


async def test_three_layers_deletion(aiohttp_server, config, db, loop):
    """Test the deletion of a resource, whose dependent holds a dependent. All direct
    and indirect dependents should be deleted.

    The dependency relations is: upper <-- middle <-- lower (where A <- B signifies that
    B depends on A, that A is in the owners list of B).

    ``upper`` is marked for deletion, so the gc recursively marks ``middle`` and
    ``lower`` as deleted.

    Then, ``lower`` is deleted, then ``middle``, then ``upper``
    """

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

        ##
        # First step: Update direct dependents of upper

        await gc.resource_received(upper)

        # Get the versions of the resources updated by the API:
        # middle, as direct dependent, is marked as deleted, while lower is not.
        marked, stored_middle = await is_marked_for_deletion(middle, db)
        assert marked

        marked, stored_lower = await is_marked_for_deletion(lower, db)
        assert not marked

        # lower and middle have been updated, and need to be handled by the gc
        await gc.on_received_update(stored_middle)
        await gc.on_received_update(stored_lower)

        assert gc.queue.size() == 1  # Only middle in queue, as lower is not marked

        ##
        # Second step: Update direct dependents of middle

        key, stored_middle = await gc.queue.get()
        await gc.resource_received(stored_middle)
        await gc.queue.done(key)

        # lower, as direct dependent of middle, is marked as deletion also.
        marked, stored_lower = await is_marked_for_deletion(lower, db)
        assert marked

        await gc.on_received_update(stored_lower)
        assert gc.queue.size() == 1  # Only lower in queue

        ##
        # Third step: lower has been put just before into the queue,
        # as direct dependency. It will be finally deleted

        await ensure_dependency_to_delete(gc, to_be_deleted=lower, dependency_number=1)

        ##
        # Fourth step: middle has been put just before into the queue,
        # as direct dependency. It will be finally deleted

        await ensure_dependency_to_delete(gc, to_be_deleted=middle, dependency_number=1)

        #
        # Fifth step: upper has been put just before into the queue,
        # as direct dependency. It will be finally deleted

        await ensure_dependency_to_delete(gc, to_be_deleted=upper, dependency_number=0)

        ##
        # Last checks: all resources are deleted

        assert await is_completely_deleted(lower, db)
        assert await is_completely_deleted(middle, db)
        assert await is_completely_deleted(upper, db)

        assert not gc.graph._resources
