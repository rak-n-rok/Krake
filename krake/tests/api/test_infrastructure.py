import asyncio
import json

import pytz
from itertools import count
from operator import attrgetter

from krake.api.app import create_app
from krake.api.helpers import HttpProblem, HttpProblemTitle
from krake.data.core import WatchEventType, WatchEvent, resource_ref
from krake.data.infrastructure import (
    Cloud,
    InfrastructureProvider,
    GlobalCloud,
    InfrastructureProviderList,
    CloudList,
    GlobalCloudList,
    GlobalInfrastructureProviderList,
    GlobalInfrastructureProvider,
    CloudState,
)
from tests.factories.core import ReasonFactory

from tests.factories.infrastructure import (
    CloudFactory,
    InfrastructureProviderFactory,
    GlobalCloudFactory,
    GlobalInfrastructureProviderFactory,
)

from tests.factories.fake import fake


async def test_create_global_infrastructure_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalInfrastructureProviderFactory()

    resp = await client.post(
        "/infrastructure/globalinfrastructureproviders", json=data.serialize()
    )
    assert resp.status == 200
    received = GlobalInfrastructureProvider.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace is None
    assert received.metadata.uid
    assert received.spec == data.spec

    stored = await db.get(GlobalInfrastructureProvider, name=data.metadata.name)
    assert stored == received


async def test_create_global_infrastructure_provider_rbac(
    rbac_allow, config, aiohttp_client
):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/infrastructure/globalinfrastructureproviders")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalinfrastructureproviders", "create"):
        resp = await client.post("/infrastructure/globalinfrastructureproviders")
        assert resp.status == 415


async def test_create_global_infrastructure_provider_with_existing_name(
    aiohttp_client, config, db
):
    existing = GlobalInfrastructureProviderFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/infrastructure/globalinfrastructureproviders", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_delete_global_infrastructure_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalInfrastructureProviderFactory()
    await db.put(data)

    resp = await client.delete(
        f"/infrastructure/globalinfrastructureproviders/{data.metadata.name}"
    )
    assert resp.status == 200
    received = GlobalInfrastructureProvider.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(GlobalInfrastructureProvider, name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_global_infrastructure_provider(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalInfrastructureProviderFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/infrastructure/globalinfrastructureproviders/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )


async def test_delete_global_infrastructure_provider_rbac(
    rbac_allow, config, aiohttp_client
):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete(
        "/infrastructure/globalinfrastructureproviders/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalinfrastructureproviders", "delete"):
        resp = await client.delete(
            "/infrastructure/globalinfrastructureproviders/my-resource"
        )
        assert resp.status == 404


async def test_delete_global_infrastructure_provider_already_in_deletion(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = GlobalInfrastructureProviderFactory(
        metadata__deleted=fake.date_time()
    )
    await db.put(in_deletion)

    resp = await client.delete(
        f"/infrastructure/globalinfrastructureproviders/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_global_infrastructure_providers(aiohttp_client, config, db):
    resources = [
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/infrastructure/globalinfrastructureproviders")
    assert resp.status == 200

    body = await resp.json()
    received = GlobalInfrastructureProviderList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_global_infrastructure_providers_rbac(
    rbac_allow, config, aiohttp_client
):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/globalinfrastructureproviders")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalinfrastructureproviders", "list"):
        resp = await client.get("/infrastructure/globalinfrastructureproviders")
        assert resp.status == 200


async def test_watch_global_infrastructure_providers(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        GlobalInfrastructureProviderFactory(),
        GlobalInfrastructureProviderFactory(),
    ]

    async def watch(created):
        resp = await client.get(
            "/infrastructure/globalinfrastructureproviders?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = GlobalInfrastructureProvider.deserialize(event.object)

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

        # Create the GlobalInfrastructureProviders
        for data in resources:
            resp = await client.post(
                "/infrastructure/globalinfrastructureproviders", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/infrastructure/globalinfrastructureproviders/"
            f"{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = GlobalInfrastructureProvider.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_global_infrastructure_provider(aiohttp_client, config, db):
    data = GlobalInfrastructureProviderFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/infrastructure/globalinfrastructureproviders/{data.metadata.name}"
    )
    assert resp.status == 200
    received = GlobalInfrastructureProvider.deserialize(await resp.json())
    assert received == data


async def test_read_global_infrastructure_provider_rbac(
    rbac_allow, config, aiohttp_client
):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/globalinfrastructureproviders/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalinfrastructureproviders", "get"):
        resp = await client.get(
            "/infrastructure/globalinfrastructureproviders/my-resource"
        )
        assert resp.status == 404


async def test_update_global_infrastructure_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalInfrastructureProviderFactory(spec__type="im")
    await db.put(data)

    data.spec.im.url += "/other/path"

    resp = await client.put(
        f"/infrastructure/globalinfrastructureproviders/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = GlobalInfrastructureProvider.deserialize(await resp.json())

    assert received.api == "infrastructure"
    assert received.kind == "GlobalInfrastructureProvider"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(GlobalInfrastructureProvider, name=data.metadata.name)
    assert stored == received


async def test_update_global_infrastructure_provider_to_delete(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalInfrastructureProviderFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the GlobalInfrastructureProvider
    data.metadata.finalizers = []
    resp = await client.put(
        f"/infrastructure/globalinfrastructureproviders/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = GlobalInfrastructureProvider.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The GlobalInfrastructureProvider should be deleted from the database
    stored = await db.get(GlobalInfrastructureProvider, name=data.metadata.name)
    assert stored is None


async def test_update_global_infrastructure_provider_rbac(
    rbac_allow, config, aiohttp_client
):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/infrastructure/globalinfrastructureproviders/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalinfrastructureproviders", "update"):
        resp = await client.put(
            "/infrastructure/globalinfrastructureproviders/my-resource"
        )
        assert resp.status == 415


async def test_update_global_infrastructure_provider_no_changes(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalInfrastructureProviderFactory()
    await db.put(data)

    resp = await client.put(
        f"/infrastructure/globalinfrastructureproviders/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_global_infrastructure_provider_immutable_field(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalInfrastructureProviderFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/infrastructure/globalinfrastructureproviders/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_create_infrastructure_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = InfrastructureProviderFactory()

    resp = await client.post(
        "/infrastructure/namespaces/testing/infrastructureproviders",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = InfrastructureProvider.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    assert received.spec == data.spec

    stored = await db.get(
        InfrastructureProvider, namespace="testing", name=data.metadata.name
    )
    assert stored == received


async def test_create_infrastructure_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/infrastructure/namespaces/testing/infrastructureproviders"
    )
    assert resp.status == 403

    async with rbac_allow("infrastructure", "infrastructureproviders", "create"):
        resp = await client.post(
            "/infrastructure/namespaces/testing/infrastructureproviders"
        )
        assert resp.status == 415


async def test_create_infrastructure_provider_with_existing_name(
    aiohttp_client, config, db
):
    existing = InfrastructureProviderFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/infrastructure/namespaces/testing/infrastructureproviders",
        json=existing.serialize(),
    )
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_delete_infrastructure_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = InfrastructureProviderFactory()
    await db.put(data)

    resp = await client.delete(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{data.metadata.name}"
    )
    assert resp.status == 200
    received = InfrastructureProvider.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(
        InfrastructureProvider, namespace="testing", name=data.metadata.name
    )
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_infrastructure_provider(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    data = InfrastructureProviderFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )


async def test_delete_infrastructure_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete(
        "/infrastructure/namespaces/testing/infrastructureproviders/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("infrastructure", "infrastructureproviders", "delete"):
        resp = await client.delete(
            "/infrastructure/namespaces/testing/infrastructureproviders/my-resource"
        )
        assert resp.status == 404


async def test_delete_infrastructure_provider_already_in_deletion(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = InfrastructureProviderFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_infrastructure_providers(aiohttp_client, config, db):
    resources = [
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        "/infrastructure/namespaces/testing/infrastructureproviders"
    )
    assert resp.status == 200

    body = await resp.json()
    received = InfrastructureProviderList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources[:-1], key=key)


async def test_list_infrastructure_providers_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get(
        "/infrastructure/namespaces/testing/infrastructureproviders"
    )
    assert resp.status == 403

    async with rbac_allow("infrastructure", "infrastructureproviders", "list"):
        resp = await client.get(
            "/infrastructure/namespaces/testing/infrastructureproviders"
        )
        assert resp.status == 200


async def test_watch_infrastructure_providers(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(metadata__namespace="other"),
    ]

    async def watch(created):
        resp = await client.get(
            "/infrastructure/namespaces/testing/"
            "infrastructureproviders?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = InfrastructureProvider.deserialize(event.object)

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

        # Create the InfrastructureProviders
        for data in resources:
            resp = await client.post(
                f"/infrastructure/namespaces/{data.metadata.namespace}/"
                "infrastructureproviders",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/infrastructure/namespaces/testing/infrastructureproviders/"
            f"{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = InfrastructureProvider.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_all_infrastructure_providers(aiohttp_client, config, db):
    resources = [
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(),
        InfrastructureProviderFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/infrastructure/infrastructureproviders")
    assert resp.status == 200

    body = await resp.json()
    received = InfrastructureProviderList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_all_infrastructure_providers_rbac(
    rbac_allow, config, aiohttp_client
):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/infrastructureproviders")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "infrastructureproviders", "list"):
        resp = await client.get("/infrastructure/infrastructureproviders")
        assert resp.status == 200


async def test_watch_all_infrastructure_providers(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        InfrastructureProviderFactory(metadata__namespace="testing"),
        InfrastructureProviderFactory(metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get(
            "/infrastructure/infrastructureproviders?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = InfrastructureProvider.deserialize(event.object)

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

        # Create the InfrastructureProviders
        for data in resources:
            resp = await client.post(
                "/infrastructure/namespaces/testing/infrastructureproviders",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/infrastructure/namespaces/testing/infrastructureproviders/"
            f"{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = InfrastructureProvider.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_infrastructure_provider(aiohttp_client, config, db):
    data = InfrastructureProviderFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{data.metadata.name}"
    )
    assert resp.status == 200
    received = InfrastructureProvider.deserialize(await resp.json())
    assert received == data


async def test_read_infrastructure_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get(
        "/infrastructure/namespaces/testing/infrastructureproviders/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("infrastructure", "infrastructureproviders", "get"):
        resp = await client.get(
            "/infrastructure/namespaces/testing/infrastructureproviders/my-resource"
        )
        assert resp.status == 404


async def test_update_infrastructure_provider(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = InfrastructureProviderFactory(spec__type="im")
    await db.put(data)

    data.spec.im.url += "/other/path"

    resp = await client.put(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = InfrastructureProvider.deserialize(await resp.json())

    assert received.api == "infrastructure"
    assert received.kind == "InfrastructureProvider"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        InfrastructureProvider, namespace="testing", name=data.metadata.name
    )
    assert stored == received


async def test_update_infrastructure_provider_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = InfrastructureProviderFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the InfrastructureProvider
    data.metadata.finalizers = []
    resp = await client.put(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = InfrastructureProvider.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The InfrastructureProvider should be deleted from the database
    stored = await db.get(
        InfrastructureProvider, namespace="testing", name=data.metadata.name
    )
    assert stored is None


async def test_update_infrastructure_provider_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/infrastructure/namespaces/testing/infrastructureproviders/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("infrastructure", "infrastructureproviders", "update"):
        resp = await client.put(
            "/infrastructure/namespaces/testing/infrastructureproviders/my-resource"
        )
        assert resp.status == 415


async def test_update_infrastructure_provider_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = InfrastructureProviderFactory()
    await db.put(data)

    resp = await client.put(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_infrastructure_provider_immutable_field(
    aiohttp_client, config, db
):
    client = await aiohttp_client(create_app(config=config))

    data = InfrastructureProviderFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/infrastructure/namespaces/testing/infrastructureproviders/"
        f"{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_create_global_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory()

    resp = await client.post("/infrastructure/globalclouds", json=data.serialize())
    assert resp.status == 200
    received = GlobalCloud.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace is None
    assert received.metadata.uid
    assert received.spec == data.spec
    assert received.status.state == CloudState.ONLINE

    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored == received


async def test_create_global_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/infrastructure/globalclouds")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalclouds", "create"):
        resp = await client.post("/infrastructure/globalclouds")
        assert resp.status == 415


async def test_create_global_cloud_with_existing_name(aiohttp_client, config, db):
    existing = GlobalCloudFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/infrastructure/globalclouds", json=existing.serialize())
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_delete_global_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory()
    await db.put(data)

    resp = await client.delete(f"/infrastructure/globalclouds/{data.metadata.name}")
    assert resp.status == 200
    received = GlobalCloud.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(GlobalCloud, name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_global_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/infrastructure/globalclouds/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 409
    body = await resp.json()
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )


async def test_delete_global_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/infrastructure/globalclouds/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalclouds", "delete"):
        resp = await client.delete("/infrastructure/globalclouds/my-resource")
        assert resp.status == 404


async def test_delete_global_cloud_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = GlobalCloudFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/infrastructure/globalclouds/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_global_clouds(aiohttp_client, config, db):
    resources = [
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
        GlobalCloudFactory(),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/infrastructure/globalclouds")
    assert resp.status == 200

    body = await resp.json()
    received = GlobalCloudList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_global_clouds_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/globalclouds")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalclouds", "list"):
        resp = await client.get("/infrastructure/globalclouds")
        assert resp.status == 200


async def test_watch_global_clouds(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [GlobalCloudFactory(), GlobalCloudFactory()]

    async def watch(created):
        resp = await client.get("/infrastructure/globalclouds?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = GlobalCloud.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == CloudState.ONLINE
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
                assert data.status.state == CloudState.ONLINE
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == CloudState.ONLINE
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the GlobalClouds
        for data in resources:
            resp = await client.post(
                "/infrastructure/globalclouds", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/infrastructure/globalclouds/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = GlobalCloud.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_global_cloud(aiohttp_client, config, db):
    data = GlobalCloudFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/infrastructure/globalclouds/{data.metadata.name}")
    assert resp.status == 200
    received = GlobalCloud.deserialize(await resp.json())
    assert received == data


async def test_read_global_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/globalclouds/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalclouds", "get"):
        resp = await client.get("/infrastructure/globalclouds/my-resource")
        assert resp.status == 404


async def test_update_global_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory()
    await db.put(data)

    data.spec.openstack.url += "/other/path"

    resp = await client.put(
        f"/infrastructure/globalclouds/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = GlobalCloud.deserialize(await resp.json())

    assert received.api == "infrastructure"
    assert received.kind == "GlobalCloud"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored == received


async def test_update_global_cloud_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the GlobalCloud
    data.metadata.finalizers = []
    resp = await client.put(
        f"/infrastructure/globalclouds/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 200
    received = GlobalCloud.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The GlobalCloud should be deleted from the database
    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored is None


async def test_update_global_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/infrastructure/globalclouds/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalclouds", "update"):
        resp = await client.put("/infrastructure/globalclouds/my-resource")
        assert resp.status == 415


async def test_update_global_cloud_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory()
    await db.put(data)

    resp = await client.put(
        f"/infrastructure/globalclouds/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 400


async def test_update_global_cloud_immutable_field(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/infrastructure/globalclouds/{data.metadata.name}", json=data.serialize()
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_update_global_cloud_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = GlobalCloudFactory(status__state=CloudState.ONLINE)
    await db.put(data)

    data.status.state = CloudState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    resp = await client.put(
        f"/infrastructure/globalclouds/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = GlobalCloud.deserialize(await resp.json())
    assert received.api == "infrastructure"
    assert received.kind == "GlobalCloud"

    assert received.status.state == CloudState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(GlobalCloud, name=data.metadata.name)
    assert stored == received
    assert stored.status.state == CloudState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]


async def test_update_global_cloud_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/infrastructure/globalclouds/my-resource/status")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "globalclouds/status", "update"):
        resp = await client.put("/infrastructure/globalclouds/my-resource/status")
        assert resp.status == 415


async def test_create_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory()

    resp = await client.post(
        "/infrastructure/namespaces/testing/clouds", json=data.serialize()
    )
    assert resp.status == 200
    received = Cloud.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    assert received.status.state == CloudState.ONLINE

    stored = await db.get(Cloud, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/infrastructure/namespaces/testing/clouds")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "clouds", "create"):
        resp = await client.post("/infrastructure/namespaces/testing/clouds")
        assert resp.status == 415


async def test_create_cloud_with_existing_name(aiohttp_client, config, db):
    existing = CloudFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/infrastructure/namespaces/testing/clouds", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_delete_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory()
    await db.put(data)

    resp = await client.delete(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Cloud.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Cloud, namespace="testing", name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )


async def test_delete_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/infrastructure/namespaces/testing/clouds/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "clouds", "delete"):
        resp = await client.delete(
            "/infrastructure/namespaces/testing/clouds/my-resource"
        )
        assert resp.status == 404


async def test_delete_cloud_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = CloudFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/infrastructure/namespaces/testing/clouds/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_clouds(aiohttp_client, config, db):
    resources = [
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/infrastructure/namespaces/testing/clouds")
    assert resp.status == 200

    body = await resp.json()
    received = CloudList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources[:-1], key=key)


async def test_list_clouds_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/namespaces/testing/clouds")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "clouds", "list"):
        resp = await client.get("/infrastructure/namespaces/testing/clouds")
        assert resp.status == 200


async def test_watch_clouds(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        CloudFactory(),
        CloudFactory(),
        CloudFactory(metadata__namespace="other"),
    ]

    async def watch(created):
        resp = await client.get(
            "/infrastructure/namespaces/testing/clouds?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Cloud.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == CloudState.ONLINE
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
                assert data.status.state == CloudState.ONLINE
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == CloudState.ONLINE
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Clouds
        for data in resources:
            resp = await client.post(
                f"/infrastructure/namespaces/{data.metadata.namespace}/clouds",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/infrastructure/namespaces/testing/clouds/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Cloud.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_all_clouds(aiohttp_client, config, db):
    resources = [
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(),
        CloudFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/infrastructure/clouds")
    assert resp.status == 200

    body = await resp.json()
    received = CloudList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_all_clouds_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/clouds")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "clouds", "list"):
        resp = await client.get("/infrastructure/clouds")
        assert resp.status == 200


async def test_watch_all_clouds(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        CloudFactory(metadata__namespace="testing"),
        CloudFactory(metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get("/infrastructure/clouds?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Cloud.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == CloudState.ONLINE
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
                assert data.status.state == CloudState.ONLINE
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == CloudState.ONLINE
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Clouds
        for data in resources:
            resp = await client.post(
                "/infrastructure/namespaces/testing/clouds", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/infrastructure/namespaces/testing/clouds/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Cloud.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_cloud(aiohttp_client, config, db):
    data = CloudFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Cloud.deserialize(await resp.json())
    assert received == data


async def test_read_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/infrastructure/namespaces/testing/clouds/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "clouds", "get"):
        resp = await client.get("/infrastructure/namespaces/testing/clouds/my-resource")
        assert resp.status == 404


async def test_update_cloud(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory()
    await db.put(data)

    data.spec.openstack.url += "/other/path"

    resp = await client.put(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cloud.deserialize(await resp.json())

    assert received.api == "infrastructure"
    assert received.kind == "Cloud"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(Cloud, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_cloud_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the Cloud
    data.metadata.finalizers = []
    resp = await client.put(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cloud.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The Cloud should be deleted from the database
    stored = await db.get(Cloud, namespace="testing", name=data.metadata.name)
    assert stored is None


async def test_update_cloud_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/infrastructure/namespaces/testing/clouds/my-resource")
    assert resp.status == 403

    async with rbac_allow("infrastructure", "clouds", "update"):
        resp = await client.put("/infrastructure/namespaces/testing/clouds/my-resource")
        assert resp.status == 415


async def test_update_cloud_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory()
    await db.put(data)

    resp = await client.put(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_cloud_immutable_field(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_update_cloud_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = CloudFactory(status__state=CloudState.ONLINE)
    await db.put(data)

    data.status.state = CloudState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    resp = await client.put(
        f"/infrastructure/namespaces/testing/clouds/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cloud.deserialize(await resp.json())
    assert received.api == "infrastructure"
    assert received.kind == "Cloud"

    assert received.status.state == CloudState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(Cloud, namespace="testing", name=data.metadata.name)
    assert stored == received
    assert stored.status.state == CloudState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]


async def test_update_cloud_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/infrastructure/namespaces/testing/clouds/my-resource/status"
    )
    assert resp.status == 403

    async with rbac_allow("infrastructure", "clouds/status", "update"):
        resp = await client.put(
            "/infrastructure/namespaces/testing/clouds/my-resource/status"
        )
        assert resp.status == 415
