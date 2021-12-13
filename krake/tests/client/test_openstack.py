from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.client.openstack import OpenstackApi
from krake.data.core import WatchEventType
from krake.utils import aenumerate
from krake.data.openstack import ProjectList, MagnumClusterList, MagnumCluster, Project
from krake.test_utils import with_timeout


from tests.factories.openstack import MagnumClusterFactory, ProjectFactory


async def test_create_magnum_cluster(aiohttp_server, config, db, loop):
    # MISSING Resource-specific elements can be set here
    data = MagnumClusterFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
        received = await openstack_api.create_magnum_cluster(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified

    # MISSING The resource-specific attributes can be verified here.
    # assert received.spec == data.spec

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_magnum_cluster(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
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
        openstack_api = OpenstackApi(client)
        received = await openstack_api.list_magnum_clusters(
            namespace="testing",
        )

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
        openstack_api = OpenstackApi(client)
        async with openstack_api.watch_magnum_clusters(
            namespace="testing",
        ) as watcher:
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
        openstack_api = OpenstackApi(client)
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
        openstack_api = OpenstackApi(client)
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
        openstack_api = OpenstackApi(client)
        received = await openstack_api.read_magnum_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_magnum_cluster(aiohttp_server, config, db, loop):
    # MISSING Resource-specific attributes can be set here
    data = MagnumClusterFactory()
    await db.put(data)
    # MISSING The resource-specific attributes can be updated here
    # data.spec.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
        received = await openstack_api.update_magnum_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert data.metadata.modified < received.metadata.modified
    # MISSING Assertions on resource-specific received values.
    # assert received.spec.foo == bar

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    # MISSING Assertions on resource-specific updated values.
    # assert data.spec.foo == bar


async def test_update_magnum_cluster_binding(aiohttp_server, config, db, loop):
    # MISSING Subresource-specific attributes can be set here
    data = MagnumClusterFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.binding.foo = bar

    binding = MagnumClusterBinding()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
        received = await openstack_api.update_magnum_cluster_binding(
            namespace=data.metadata.namespace, name=data.metadata.name, body=binding
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"

    # MISSING Assertions on subresource-specific received values.
    # assert received.binding.foo == bar

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    # MISSING Assertions on subresource-specific updated values.
    # assert received.binding == data.binding
    # assert received.binding.foo == bar


async def test_update_magnum_cluster_status(aiohttp_server, config, db, loop):
    # MISSING Subresource-specific attributes can be set here
    data = MagnumClusterFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.status.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
        received = await openstack_api.update_magnum_cluster_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"

    # MISSING Assertions on subresource-specific received values.
    # assert received.status.foo == bar

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    # MISSING Assertions on subresource-specific updated values.
    # assert received.status == data.status
    # assert received.status.foo == bar


async def test_create_project(aiohttp_server, config, db, loop):
    # MISSING Resource-specific elements can be set here
    data = ProjectFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
        received = await openstack_api.create_project(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "Project"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified

    # MISSING The resource-specific attributes can be verified here.
    # assert received.spec == data.spec

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_project(aiohttp_server, config, db, loop):
    data = ProjectFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
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
        openstack_api = OpenstackApi(client)
        received = await openstack_api.list_projects(
            namespace="testing",
        )

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
        openstack_api = OpenstackApi(client)
        async with openstack_api.watch_projects(
            namespace="testing",
        ) as watcher:
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
        openstack_api = OpenstackApi(client)
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
        openstack_api = OpenstackApi(client)
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
        openstack_api = OpenstackApi(client)
        received = await openstack_api.read_project(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_project(aiohttp_server, config, db, loop):
    # MISSING Resource-specific attributes can be set here
    data = ProjectFactory()
    await db.put(data)
    # MISSING The resource-specific attributes can be updated here
    # data.spec.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
        received = await openstack_api.update_project(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "Project"
    assert data.metadata.modified < received.metadata.modified
    # MISSING Assertions on resource-specific received values.
    # assert received.spec.foo == bar

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    # MISSING Assertions on resource-specific updated values.
    # assert data.spec.foo == bar


async def test_update_project_status(aiohttp_server, config, db, loop):
    # MISSING Subresource-specific attributes can be set here
    data = ProjectFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.status.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenstackApi(client)
        received = await openstack_api.update_project_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "openstack"
    assert received.kind == "Project"

    # MISSING Assertions on subresource-specific received values.
    # assert received.status.foo == bar

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    # MISSING Assertions on subresource-specific updated values.
    # assert received.status == data.status
    # assert received.status.foo == bar

