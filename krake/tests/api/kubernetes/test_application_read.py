import asyncio
import json
from itertools import count
from operator import attrgetter


from krake.api.app import create_app
from krake.data.core import WatchEventType, WatchEvent, resource_ref
from krake.data.kubernetes import (
    Application,
    ApplicationList,
    ApplicationState,
)

from tests.factories.kubernetes import (
    ApplicationFactory,
)
from tests.factories.fake import fake


async def test_list_applications(aiohttp_client, config, db):
    resources = [
        ApplicationFactory(status__state=ApplicationState.PENDING),
        ApplicationFactory(status__state=ApplicationState.CREATING),
        ApplicationFactory(status__state=ApplicationState.RECONCILING),
        ApplicationFactory(status__state=ApplicationState.MIGRATING),
        ApplicationFactory(status__state=ApplicationState.DELETING),
        ApplicationFactory(
            metadata__namespace="other", status__state=ApplicationState.RUNNING
        ),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 200

    body = await resp.json()
    received = ApplicationList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources[:-1], key=key)


async def test_list_applications_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "list"):
        resp = await client.get("/kubernetes/namespaces/testing/applications")
        assert resp.status == 200


async def test_watch_applications(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]

    async def watch(created):
        resp = await client.get(
            "/kubernetes/namespaces/testing/applications?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Application.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Applications
        for data in resources:
            resp = await client.post(
                f"/kubernetes/namespaces/{data.metadata.namespace}/applications",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/applications/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Application.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_all_applications(aiohttp_client, config, db):
    resources = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/applications")
    assert resp.status == 200

    body = await resp.json()
    received = ApplicationList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_all_applications_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "list"):
        resp = await client.get("/kubernetes/applications")
        assert resp.status == 200


async def test_watch_all_applications(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        ApplicationFactory(metadata__namespace="testing"),
        ApplicationFactory(metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get("/kubernetes/applications?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Application.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Applications
        for data in resources:
            resp = await client.post(
                "/kubernetes/namespaces/testing/applications", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/applications/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Application.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_application(aiohttp_client, config, db):
    data = ApplicationFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}"
    )

    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received == data


async def test_read_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/namespaces/testing/applications/my-resource")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "get"):
        resp = await client.get(
            "/kubernetes/namespaces/testing/applications/my-resource"
        )
        assert resp.status == 404


async def test_add_finalizer_in_deleted_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )
