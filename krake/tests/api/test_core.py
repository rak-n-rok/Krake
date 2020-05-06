import asyncio
import json
import pytz
from itertools import count
from operator import attrgetter

from krake.api.app import create_app
from krake.api.helpers import HttpReason, HttpReasonCode
from krake.data.core import WatchEventType, WatchEvent, resource_ref
from krake.data.core import (
    Metric,
    MetricsProvider,
    RoleList,
    MetricList,
    RoleBinding,
    RoleBindingList,
    Role,
    MetricsProviderList,
)


from tests.factories.core import (
    MetricFactory,
    MetricSpecFactory,
    MetricsProviderFactory,
    MetricsProviderSpecFactory,
    RoleBindingFactory,
    RoleFactory,
    RoleRuleFactory,
)

from tests.factories.fake import fake


async def test_create_metric(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = MetricFactory()

    resp = await client.post("/core/metrics", json=data.serialize())
    assert resp.status == 200
    received = Metric.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace is None
    assert received.metadata.uid

    stored = await db.get(Metric, name=data.metadata.name)
    assert stored == received


async def test_create_metric_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/metrics")
    assert resp.status == 403

    async with rbac_allow("core", "metrics", "create", namespace=None):
        resp = await client.post("/core/metrics")
        assert resp.status == 415


async def test_create_metric_with_existing_name(aiohttp_client, config, db):
    existing = MetricFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/metrics", json=existing.serialize())
    assert resp.status == 409

    received = await resp.json()
    reason = HttpReason.deserialize(received)
    assert reason.code == HttpReasonCode.RESOURCE_ALREADY_EXISTS


async def test_delete_metric(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricFactory()
    await db.put(data)

    resp = await client.delete(f"/core/metrics/{data.metadata.name}")
    assert resp.status == 200
    received = Metric.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Metric, name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_metric(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/core/metrics/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 409
    body = await resp.json()
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_metric_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/core/metrics/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "metrics", "delete", namespace=None):
        resp = await client.delete("/core/metrics/my-resource")
        assert resp.status == 404


async def test_delete_metric_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = MetricFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(f"/core/metrics/{in_deletion.metadata.name}")
    assert resp.status == 200


async def test_list_metrics(aiohttp_client, config, db):
    resources = [
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
        MetricFactory(),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/metrics")
    assert resp.status == 200

    body = await resp.json()
    received = MetricList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_metrics_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/metrics")
    assert resp.status == 403

    async with rbac_allow("core", "metrics", "list", namespace=None):
        resp = await client.get("/core/metrics")
        assert resp.status == 200


async def test_watch_metrics(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [MetricFactory(), MetricFactory()]

    async def watch(created):
        resp = await client.get("/core/metrics?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Metric.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Metrics
        for data in resources:
            resp = await client.post("/core/metrics", json=data.serialize())
            assert resp.status == 200

        resp = await client.delete(f"/core/metrics/{resources[0].metadata.name}")
        assert resp.status == 200

        received = Metric.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_metric(aiohttp_client, config, db):
    data = MetricFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/metrics/{data.metadata.name}")
    assert resp.status == 200
    received = Metric.deserialize(await resp.json())
    assert received == data


async def test_read_metric_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/metrics/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "metrics", "get", namespace=None):
        resp = await client.get("/core/metrics/my-resource")
        assert resp.status == 404


async def test_update_metric(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricFactory()
    await db.put(data)
    data.spec = MetricSpecFactory(min=-10, max=10)

    resp = await client.put(
        f"/core/metrics/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = Metric.deserialize(await resp.json())

    assert received.api == "core"
    assert received.kind == "Metric"
    assert data.metadata.modified.replace(tzinfo=None) < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(Metric, name=data.metadata.name)
    assert stored == received


async def test_update_metric_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the Metric
    data.metadata.finalizers = []
    resp = await client.put(
        f"/core/metrics/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = Metric.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The Metric should be deleted from the database
    stored = await db.get(Metric, name=data.metadata.name)
    assert stored is None


async def test_update_metric_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/core/metrics/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "metrics", "update", namespace=None):
        resp = await client.put("/core/metrics/my-resource")
        assert resp.status == 415


async def test_create_metrics_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricsProviderFactory()

    resp = await client.post("/core/metricsproviders", json=data.serialize())
    assert resp.status == 200
    received = MetricsProvider.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace is None
    assert received.metadata.uid
    assert received.spec == data.spec

    stored = await db.get(MetricsProvider, name=data.metadata.name)
    assert stored == received


async def test_create_metrics_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/metricsproviders")
    assert resp.status == 403

    async with rbac_allow("core", "metricsproviders", "create", namespace=None):
        resp = await client.post("/core/metricsproviders")
        assert resp.status == 415


async def test_create_metrics_provider_with_existing_name(aiohttp_client, config, db):
    existing = MetricsProviderFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/metricsproviders", json=existing.serialize())
    assert resp.status == 409

    received = await resp.json()
    reason = HttpReason.deserialize(received)
    assert reason.code == HttpReasonCode.RESOURCE_ALREADY_EXISTS


async def test_delete_metrics_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricsProviderFactory()
    await db.put(data)

    resp = await client.delete(f"/core/metricsproviders/{data.metadata.name}")
    assert resp.status == 200
    received = MetricsProvider.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(MetricsProvider, name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_metrics_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricsProviderFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/core/metricsproviders/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 409
    body = await resp.json()
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_metrics_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/core/metricsproviders/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "metricsproviders", "delete", namespace=None):
        resp = await client.delete("/core/metricsproviders/my-resource")
        assert resp.status == 404


async def test_delete_metrics_provider_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = MetricsProviderFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(f"/core/metricsproviders/{in_deletion.metadata.name}")
    assert resp.status == 200


async def test_list_metrics_providers(aiohttp_client, config, db):
    resources = [
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
        MetricsProviderFactory(),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/metricsproviders")
    assert resp.status == 200

    body = await resp.json()
    received = MetricsProviderList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_metrics_providers_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/metricsproviders")
    assert resp.status == 403

    async with rbac_allow("core", "metricsproviders", "list", namespace=None):
        resp = await client.get("/core/metricsproviders")
        assert resp.status == 200


async def test_watch_metrics_providers(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [MetricsProviderFactory(), MetricsProviderFactory()]

    async def watch(created):
        resp = await client.get("/core/metricsproviders?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = MetricsProvider.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the  MetricsProviders
        for data in resources:
            resp = await client.post("/core/metricsproviders", json=data.serialize())
            assert resp.status == 200

        resp = await client.delete(
            f"/core/metricsproviders/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = MetricsProvider.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_metrics_provider(aiohttp_client, config, db):
    data = MetricsProviderFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/metricsproviders/{data.metadata.name}")
    assert resp.status == 200
    received = MetricsProvider.deserialize(await resp.json())
    assert received == data


async def test_read_metrics_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/metricsproviders/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "metricsproviders", "get", namespace=None):
        resp = await client.get("/core/metricsproviders/my-resource")
        assert resp.status == 404


async def test_update_metrics_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricsProviderFactory(spec__type="prometheus")
    await db.put(data)
    data.spec = MetricsProviderSpecFactory(type="static")

    resp = await client.put(
        f"/core/metricsproviders/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = MetricsProvider.deserialize(await resp.json())

    assert received.api == "core"
    assert received.kind == "MetricsProvider"
    assert data.metadata.modified.replace(tzinfo=None) < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(MetricsProvider, name=data.metadata.name)
    assert stored == received


async def test_update_metrics_provider_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MetricsProviderFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the MetricsProvider
    data.metadata.finalizers = []
    resp = await client.put(
        f"/core/metricsproviders/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = MetricsProvider.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The MetricsProvider should be deleted from the database
    stored = await db.get(MetricsProvider, name=data.metadata.name)
    assert stored is None


async def test_update_metrics_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/core/metricsproviders/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "metricsproviders", "update", namespace=None):
        resp = await client.put("/core/metricsproviders/my-resource")
        assert resp.status == 415


async def test_create_role(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleFactory()

    resp = await client.post("/core/roles", json=data.serialize())
    assert resp.status == 200
    received = Role.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace is None
    assert received.metadata.uid

    stored = await db.get(Role, name=data.metadata.name)
    assert stored == received


async def test_create_role_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/roles")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "create", namespace=None):
        resp = await client.post("/core/roles")
        assert resp.status == 415


async def test_create_role_with_existing_name(aiohttp_client, config, db):
    existing = RoleFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/roles", json=existing.serialize())
    assert resp.status == 409

    received = await resp.json()
    reason = HttpReason.deserialize(received)
    assert reason.code == HttpReasonCode.RESOURCE_ALREADY_EXISTS


async def test_delete_role(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleFactory()
    await db.put(data)

    resp = await client.delete(f"/core/roles/{data.metadata.name}")
    assert resp.status == 200
    received = Role.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Role, name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_role(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(f"/core/roles/{data.metadata.name}", json=data.serialize())
    assert resp.status == 409
    body = await resp.json()
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_role_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/core/roles/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "delete", namespace=None):
        resp = await client.delete("/core/roles/my-resource")
        assert resp.status == 404


async def test_delete_role_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = RoleFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(f"/core/roles/{in_deletion.metadata.name}")
    assert resp.status == 200


async def test_list_roles(aiohttp_client, config, db):
    resources = [
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
        RoleFactory(),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/roles")
    assert resp.status == 200

    body = await resp.json()
    received = RoleList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_roles_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/roles")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "list", namespace=None):
        resp = await client.get("/core/roles")
        assert resp.status == 200


async def test_watch_roles(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [RoleFactory(), RoleFactory()]

    async def watch(created):
        resp = await client.get("/core/roles?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Role.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.rules == resources[0].rules
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.rules == resources[1].rules
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.rules == resources[0].rules
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the  Roles
        for data in resources:
            resp = await client.post("/core/roles", json=data.serialize())
            assert resp.status == 200

        resp = await client.delete(f"/core/roles/{resources[0].metadata.name}")
        assert resp.status == 200

        received = Role.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_role(aiohttp_client, config, db):
    data = RoleFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/roles/{data.metadata.name}")
    assert resp.status == 200
    received = Role.deserialize(await resp.json())
    assert received == data


async def test_read_role_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/roles/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "get", namespace=None):
        resp = await client.get("/core/roles/my-resource")
        assert resp.status == 404


async def test_update_role(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleFactory()
    previous_rules = data.rules
    await db.put(data)

    new_rules = [RoleRuleFactory(), RoleRuleFactory(), RoleRuleFactory()]
    assert new_rules != previous_rules
    data.rules = new_rules

    resp = await client.put(f"/core/roles/{data.metadata.name}", json=data.serialize())
    assert resp.status == 200
    received = Role.deserialize(await resp.json())

    assert received.api == "core"
    assert received.kind == "Role"
    assert data.metadata.modified.replace(tzinfo=None) < received.metadata.modified
    assert received.rules == new_rules

    stored = await db.get(Role, name=data.metadata.name)
    assert stored == received


async def test_update_role_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the Role
    data.metadata.finalizers = []
    resp = await client.put(f"/core/roles/{data.metadata.name}", json=data.serialize())
    assert resp.status == 200
    received = Role.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The Role should be deleted from the database
    stored = await db.get(Role, name=data.metadata.name)
    assert stored is None


async def test_update_role_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/core/roles/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "update", namespace=None):
        resp = await client.put("/core/roles/my-resource")
        assert resp.status == 415


async def test_create_role_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleBindingFactory()

    resp = await client.post("/core/rolebindings", json=data.serialize())
    assert resp.status == 200
    received = RoleBinding.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace is None
    assert received.metadata.uid

    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored == received


async def test_create_role_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/rolebindings")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "create", namespace=None):
        resp = await client.post("/core/rolebindings")
        assert resp.status == 415


async def test_create_role_binding_with_existing_name(aiohttp_client, config, db):
    existing = RoleBindingFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/rolebindings", json=existing.serialize())
    assert resp.status == 409

    received = await resp.json()
    reason = HttpReason.deserialize(received)
    assert reason.code == HttpReasonCode.RESOURCE_ALREADY_EXISTS


async def test_delete_role_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleBindingFactory()
    await db.put(data)

    resp = await client.delete(f"/core/rolebindings/{data.metadata.name}")
    assert resp.status == 200
    received = RoleBinding.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(RoleBinding, name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_role_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleBindingFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/core/rolebindings/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 409
    body = await resp.json()
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_role_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/core/rolebindings/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "delete", namespace=None):
        resp = await client.delete("/core/rolebindings/my-resource")
        assert resp.status == 404


async def test_delete_role_binding_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = RoleBindingFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(f"/core/rolebindings/{in_deletion.metadata.name}")
    assert resp.status == 200


async def test_list_role_bindings(aiohttp_client, config, db):
    resources = [
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
        RoleBindingFactory(),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/rolebindings")
    assert resp.status == 200

    body = await resp.json()
    received = RoleBindingList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_role_bindings_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/rolebindings")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "list", namespace=None):
        resp = await client.get("/core/rolebindings")
        assert resp.status == 200


async def test_watch_role_bindings(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [RoleBindingFactory(), RoleBindingFactory()]

    async def watch(created):
        resp = await client.get("/core/rolebindings?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = RoleBinding.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.users == resources[0].users
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.users == resources[1].users
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.users == resources[0].users
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the  RoleBindings
        for data in resources:
            resp = await client.post("/core/rolebindings", json=data.serialize())
            assert resp.status == 200

        resp = await client.delete(f"/core/rolebindings/{resources[0].metadata.name}")
        assert resp.status == 200

        received = RoleBinding.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_role_binding(aiohttp_client, config, db):
    data = RoleBindingFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/rolebindings/{data.metadata.name}")
    assert resp.status == 200
    received = RoleBinding.deserialize(await resp.json())
    assert received == data


async def test_read_role_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/core/rolebindings/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "get", namespace=None):
        resp = await client.get("/core/rolebindings/my-resource")
        assert resp.status == 404


async def test_update_role_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleBindingFactory()
    await db.put(data)
    data.users = ["some", "additional", "users"]
    data.roles = ["and", "other", "roles"]

    resp = await client.put(
        f"/core/rolebindings/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = RoleBinding.deserialize(await resp.json())

    assert received.api == "core"
    assert received.kind == "RoleBinding"
    assert data.metadata.modified.replace(tzinfo=None) < received.metadata.modified
    assert received.users == data.users
    assert received.roles == data.roles

    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored == received


async def test_update_role_binding_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = RoleBindingFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the RoleBinding
    data.metadata.finalizers = []
    resp = await client.put(
        f"/core/rolebindings/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = RoleBinding.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The RoleBinding should be deleted from the database
    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored is None


async def test_update_role_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/core/rolebindings/my-resource")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "update", namespace=None):
        resp = await client.put("/core/rolebindings/my-resource")
        assert resp.status == 415
