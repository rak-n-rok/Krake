from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.client.openstack import OpenStackApi
from krake.data.core import resource_ref, ResourceRef, WatchEventType
from krake.data.openstack import (
    Project,
    MagnumCluster,
    MagnumClusterBinding,
    MagnumClusterState,
    ProjectState,
)
from krake.test_utils import with_timeout, aenumerate

from tests.factories.openstack import (
    MagnumClusterFactory,
    ProjectFactory,
    ReasonFactory,
)


async def test_create_magnum_cluster(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.create_magnum_cluster(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_magnum_cluster(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.delete_magnum_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert received.metadata.deleted is not None

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_list_magnum_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.list_magnum_clusters(namespace="testing")

    assert received.api == "openstack"
    assert received.kind == "MagnumClusterList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_magnum_clusters(aiohttp_server, config, db, loop):
    data = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        async with openstack_api.watch_magnum_clusters(namespace="testing") as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                # '1' because of the offset length-index and '1' for the resource in
                # another namespace
                if i == len(data) - 2:
                    break

            await modifying


async def test_list_all_magnum_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.list_all_magnum_clusters()

    assert received.api == "openstack"
    assert received.kind == "MagnumClusterList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_magnum_clusters(aiohttp_server, config, db, loop):
    data = [
        MagnumClusterFactory(metadata__namespace="testing"),
        MagnumClusterFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        async with openstack_api.watch_all_magnum_clusters() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_magnum_cluster(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.read_magnum_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_magnum_cluster(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory(spec__master_count=1, spec__node_count=4)
    await db.put(data)

    # Update node count to 7
    data.spec.node_count = 7

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.update_magnum_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.master_count == 1
    assert received.spec.node_count == 7

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_magnum_cluster_binding(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory()
    project = ProjectFactory()
    await db.put(data)
    await db.put(project)

    project_ref = resource_ref(project)
    binding = MagnumClusterBinding(project=project_ref, template=project.spec.template)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.update_magnum_cluster_binding(
            namespace=data.metadata.namespace, name=data.metadata.name, body=binding
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert received.status.project == project_ref
    assert received.status.template == project.spec.template
    assert project_ref in received.metadata.owners

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_magnum_cluster_status(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)
    await db.put(data)

    data.status.state = MagnumClusterState.FAILED
    data.status.reason = ReasonFactory()
    data.status.project = ResourceRef(
        api="openstack", kind="Project", namespace="testing", name="test-project"
    )

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.update_magnum_cluster_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert received.metadata == data.metadata
    assert received.status == data.status

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_create_project(aiohttp_server, config, db, loop):
    data = ProjectFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.create_project(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "Project"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_project(aiohttp_server, config, db, loop):
    data = ProjectFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.delete_project(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "openstack"
    assert received.kind == "Project"
    assert received.metadata.deleted is not None

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_list_projects(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.list_projects(namespace="testing")

    assert received.api == "openstack"
    assert received.kind == "ProjectList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_projects(aiohttp_server, config, db, loop):
    data = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        async with openstack_api.watch_projects(namespace="testing") as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                # '1' because of the offset length-index and '1' for the resource in
                # another namespace
                if i == len(data) - 2:
                    break

            await modifying


async def test_list_all_projects(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.list_all_projects()

    assert received.api == "openstack"
    assert received.kind == "ProjectList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_projects(aiohttp_server, config, db, loop):
    data = [
        ProjectFactory(metadata__namespace="testing"),
        ProjectFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        async with openstack_api.watch_all_projects() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_project(aiohttp_server, config, db, loop):
    data = ProjectFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.read_project(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_project(aiohttp_server, config, db, loop):
    data = ProjectFactory()
    await db.put(data)
    data.spec = ProjectFactory().spec

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.update_project(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "Project"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_project_status(aiohttp_server, config, db, loop):
    data = ProjectFactory()
    await db.put(data)

    data.status.state = ProjectState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.update_project_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "Project"

    assert received.status.state == ProjectState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored.status.state == ProjectState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]
