import asyncio
from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.client.openstack import OpenStackApi
from krake.data.core import ListMetadata, WatchEventType
from krake.data.openstack import Project, MagnumCluster
from krake.utils import aenumerate
from krake.test_utils import with_timeout

from factories.openstack import ProjectFactory, MagnumClusterFactory


async def test_list_projects(aiohttp_server, config, db, loop):
    # Populate database
    data = [ProjectFactory(), ProjectFactory()]
    for project in data:
        await db.put(project)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        projects = await openstack_api.list_projects(namespace="testing")

    assert projects.api == "openstack"
    assert projects.kind == "ProjectList"
    assert isinstance(projects.metadata, ListMetadata)

    key = attrgetter("metadata.name")
    assert sorted(projects.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_projects(aiohttp_server, config, loop):
    data = [ProjectFactory() for _ in range(10)]

    async def modify(openstack_api):
        for project in data:
            await openstack_api.create_project(
                namespace=project.metadata.namespace,
                name=project.metadata.name,
                body=project,
            )

    async def watch(watcher):
        async for i, event in aenumerate(watcher):
            expected = data[i]
            assert event.type == WatchEventType.ADDED
            assert event.object == expected

            if i == len(data) - 1:
                break

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)

        async with openstack_api.watch_projects(namespace="testing") as watcher:
            watching = loop.create_task(watch(watcher))
            modifying = loop.create_task(modify(openstack_api))

            await asyncio.wait(
                [watching, modifying], return_when=asyncio.FIRST_EXCEPTION
            )


@with_timeout(3)
async def test_watch_all_projects(aiohttp_server, config, loop):
    data = [
        ProjectFactory(metadata__namespace="testing"),
        ProjectFactory(metadata__namespace="default"),
        ProjectFactory(metadata__namespace="testing"),
        ProjectFactory(metadata__namespace="system"),
        ProjectFactory(metadata__namespace="testing"),
    ]

    async def modify(openstack_api):
        for project in data:
            await openstack_api.create_project(
                namespace=project.metadata.namespace,
                name=project.metadata.name,
                body=project,
            )

    async def watch(watcher):
        async for i, event in aenumerate(watcher):
            expected = data[i]
            assert event.type == WatchEventType.ADDED
            assert event.object == expected

            if i == len(data) - 1:
                break

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)

        async with openstack_api.watch_all_projects() as watcher:
            watching = loop.create_task(watch(watcher))
            modifying = loop.create_task(modify(openstack_api))

            await asyncio.wait(
                [watching, modifying], return_when=asyncio.FIRST_EXCEPTION
            )


async def test_create_project(aiohttp_server, config, db, loop):
    data = ProjectFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.create_project(
            namespace=data.metadata.namespace, body=data
        )

    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_project(aiohttp_server, config, db, loop):
    project = ProjectFactory()
    await db.put(project)
    project.spec = ProjectFactory().spec

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.update_project(
            namespace=project.metadata.namespace,
            name=project.metadata.name,
            body=project,
        )

    assert received.spec == project.spec
    assert received.metadata.created == project.metadata.created
    assert received.metadata.modified

    stored = await db.get(
        Project, namespace=project.metadata.namespace, name=project.metadata.name
    )
    assert stored == received


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


async def test_delete_project(aiohttp_server, config, db, loop):
    data = ProjectFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.delete_project(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received.metadata.deleted is not None

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored.metadata.deleted is not None


async def test_list_magnum_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [MagnumClusterFactory(), MagnumClusterFactory()]
    for cluster in data:
        await db.put(cluster)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        projects = await openstack_api.list_magnum_clusters(namespace="testing")

    assert projects.api == "openstack"
    assert projects.kind == "ProjectList"
    assert isinstance(projects.metadata, ListMetadata)

    key = attrgetter("metadata.name")
    assert sorted(projects.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_magnum_clusters(aiohttp_server, config, loop):
    data = [MagnumClusterFactory() for _ in range(10)]

    async def modify(openstack_api):
        for cluster in data:
            await openstack_api.create_project(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )

    async def watch(watcher):
        async for i, event in aenumerate(watcher):
            expected = data[i]
            assert event.type == WatchEventType.ADDED
            assert event.object == expected

            if i == len(data) - 1:
                break

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)

        async with openstack_api.watch_magnum_clusters(namespace="testing") as watcher:
            watching = loop.create_task(watch(watcher))
            modifying = loop.create_task(modify(openstack_api))

            await asyncio.wait(
                [watching, modifying], return_when=asyncio.FIRST_EXCEPTION
            )


@with_timeout(3)
async def test_watch_all_magnum_clusters(aiohttp_server, config, loop):
    data = [
        MagnumClusterFactory(metadata__namespace="testing"),
        MagnumClusterFactory(metadata__namespace="default"),
        MagnumClusterFactory(metadata__namespace="testing"),
        MagnumClusterFactory(metadata__namespace="system"),
        MagnumClusterFactory(metadata__namespace="testing"),
    ]

    async def modify(openstack_api):
        for cluster in data:
            await openstack_api.create_project(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )

    async def watch(watcher):
        async for i, event in aenumerate(watcher):
            expected = data[i]
            assert event.type == WatchEventType.ADDED
            assert event.object == expected

            if i == len(data) - 1:
                break

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)

        async with openstack_api.watch_all_magnum_clusters() as watcher:
            watching = loop.create_task(watch(watcher))
            modifying = loop.create_task(modify(openstack_api))

            await asyncio.wait(
                [watching, modifying], return_when=asyncio.FIRST_EXCEPTION
            )


async def test_create_magnum_cluster(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.create_magnum_cluster(
            namespace=data.metadata.namespace, body=data
        )

    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_magnum_cluster(aiohttp_server, config, db, loop):
    cluster = MagnumClusterFactory()
    await db.put(cluster)
    cluster.spec.master_count = 3
    cluster.spec.node_count = 7

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.update_magnum_cluster(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

    assert received.spec == cluster.spec
    assert received.metadata.created == cluster.metadata.created
    assert received.metadata.modified

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored == received


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


async def test_delete_magnum_cluster(aiohttp_server, config, db, loop):
    data = MagnumClusterFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        openstack_api = OpenStackApi(client)
        received = await openstack_api.delete_magnum_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received.metadata.deleted is not None

    stored = await db.get(
        MagnumCluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored.metadata.deleted is not None
