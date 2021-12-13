from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.client.kubernetes import KubernetesApi
from krake.data.core import WatchEventType
from krake.utils import aenumerate
from krake.data.kubernetes import ClusterList, Application, ApplicationList, Cluster
from krake.test_utils import with_timeout


from tests.factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_create_application(aiohttp_server, config, db, loop):
    # MISSING Resource-specific elements can be set here
    data = ApplicationFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_application(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified

    # MISSING The resource-specific attributes can be verified here.
    # assert received.spec == data.spec

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_application(aiohttp_server, config, db, loop):
    data = ApplicationFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.delete_application(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.deleted is not None

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_list_applications(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_applications(
            namespace="testing",
        )

    assert received.api == "kubernetes"
    assert received.kind == "ApplicationList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_applications(aiohttp_server, config, db, loop):
    data = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_applications(
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


async def test_list_all_applications(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_all_applications()

    assert received.api == "kubernetes"
    assert received.kind == "ApplicationList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_applications(aiohttp_server, config, db, loop):
    data = [
        ApplicationFactory(metadata__namespace="testing"),
        ApplicationFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_all_applications() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_application(aiohttp_server, config, db, loop):
    data = ApplicationFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.read_application(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_application(aiohttp_server, config, db, loop):
    # MISSING Resource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)
    # MISSING The resource-specific attributes can be updated here
    # data.spec.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    # MISSING Assertions on resource-specific received values.
    # assert received.spec.foo == bar

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    # MISSING Assertions on resource-specific updated values.
    # assert data.spec.foo == bar


async def test_update_application_binding(aiohttp_server, config, db, loop):
    # MISSING Subresource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.binding.foo = bar

    binding = ClusterBinding()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application_binding(
            namespace=data.metadata.namespace, name=data.metadata.name, body=binding
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"

    # MISSING Assertions on subresource-specific received values.
    # assert received.binding.foo == bar

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    # MISSING Assertions on subresource-specific updated values.
    # assert received.binding == data.binding
    # assert received.binding.foo == bar


async def test_update_application_complete(aiohttp_server, config, db, loop):
    # MISSING Subresource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.complete.foo = bar

    complete = ApplicationComplete()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application_complete(
            namespace=data.metadata.namespace, name=data.metadata.name, body=complete
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"

    # MISSING Assertions on subresource-specific received values.
    # assert received.complete.foo == bar

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    # MISSING Assertions on subresource-specific updated values.
    # assert received.complete == data.complete
    # assert received.complete.foo == bar


async def test_update_application_status(aiohttp_server, config, db, loop):
    # MISSING Subresource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.status.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"

    # MISSING Assertions on subresource-specific received values.
    # assert received.status.foo == bar

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    # MISSING Assertions on subresource-specific updated values.
    # assert received.status == data.status
    # assert received.status.foo == bar


async def test_create_cluster(aiohttp_server, config, db, loop):
    # MISSING Resource-specific elements can be set here
    data = ClusterFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_cluster(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified

    # MISSING The resource-specific attributes can be verified here.
    # assert received.spec == data.spec

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_cluster(aiohttp_server, config, db, loop):
    data = ClusterFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.delete_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert received.metadata.deleted is not None

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_list_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_clusters(
            namespace="testing",
        )

    assert received.api == "kubernetes"
    assert received.kind == "ClusterList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_clusters(aiohttp_server, config, db, loop):
    data = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_clusters(
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


async def test_list_all_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_all_clusters()

    assert received.api == "kubernetes"
    assert received.kind == "ClusterList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_clusters(aiohttp_server, config, db, loop):
    data = [
        ClusterFactory(metadata__namespace="testing"),
        ClusterFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_all_clusters() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_cluster(aiohttp_server, config, db, loop):
    data = ClusterFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.read_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_cluster(aiohttp_server, config, db, loop):
    # MISSING Resource-specific attributes can be set here
    data = ClusterFactory()
    await db.put(data)
    # MISSING The resource-specific attributes can be updated here
    # data.spec.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert data.metadata.modified < received.metadata.modified
    # MISSING Assertions on resource-specific received values.
    # assert received.spec.foo == bar

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    # MISSING Assertions on resource-specific updated values.
    # assert data.spec.foo == bar


async def test_update_cluster_status(aiohttp_server, config, db, loop):
    # MISSING Subresource-specific attributes can be set here
    data = ClusterFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.status.foo = bar

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_cluster_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"

    # MISSING Assertions on subresource-specific received values.
    # assert received.status.foo == bar

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    # MISSING Assertions on subresource-specific updated values.
    # assert received.status == data.status
    # assert received.status.foo == bar

