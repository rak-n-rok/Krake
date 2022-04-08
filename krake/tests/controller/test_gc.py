import asyncio
from asyncio.subprocess import PIPE, STDOUT
import multiprocessing
import time
from contextlib import suppress
from itertools import count

import sys
import pytest
import pytz
from factory import Factory, SubFactory
from krake.api.app import create_app

from krake.client import Client
from krake.data.core import resource_ref, Metadata
from krake.data.kubernetes import ApplicationState, Cluster
from krake.controller.gc import (
    DependencyGraph,
    GarbageCollector,
    ResourceWithDependentsException,
    DependencyCycleException,
    main,
)
from krake.utils import get_namespace_as_kwargs

from tests.factories.core import MetadataFactory, RoleBindingFactory, RoleFactory
from tests.factories.fake import fake
from tests.factories.kubernetes import ApplicationFactory, ClusterFactory
from tests.factories.openstack import ProjectFactory
from krake.data.serializable import Serializable
from krake.test_utils import server_endpoint, with_timeout
from tests.factories.openstack import MagnumClusterFactory


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
    up_ref = resource_ref(up)
    graph.add_resource(up_ref, up.metadata.owners)

    cluster = ClusterFactory(metadata__owners=[resource_ref(up)])
    cluster_ref = resource_ref(cluster)
    graph.add_resource(cluster_ref, cluster.metadata.owners)

    apps = [
        ApplicationFactory(
            metadata__owners=[cluster_ref],
            status__scheduled_to=cluster_ref,
            status__state=ApplicationState.RUNNING,
        )
        for _ in range(0, 3)
    ]

    for app in apps:
        graph.add_resource(resource_ref(app), app.metadata.owners)

    assert len(graph._relationships) == 5
    assert graph.get_direct_dependents(up_ref) == [cluster_ref]
    assert graph.get_direct_dependents(cluster_ref) == [
        resource_ref(app) for app in apps
    ]

    for app in apps:
        assert len(graph.get_direct_dependents(resource_ref(app))) == 0

    graph.remove_resource(resource_ref(apps[0]))
    assert len(graph._relationships) == 4
    assert graph.get_direct_dependents(up_ref) == [cluster_ref]
    assert graph.get_direct_dependents(cluster_ref) == [
        resource_ref(app) for app in apps[1:]
    ]

    for app in apps:
        assert len(graph.get_direct_dependents(resource_ref(app))) == 0

    with pytest.raises(ResourceWithDependentsException):
        graph.remove_resource(up_ref)


def test_dependency_graph_wrong_order():
    up = UpperResourceFactory()
    up_ref = resource_ref(up)

    cluster = ClusterFactory(metadata__owners=[resource_ref(up)])
    cluster_ref = resource_ref(cluster)

    app = ApplicationFactory(
        metadata__owners=[cluster_ref],
        status__scheduled_to=cluster_ref,
        status__state=ApplicationState.RUNNING,
    )

    app_ref = resource_ref(app)

    graph = DependencyGraph()
    graph.add_resource(app_ref, app.metadata.owners)
    graph.add_resource(cluster_ref, cluster.metadata.owners)
    graph.add_resource(up_ref, up.metadata.owners)

    assert len(graph._relationships) == 3
    assert graph.get_direct_dependents(up_ref) == [cluster_ref]
    assert graph.get_direct_dependents(cluster_ref) == [app_ref]
    assert graph.get_direct_dependents(app_ref) == []

    # Verify that adding objects in any order does not change the result.
    right_order_graph = DependencyGraph()
    right_order_graph.add_resource(up_ref, up.metadata.owners)
    right_order_graph.add_resource(cluster_ref, cluster.metadata.owners)
    right_order_graph.add_resource(app_ref, app.metadata.owners)

    assert right_order_graph._relationships == graph._relationships

    # check that the graph only copied the resources
    for key in right_order_graph._relationships:
        assert right_order_graph._relationships[key] is not graph._relationships[key]


def test_error_on_cycle_in_dependency_graph():
    # Create a cycle in dependency
    up = UpperResourceFactory()
    up_ref = resource_ref(up)

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
    graph.add_resource(up_ref, up.metadata.owners)
    graph.add_resource(cluster_ref, cluster.metadata.owners)

    # Add resources without cycle
    for app in apps[1:]:
        graph.add_resource(resource_ref(app), app.metadata.owners)

    # Add resource with cycle
    with pytest.raises(DependencyCycleException):
        graph.add_resource(resource_ref(apps[0]), apps[0].metadata.owners)


def test_update_resource_dependency_graph():
    up_1 = UpperResourceFactory()
    up_1_ref = resource_ref(up_1)

    cluster_1 = ClusterFactory(metadata__owners=[resource_ref(up_1)])
    cluster_2 = ClusterFactory(metadata__owners=[resource_ref(up_1)])
    cluster_1_ref = resource_ref(cluster_1)
    cluster_2_ref = resource_ref(cluster_2)

    app_1 = ApplicationFactory(
        metadata__owners=[cluster_1_ref],
        status__scheduled_to=cluster_1_ref,
        status__state=ApplicationState.RUNNING,
    )
    app_1_ref = resource_ref(app_1)

    """     cluster_1 -- app_1
          /
    up_1 <
          \
            cluster_2
    """
    graph = DependencyGraph()
    graph.add_resource(up_1_ref, up_1.metadata.owners)
    graph.add_resource(cluster_1_ref, cluster_1.metadata.owners)
    graph.add_resource(cluster_2_ref, cluster_2.metadata.owners)
    graph.add_resource(app_1_ref, app_1.metadata.owners)

    # Replace ownership
    """     cluster_1
          /
    up_1 <
          \
            cluster_2 -- app_1
    """
    app_1.metadata.owners = [cluster_2_ref]
    graph.update_resource(app_1_ref, app_1.metadata.owners)

    assert graph.get_direct_dependents(cluster_2_ref) == [app_1_ref]
    assert graph.get_direct_dependents(cluster_1_ref) == []

    # Remove ownership
    """
    up_1 -- cluster_1
    ---------------------
    cluster_2 -- app_1
    """
    cluster_2.metadata.owners = []
    graph.update_resource(cluster_2_ref, cluster_2.metadata.owners)

    assert graph.get_direct_dependents(cluster_2_ref) == [app_1_ref]
    assert graph.get_direct_dependents(up_1_ref) == [cluster_1_ref]

    # Add new ownership
    """
    up_1 -- cluster_1
    ---------------------------
    up_2 -- cluster_2 -- app_1
    """
    up_2 = UpperResourceFactory()
    up_2_ref = resource_ref(up_2)
    graph.add_resource(up_2_ref, up_2.metadata.owners)

    cluster_2.metadata.owners = [up_2_ref]
    graph.update_resource(cluster_2_ref, cluster_2.metadata.owners)

    assert graph.get_direct_dependents(cluster_2_ref) == [app_1_ref]
    assert graph.get_direct_dependents(up_2_ref) == [cluster_2_ref]


@with_timeout(3)
async def test_main_help(loop):
    """Verify that the help for the Garbage Collector is displayed, and contains the
    elements added by the argparse formatters (default value and expected types of the
    parameters).
    """
    command = "python -m krake.controller.gc -h"
    # The loop parameter is mandatory otherwise the test fails if started with others.
    process = await asyncio.create_subprocess_exec(
        *command.split(" "), stdout=PIPE, stderr=STDOUT
    )
    stdout, _ = await process.communicate()
    output = stdout.decode()

    to_check = [
        "Garbage Collector for Krake",
        "usage:",
        "default:",  # Present if the default value of the arguments are displayed
        "str",  # Present if the type of the arguments are displayed
        "int",
    ]
    # Because python3.10 argparse version changed 'optional arguments:' to 'options:'
    if sys.version_info < (3, 10):
        to_check.append("optional arguments:")
    else:
        to_check.append("options:")

    for expression in to_check:
        assert expression in output


@pytest.mark.slow
def test_main(gc_config, log_to_file_config):
    """Test the main function of the Garbage Collector, and verify that it starts,
    display the right output and stops without issue.
    """
    log_config, file_path = log_to_file_config()

    gc_config.api_endpoint = "http://my-krake-api:1234"
    gc_config.log = log_config

    def wrapper(configuration):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        main(configuration)

    # Start the process and let it time to initialize
    process = multiprocessing.Process(target=wrapper, args=(gc_config,))
    process.start()
    time.sleep(2)

    # Stop and wait for the process to finish
    process.terminate()
    process.join()

    assert not process.is_alive()
    assert process.exitcode == 0

    # Verify the output of the process
    with open(file_path, "r") as f:
        output = f.read()

    assert "Controller started" in output
    assert "Received signal, exiting..." in output
    assert "Controller stopped" in output

    # Verify that all "ERROR" lines in the output are only errors that logs the lack of
    # connectivity to the API.
    attempted_connectivity = False
    for line in output.split("\n"):
        if "ERROR" in output:
            message = (
                f"In line {line!r}, an error occurred which was different from the"
                f" error from connecting to the API."
            )
            assert "Cannot connect to host my-krake-api:1234" in output, message
            attempted_connectivity = True

    assert attempted_connectivity


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

    project_alive = ProjectFactory()
    project_deleting = ProjectFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )

    await db.put(app_migrating)
    await db.put(app_deleting)

    await db.put(cluster_alive)
    await db.put(cluster_deleting)

    await db.put(project_alive)
    await db.put(project_deleting)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        gc = GarbageCollector(server_endpoint(server), worker_count=0)
        await gc.prepare(client)  # need to be called explicitly
        for reflector in gc.reflectors:
            await reflector.list_resource()

    assert gc.queue.size() == 3
    key_1, value_1 = await gc.queue.get()
    key_2, value_2 = await gc.queue.get()
    key_3, value_3 = await gc.queue.get()

    deleting_resources = {
        res.metadata.uid for res in (app_deleting, cluster_deleting, project_deleting)
    }
    # Assert that all resources to delete are in the queue,
    # and that the keys are all different.
    assert key_1 in deleting_resources
    assert key_2 in deleting_resources
    assert key_3 in deleting_resources
    assert len(deleting_resources) == len({key_1, key_2, key_3})

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
        assert resource_ref(cluster_added) in gc.graph._relationships
        assert gc.queue.size() == 0

        await gc.on_received_new(cluster_deleting)
        assert resource_ref(cluster_deleting) in gc.graph._relationships
        assert gc.queue.size() == 1


async def test_update_event_reception(aiohttp_server, config, db, loop):
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    cluster = ClusterFactory()

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        await gc.on_received_new(cluster)
        assert resource_ref(cluster) in gc.graph._relationships
        assert gc.queue.size() == 0

        cluster.metadata.deleted = fake.date_time(tzinfo=pytz.utc)
        cluster.metadata.finalizers.append("cascade_deletion")

        await gc.on_received_update(cluster)
        assert resource_ref(cluster) in gc.graph._relationships
        assert gc.queue.size() == 1


async def test_delete_event_reception(aiohttp_server, config, db, loop):
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    ups = [MagnumClusterFactory() for _ in range(2)]

    cluster = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__owners=[resource_ref(up) for up in ups],
    )

    for up in ups:
        await db.put(up)
    await db.put(cluster)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        # Add resources to the dependency graph
        for up in ups:
            await gc.on_received_new(up)
        await gc.on_received_new(cluster)

        await gc.on_received_deleted(cluster)
        assert resource_ref(cluster) not in gc.graph._relationships
        assert gc.queue.size() == 0


async def test_handle_resource(aiohttp_server, config, db, loop):
    """Verify that the handle_resource method handles the resources the right way."""
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server), worker_count=0, loop=loop)

    cluster = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
        metadata__owners=[],
    )

    await db.put(cluster)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        # Get the reflectors that was created for the Cluster resources.
        cluster_reflector = next(
            filter(lambda r: r.resource_plural == "Clusters", gc.reflectors), None
        )
        reflector_task = loop.create_task(cluster_reflector())

        await gc.handle_resource(run_once=True)

        reflector_task.cancel()
        with suppress(asyncio.CancelledError):
            await reflector_task

    # The resource was deleted on the API as no finalizer is left on the resource
    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored is None
    assert gc.queue.empty()


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
    kwargs = get_namespace_as_kwargs(resource.metadata.namespace)
    stored = await db.get(cls, name=resource.metadata.name, **kwargs)
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
    kwargs = get_namespace_as_kwargs(resource.metadata.namespace)
    stored = await db.get(cls, name=resource.metadata.name, **kwargs)
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
    cluster_ref = resource_ref(cluster)
    gc.graph.add_resource(cluster_ref, cluster.metadata.owners)

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
        gc.graph.add_resource(resource_ref(app), app.metadata.owners)
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

        assert not gc.graph._relationships


async def test_cascade_deletion_non_namespaced(aiohttp_server, config, db, loop):
    """Verify that resources without namespace are still handled by the Garbage
    Collector.
    """
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server))

    role = RoleFactory(
        metadata__namespace=None,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    role_ref = resource_ref(role)
    gc.graph.add_resource(role_ref, role.metadata.owners)
    await db.put(role)

    role_binding = RoleBindingFactory(
        metadata__namespace=None,
        metadata__owners=[role_ref],  # The role is normally not added as owner
        metadata__finalizers=["cascade_deletion"],
    )
    gc.graph.add_resource(resource_ref(role_binding), role_binding.metadata.owners)
    await db.put(role_binding)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await gc.prepare(client)

        await gc.resource_received(role)

        # Ensure that the RoleBinding is marked as deleted
        marked, stored_role_binding = await is_marked_for_deletion(role_binding, db)
        assert marked

        # Ensure that the RoleBinding is deleted from database
        await gc.resource_received(role_binding)

        assert await is_completely_deleted(role_binding, db)

        await gc.on_received_deleted(role_binding)  # Simulate DELETED event
        await gc.resource_received(role)

        # Ensure that the Role is deleted from the database
        assert await is_completely_deleted(role, db)
        await gc.on_received_deleted(role)  # Simulate DELETED event

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
        gc.graph.add_resource(resource_ref(resource), resource.metadata.owners)

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

    gc.graph.add_resource(resource_ref(upper), upper.metadata.owners)
    gc.graph.add_resource(resource_ref(middle), middle.metadata.owners)
    gc.graph.add_resource(resource_ref(lower), lower.metadata.owners)

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


async def test_gc_handling_of_cycles(caplog, loop):
    """In case of cycle in the dependency graph, the Garbage Collector removes the
    resources that constitute the cycle, but keeps the others.
    """
    endpoint = "http://localhost:1234"
    gc = GarbageCollector(endpoint)

    uppest = ClusterFactory()
    upper = ClusterFactory(metadata__owners=[resource_ref(uppest)])
    middle = ClusterFactory(metadata__owners=[resource_ref(upper)])
    other = ClusterFactory(metadata__owners=[resource_ref(upper), resource_ref(uppest)])
    lower = ClusterFactory(metadata__owners=[resource_ref(middle)])

    # Create a cycle between upper, middle and lower
    upper.metadata.owners = [resource_ref(lower)]

    async with Client(url=endpoint, loop=loop) as client:
        await gc.prepare(client)

        # Let the gc handle all resources. The cycle should be detected,
        # and all the resources that constitutes it should be removed.
        await gc.on_received_new(uppest)
        await gc.on_received_new(upper)
        await gc.on_received_new(middle)
        await gc.on_received_new(other)
        await gc.on_received_new(lower)

        # The other relationships should be kept
        assert len(gc.graph._relationships) == 2

        uppest_dependents = gc.graph._relationships[resource_ref(uppest)]
        assert len(uppest_dependents) == 1
        other_dependents = gc.graph._relationships[resource_ref(other)]
        assert len(other_dependents) == 0

    assert upper.metadata.name in caplog.text
    assert middle.metadata.name in caplog.text
    assert lower.metadata.name in caplog.text

    # No issues with other and uppest
    assert other.metadata.name not in caplog.text
    assert uppest.metadata.name not in caplog.text


async def test_gc_handling_of_resource_with_dependent(loop, caplog):
    """If resources are deleted by the API, but have still dependents on the dependency
    graph, the garbage collector issues a warning message.
    """
    endpoint = "http://localhost:1234"
    gc = GarbageCollector(endpoint)

    upper = ClusterFactory()
    misc = ClusterFactory(metadata__owners=[resource_ref(upper)])
    other = ClusterFactory(metadata__owners=[resource_ref(upper)])

    async with Client(url=endpoint, loop=loop) as client:
        await gc.prepare(client)

        await gc.on_received_new(upper)
        await gc.on_received_new(misc)
        await gc.on_received_new(other)

        # Receive upper as deleted, even if it has still dependents on the graph
        await gc.on_received_deleted(upper)

    assert upper.metadata.name in caplog.text
    assert misc.metadata.name in caplog.text
    assert other.metadata.name in caplog.text


async def wait_for_resource(resource, graph, present=True, max_retry=10):
    """Verify the presence or absence of a resource in a dependency graph. If the
    resource is not in the wanted state (present or absent), the lookup will be retried
    the given number of times.

    Args:
        resource (krake.data.serializable.ApiObject): the resource to look for.
        graph (DependencyGraph): the graph in which the resource should be looked for.
        present (bool, optional): if True, wait for the resource to be present.
            Otherwise, wait for the resource to be absent.
        max_retry (int, optional): maximum number of times the check needs to be
            performed.

    Raises:
        AssertionError: if the resource is not in the wanted state after the given
            number of retries.

    """
    res_ref = resource_ref(resource)
    for i in count():
        if (res_ref in graph._relationships) == present:
            return
        await asyncio.sleep(0.1)

        if i == max_retry:
            assert False


@with_timeout(3)
async def test_gc_error_handling(aiohttp_server, config, db, loop, caplog):
    """Test the resilience of the garbage collector after an issue occurred with the
    dependency graph. The gc should not stop and continue its work.
    """
    server = await aiohttp_server(create_app(config))
    gc = GarbageCollector(server_endpoint(server), worker_count=1)

    upper = ClusterFactory()
    middle = ClusterFactory(metadata__owners=[resource_ref(upper)])
    lower = ClusterFactory(metadata__owners=[resource_ref(middle)])

    misc = ClusterFactory()
    other = ClusterFactory(metadata__owners=[resource_ref(misc)])

    await db.put(upper)
    await db.put(middle)
    await db.put(lower)

    after_cycle = loop.create_future()

    async def add_cycle():
        await wait_for_resource(upper, gc.graph)
        await wait_for_resource(middle, gc.graph)
        await wait_for_resource(lower, gc.graph)

        # Add the dependency cycle
        stored = await db.get(
            Cluster, namespace=upper.metadata.namespace, name=upper.metadata.name
        )
        stored.metadata.owners = [resource_ref(lower)]
        await db.put(stored)

        # Add resources to the gc, to test if it did not crash after the cycle detection
        await db.put(misc)
        await db.put(other)

        # Wait for the gc to receive and handle the new resources
        await wait_for_resource(other, gc.graph)
        await wait_for_resource(misc, gc.graph)
        after_cycle.set_result(None)

    async def stop_controller():
        # Wait for the gc to finish removing the cycle
        await after_cycle
        await wait_for_resource(lower, gc.graph, present=False)
        await wait_for_resource(middle, gc.graph, present=False)
        await wait_for_resource(upper, gc.graph, present=False)

        # Stop the gc
        run_task.cancel()
        with suppress(asyncio.CancelledError):
            await run_task

    # Graph is deleted at the end of run() on the gc
    graph_copy = gc.graph

    run_task = loop.create_task(gc.run())

    with suppress(asyncio.CancelledError):
        await asyncio.gather(run_task, add_cycle(), stop_controller())

    assert after_cycle.done()

    assert upper.metadata.name in caplog.text
    assert middle.metadata.name in caplog.text
    assert lower.metadata.name in caplog.text

    # Even with a cycle, the gc continue working
    assert resource_ref(other) in graph_copy._relationships
    assert resource_ref(misc) in graph_copy._relationships

    assert resource_ref(upper) not in graph_copy._relationships
    assert resource_ref(middle) not in graph_copy._relationships
    assert resource_ref(lower) not in graph_copy._relationships
