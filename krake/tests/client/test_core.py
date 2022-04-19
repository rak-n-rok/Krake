from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.client.core import CoreApi
from krake.data.core import (
    GlobalMetric,
    Metric,
    GlobalMetricsProvider,
    MetricsProvider,
    RoleBinding,
    Role,
    WatchEventType,
)
from krake.test_utils import with_timeout, aenumerate

from tests.factories.core import (
    GlobalMetricFactory,
    MetricFactory,
    GlobalMetricsProviderFactory,
    MetricsProviderFactory,
    MetricsProviderSpecFactory,
    MetricSpecProviderFactory,
    RoleBindingFactory,
    RoleFactory,
    RoleRuleFactory,
)


async def test_create_global_metric(aiohttp_server, config, db, loop):
    data = GlobalMetricFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_global_metric(body=data)

    assert received.api == "core"
    assert received.kind == "GlobalMetric"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified

    stored = await db.get(GlobalMetric, name=data.metadata.name)
    assert stored == received


async def test_delete_global_metric(aiohttp_server, config, db, loop):
    data = GlobalMetricFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_global_metric(name=data.metadata.name)

    assert received.api == "core"
    assert received.kind == "GlobalMetric"
    assert received.spec == data.spec
    assert received.metadata.deleted is not None

    stored = await db.get(GlobalMetric, name=data.metadata.name)
    assert stored == received


async def test_list_global_metrics(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        GlobalMetricFactory(),
        GlobalMetricFactory(),
        GlobalMetricFactory(),
        GlobalMetricFactory(),
        GlobalMetricFactory(),
        GlobalMetricFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.list_global_metrics()

    assert received.api == "core"
    assert received.kind == "GlobalMetricList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_global_metrics(aiohttp_server, config, db, loop):
    data = [
        GlobalMetricFactory(),
        GlobalMetricFactory(),
        GlobalMetricFactory(),
        GlobalMetricFactory(),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        async with core_api.watch_global_metrics(heartbeat=30) as watcher:
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


async def test_read_global_metric(aiohttp_server, config, db, loop):
    data = GlobalMetricFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_global_metric(name=data.metadata.name)
        assert received == data


async def test_update_global_metric(aiohttp_server, config, db, loop):
    data = GlobalMetricFactory()
    await db.put(data)
    data.spec.provider = MetricSpecProviderFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_global_metric(
            name=data.metadata.name, body=data
        )

    assert received.api == "core"
    assert received.kind == "GlobalMetric"

    assert received.spec == data.spec
    assert data.metadata.modified < received.metadata.modified

    stored = await db.get(GlobalMetric, name=data.metadata.name)
    assert stored == received


async def test_create_global_metrics_provider(aiohttp_server, config, db, loop):
    data = GlobalMetricsProviderFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_global_metrics_provider(body=data)

    assert received.api == "core"
    assert received.kind == "GlobalMetricsProvider"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified

    stored = await db.get(GlobalMetricsProvider, name=data.metadata.name)
    assert stored == received


async def test_delete_global_metrics_provider(aiohttp_server, config, db, loop):
    data = GlobalMetricsProviderFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_global_metrics_provider(
            name=data.metadata.name
        )

    assert received.api == "core"
    assert received.kind == "GlobalMetricsProvider"
    assert received.spec == data.spec
    assert received.metadata.deleted is not None

    stored = await db.get(GlobalMetricsProvider, name=data.metadata.name)
    assert stored == received


async def test_list_global_metrics_providers(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.list_global_metrics_providers()

    assert received.api == "core"
    assert received.kind == "GlobalMetricsProviderList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_global_metrics_providers(aiohttp_server, config, db, loop):
    data = [
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
        GlobalMetricsProviderFactory(),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        async with core_api.watch_global_metrics_providers(heartbeat=30) as watcher:
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


async def test_read_global_metrics_provider(aiohttp_server, config, db, loop):
    data = GlobalMetricsProviderFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_global_metrics_provider(name=data.metadata.name)
        assert received == data


async def test_update_global_metrics_provider(aiohttp_server, config, db, loop):
    data = GlobalMetricsProviderFactory(spec__type="static")
    await db.put(data)
    data.spec = MetricsProviderSpecFactory(type="prometheus")

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_global_metrics_provider(
            name=data.metadata.name, body=data
        )

    assert received.api == "core"
    assert received.kind == "GlobalMetricsProvider"

    assert received.spec == data.spec
    assert data.metadata.modified < received.metadata.modified

    stored = await db.get(GlobalMetricsProvider, name=data.metadata.name)
    assert stored == received


async def test_create_metric(aiohttp_server, config, db, loop):

    data = MetricFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_metric(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "core"
    assert received.kind == "Metric"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace
    assert received.metadata.created
    assert received.metadata.modified

    stored = await db.get(
        Metric, name=data.metadata.name, namespace=data.metadata.namespace
    )
    assert stored == received


async def test_delete_metric(aiohttp_server, config, db, loop):
    data = MetricFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_metric(
            name=data.metadata.name, namespace=data.metadata.namespace
        )

    assert received.api == "core"
    assert received.kind == "Metric"
    assert received.spec == data.spec
    assert received.metadata.deleted is not None

    stored = await db.get(
        Metric, name=data.metadata.name, namespace=data.metadata.namespace
    )
    assert stored == received


async def test_list_metrics(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.list_metrics()

    assert received.api == "core"
    assert received.kind == "MetricList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_metrics(aiohttp_server, config, db, loop):
    data = [
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        async with core_api.watch_metrics(heartbeat=30) as watcher:
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


async def test_read_metric(aiohttp_server, config, db, loop):
    data = MetricFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_metric(
            name=data.metadata.name, namespace=data.metadata.namespace
        )
        assert received == data


async def test_update_metric(aiohttp_server, config, db, loop):
    data = MetricFactory()
    await db.put(data)
    data.spec.provider = MetricSpecProviderFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_metric(
            name=data.metadata.name, namespace=data.metadata.namespace, body=data
        )

    assert received.api == "core"
    assert received.kind == "Metric"

    assert received.spec == data.spec
    assert data.metadata.modified < received.metadata.modified

    stored = await db.get(
        Metric, name=data.metadata.name, namespace=data.metadata.namespace
    )
    assert stored == received


async def test_create_metrics_provider(aiohttp_server, config, db, loop):
    data = MetricsProviderFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_metrics_provider(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "core"
    assert received.kind == "MetricsProvider"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace
    assert received.metadata.created
    assert received.metadata.modified

    stored = await db.get(
        MetricsProvider, name=data.metadata.name, namespace=data.metadata.namespace
    )
    assert stored == received


async def test_delete_metrics_provider(aiohttp_server, config, db, loop):
    data = MetricsProviderFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_metrics_provider(
            name=data.metadata.name, namespace=data.metadata.namespace
        )

    assert received.api == "core"
    assert received.kind == "MetricsProvider"
    assert received.spec == data.spec
    assert received.metadata.deleted is not None

    stored = await db.get(
        MetricsProvider, name=data.metadata.name, namespace=data.metadata.namespace
    )
    assert stored == received


async def test_list_metrics_providers(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.list_metrics_providers()

    assert received.api == "core"
    assert received.kind == "MetricsProviderList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_metrics_providers(aiohttp_server, config, db, loop):
    data = [
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        async with core_api.watch_metrics_providers(heartbeat=30) as watcher:
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


async def test_read_metrics_provider(aiohttp_server, config, db, loop):
    data = MetricsProviderFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_metrics_provider(
            name=data.metadata.name, namespace=data.metadata.namespace
        )
        assert received == data


async def test_update_metrics_provider(aiohttp_server, config, db, loop):
    data = MetricsProviderFactory(spec__type="static")
    await db.put(data)
    data.spec = MetricsProviderSpecFactory(type="prometheus")

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_metrics_provider(
            name=data.metadata.name, namespace=data.metadata.namespace, body=data
        )

    assert received.api == "core"
    assert received.kind == "MetricsProvider"

    assert received.spec == data.spec
    assert data.metadata.modified < received.metadata.modified

    stored = await db.get(
        MetricsProvider, name=data.metadata.name, namespace=data.metadata.namespace
    )
    assert stored == received


async def test_create_role(aiohttp_server, config, db, loop):
    data = RoleFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_role(body=data)

    assert received.api == "core"
    assert received.kind == "Role"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified

    stored = await db.get(Role, name=data.metadata.name)
    assert stored == received


async def test_delete_role(aiohttp_server, config, db, loop):
    data = RoleFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_role(name=data.metadata.name)

    assert received.api == "core"
    assert received.kind == "Role"
    assert received.metadata.deleted is not None

    stored = await db.get(Role, name=data.metadata.name)
    assert stored == received


async def test_list_roles(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.list_roles()

    assert received.api == "core"
    assert received.kind == "RoleList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_roles(aiohttp_server, config, db, loop):
    data = [RoleFactory(), RoleFactory(), RoleFactory(), RoleFactory()]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        async with core_api.watch_roles(heartbeat=30) as watcher:
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


async def test_read_role(aiohttp_server, config, db, loop):
    data = RoleFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_role(name=data.metadata.name)
        assert received == data


async def test_update_role(aiohttp_server, config, db, loop):
    data = RoleFactory()
    await db.put(data)
    data.rules.append(RoleRuleFactory())

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_role(name=data.metadata.name, body=data)

    assert received.api == "core"
    assert received.kind == "Role"
    assert received.rules == data.rules
    assert data.metadata.modified < received.metadata.modified

    stored = await db.get(Role, name=data.metadata.name)
    assert stored == received


async def test_create_role_binding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_role_binding(body=data)

    assert received.api == "core"
    assert received.kind == "RoleBinding"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified

    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored == received


async def test_delete_role_binding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_role_binding(name=data.metadata.name)

    assert received.api == "core"
    assert received.kind == "RoleBinding"
    assert received.metadata.deleted is not None

    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored == received


async def test_list_role_bindings(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.list_role_bindings()

    assert received.api == "core"
    assert received.kind == "RoleBindingList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_role_bindings(aiohttp_server, config, db, loop):
    data = [
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        async with core_api.watch_role_bindings(heartbeat=30) as watcher:
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


async def test_read_role_binding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_role_binding(name=data.metadata.name)
        assert received == data


async def test_update_role_binding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory()
    await db.put(data)
    data.users.append("test-user")
    data.roles.append("test-role")

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_role_binding(
            name=data.metadata.name, body=data
        )

    assert received.api == "core"
    assert received.kind == "RoleBinding"
    assert received.users == data.users
    assert received.roles == data.roles
    assert data.metadata.modified < received.metadata.modified

    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored == received
