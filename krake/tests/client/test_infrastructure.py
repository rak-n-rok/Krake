from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.client.infrastructure import InfrastructureApi
from krake.data.core import WatchEventType
from krake.data.infrastructure import (
    InfrastructureProvider, InfrastructureProviderRef,
    Cloud,
    GlobalCloud,
    GlobalInfrastructureProvider,
    CloudState,
)
from krake.test_utils import with_timeout, aenumerate
from tests.factories.core import ReasonFactory

from tests.factories.infrastructure import (
    InfrastructureProviderFactory,
    CloudFactory,
    GlobalCloudFactory,
    GlobalInfrastructureProviderFactory,
)


async def test_create_global_infrastructure_provider(aiohttp_server, config, db, loop):
    data = GlobalInfrastructureProviderFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.create_global_infrastructure_provider(
            body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "GlobalInfrastructureProvider"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(GlobalInfrastructureProvider, name=data.metadata.name)
    assert stored == received
    assert stored.spec == data.spec


async def test_delete_global_infrastructure_provider(aiohttp_server, config, db, loop):
    data = GlobalInfrastructureProviderFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.delete_global_infrastructure_provider(
            name=data.metadata.name
        )

    assert received.api == "infrastructure"
    assert received.kind == "GlobalInfrastructureProvider"
    assert received.metadata.deleted is not None

    stored = await db.get(GlobalInfrastructureProvider, name=data.metadata.name)
    assert stored == received


async def test_list_global_infrastructure_providers(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.list_global_infrastructure_providers()

    assert received.api == "infrastructure"
    assert received.kind == "GlobalInfrastructureProviderList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_global_infrastructure_providers(aiohttp_server, config, db, loop):
    data = [
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        async with infrastructure_api.watch_global_infrastructure_providers() as watcher:  # noqa: E501
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


async def test_read_global_infrastructure_provider(aiohttp_server, config, db, loop):
    data = GlobalInfrastructureProviderFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.read_global_infrastructure_provider(
            name=data.metadata.name
        )
        assert received == data


async def test_update_global_infrastructure_provider(aiohttp_server, config, db, loop):
    data = GlobalInfrastructureProviderFactory(spec__type="im")
    await db.put(data)

    data.spec.im.url += "/other/path"

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.update_global_infrastructure_provider(
            name=data.metadata.name, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "GlobalInfrastructureProvider"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(GlobalInfrastructureProvider, name=data.metadata.name)
    assert stored == received


async def test_create_infrastructure_provider(aiohttp_server, config, db, loop):
    data = InfrastructureProviderFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.create_infrastructure_provider(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "InfrastructureProvider"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        InfrastructureProvider,
        namespace=data.metadata.namespace,
        name=data.metadata.name,
    )
    assert stored == received
    assert stored.spec == data.spec


async def test_delete_infrastructure_provider(aiohttp_server, config, db, loop):
    data = InfrastructureProviderFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.delete_infrastructure_provider(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "infrastructure"
    assert received.kind == "InfrastructureProvider"
    assert received.metadata.deleted is not None

    stored = await db.get(
        InfrastructureProvider,
        namespace=data.metadata.namespace,
        name=data.metadata.name,
    )
    assert stored == received


async def test_list_infrastructure_providers(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.list_infrastructure_providers(
            namespace="testing",
        )

    assert received.api == "infrastructure"
    assert received.kind == "InfrastructureProviderList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_infrastructure_providers(aiohttp_server, config, db, loop):
    data = [
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        async with infrastructure_api.watch_infrastructure_providers(
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


async def test_list_all_infrastructure_providers(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.list_all_infrastructure_providers()

    assert received.api == "infrastructure"
    assert received.kind == "InfrastructureProviderList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_infrastructure_providers(aiohttp_server, config, db, loop):
    data = [
        InfrastructureProviderFactory(metadata__namespace="testing"),
        InfrastructureProviderFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        async with infrastructure_api.watch_all_infrastructure_providers() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_infrastructure_provider(aiohttp_server, config, db, loop):
    data = InfrastructureProviderFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.read_infrastructure_provider(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_infrastructure_provider(aiohttp_server, config, db, loop):
    data = InfrastructureProviderFactory(spec__type="im")
    await db.put(data)

    data.spec.im.url += "/other/path"

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.update_infrastructure_provider(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "InfrastructureProvider"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        InfrastructureProvider,
        namespace=data.metadata.namespace,
        name=data.metadata.name,
    )
    assert stored == received
    assert stored.spec == received.spec


async def test_create_global_cloud(aiohttp_server, config, db, loop):
    data = GlobalCloudFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.create_global_cloud(body=data)

    assert received.api == "infrastructure"
    assert received.kind == "GlobalCloud"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored == received


async def test_delete_global_cloud(aiohttp_server, config, db, loop):
    data = GlobalCloudFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.delete_global_cloud(name=data.metadata.name)

    assert received.api == "infrastructure"
    assert received.kind == "GlobalCloud"
    assert received.metadata.deleted is not None

    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored == received


async def test_list_global_clouds(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.list_global_clouds()

    assert received.api == "infrastructure"
    assert received.kind == "GlobalCloudList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_global_clouds(aiohttp_server, config, db, loop):
    data = [
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        async with infrastructure_api.watch_global_clouds() as watcher:
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


async def test_read_global_cloud(aiohttp_server, config, db, loop):
    data = GlobalCloudFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.read_global_cloud(name=data.metadata.name)
        assert received == data


async def test_update_global_cloud(aiohttp_server, config, db, loop):
    data = GlobalCloudFactory()
    await db.put(data)

    data.spec.openstack.url += "/other/path"

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.update_global_cloud(
            name=data.metadata.name, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "GlobalCloud"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored == received
    assert stored.spec == received.spec


async def test_update_global_cloud_status(aiohttp_server, config, db, loop):
    data = GlobalCloudFactory(status__state=CloudState.ONLINE)
    await db.put(data)

    data.status.state = CloudState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.update_global_cloud_status(
            name=data.metadata.name, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "GlobalCloud"

    assert received.status.state == CloudState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored == received
    assert stored.status.state == CloudState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]


async def test_create_cloud(aiohttp_server, config, db, loop):
    data = CloudFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.create_cloud(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "Cloud"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.status.state == CloudState.ONLINE

    stored = await db.get(
        Cloud, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_cloud(aiohttp_server, config, db, loop):
    data = CloudFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.delete_cloud(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "infrastructure"
    assert received.kind == "Cloud"
    assert received.metadata.deleted is not None

    stored = await db.get(
        Cloud, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_list_clouds(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.list_clouds(
            namespace="testing",
        )

    assert received.api == "infrastructure"
    assert received.kind == "CloudList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_clouds(aiohttp_server, config, db, loop):
    data = [
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        async with infrastructure_api.watch_clouds(
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


async def test_list_all_clouds(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.list_all_clouds()

    assert received.api == "infrastructure"
    assert received.kind == "CloudList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_clouds(aiohttp_server, config, db, loop):
    data = [
        CloudFactory(metadata__namespace="testing"),
        CloudFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        async with infrastructure_api.watch_all_clouds() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_cloud(aiohttp_server, config, db, loop):
    data = CloudFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.read_cloud(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_cloud(aiohttp_server, config, db, loop):
    data = CloudFactory()
    await db.put(data)

    data.spec.openstack.url += "/other/path"

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.update_cloud(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "Cloud"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Cloud, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_cloud_status(aiohttp_server, config, db, loop):
    data = CloudFactory(status__state=CloudState.ONLINE)
    await db.put(data)

    data.status.state = CloudState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.update_cloud_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "infrastructure"
    assert received.kind == "Cloud"
    assert received.status.state == CloudState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(
        Cloud, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    assert stored.status.state == CloudState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]


async def test_read_cloud_binding(aiohttp_server, config, db, loop):
    """Test the :meth:`read_cloud_binding` method

    Checks that the method returns the regular infrastructure provider registered for a
    regular cloud.

    Steps:
        1. Create a cloud and a suitable infrastructure provider
        2. Register the infrastructure provider for the cloud
        3. Put both resources into the Krake database
        4. Call the target method with the cloud

    Asserts:
        The registered infrastructure provider is returned
    """

    infra_provider = InfrastructureProviderFactory()
    cloud = CloudFactory()

    # Register infrastructure provider for cloud
    # NOTE: That is essentially what `rok.infrastructure.update_cloud` does through the
    #       Krake API.
    cloud.spec.openstack.infrastructure_provider = \
        InfrastructureProviderRef(name=infra_provider.metadata.name,
                                  namespaced=infra_provider.metadata.namespace)

    await db.put(infra_provider)
    await db.put(cloud)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.read_cloud_binding(
            namespace=cloud.metadata.namespace,
            name=cloud.metadata.name
        )

        assert received == infra_provider


async def test_read_global_cloud_binding(aiohttp_server, config, db, loop):
    """Test the :meth:`read_global_cloud_binding` method

    Checks that the method returns the global infrastructure provider registered for a
    global cloud.

    Steps:
        1. Create a global cloud and a suitable infrastructure provider
        2. Register the infrastructure provider for the global cloud
        3. Put both resources into the Krake database
        4. Call the target method with the global cloud

    Asserts:
        The registered global infrastructure provider is returned
    """

    global_infra_provider = GlobalInfrastructureProviderFactory()
    global_cloud = GlobalCloudFactory()

    # Register infrastructure provider for cloud
    # NOTE: That is essentially what `rok.infrastructure.update_cloud` does through the
    #       Krake API.
    global_cloud.spec.openstack.infrastructure_provider = \
        InfrastructureProviderRef(name=global_infra_provider.metadata.name)

    await db.put(global_infra_provider)
    await db.put(global_cloud)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        infrastructure_api = InfrastructureApi(client)
        received = await infrastructure_api.read_global_cloud_binding(
            name=global_cloud.metadata.name
        )

        assert received == global_infra_provider
