import asyncio
import json
import pytz
from itertools import count
from operator import attrgetter

from krake.api.app import create_app
from krake.api.helpers import HttpReason, HttpReasonCode
from krake.data.core import WatchEventType, WatchEvent, resource_ref
from krake.data.kubernetes import Cluster, Application, ClusterList, ApplicationList


from tests.factories.kubernetes import ClusterFactory, ApplicationFactory

from tests.factories.fake import fake


async def test_create_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Resource-specific elements can be set here
    data = ApplicationFactory()

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    # MISSING The resource-specific attributes can be verified here.
    # assert received.spec == data.spec

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/applications")
        assert resp.status == 415


async def test_create_application_with_existing_name(aiohttp_client, config, db):
    existing = ApplicationFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    reason = HttpReason.deserialize(received)
    assert reason.code == HttpReasonCode.RESOURCE_ALREADY_EXISTS


async def test_delete_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Resource-specific elements can be set here
    data = ApplicationFactory()
    await db.put(data)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


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
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete(
        "/kubernetes/namespaces/testing/applications/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "delete"):
        resp = await client.delete(
            "/kubernetes/namespaces/testing/applications/my-resource"
        )
        assert resp.status == 404


async def test_delete_application_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = ApplicationFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_applications(aiohttp_client, config, db):
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
    # MISSING Resource-specific elements can be set here
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
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[1].spec
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
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
    # MISSING Resource-specific elements can be set here
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
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[1].spec
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
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


async def test_update_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Resource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)
    # MISSING The resource-specific attributes can be updated here
    # data.spec.foo = bar

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    # MISSING Assertions on resource-specific received values.
    # assert received.spec.foo == bar

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the Application
    data.metadata.finalizers = []
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The Application should be deleted from the database
    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored is None


async def test_update_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/kubernetes/namespaces/testing/applications/my-resource")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource"
        )
        assert resp.status == 415


async def test_update_application_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory()
    await db.put(data)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_application_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Subresource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.binding.foo = bar

    binding = ClusterBinding()

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/binding",
        json=binding.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Application"

    # MISSING Assertions on subresource-specific received values.
    # assert received.binding.foo == bar

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received
    # MISSING Assertions on subresource-specific updated values.
    # assert received.binding == data.binding
    # assert received.binding.foo == bar


async def test_update_application_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/applications/my-resource/binding"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/binding", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource/binding"
        )
        assert resp.status == 415


async def test_update_application_complete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Subresource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.complete.foo = bar

    complete = ApplicationComplete()

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/complete",
        json=complete.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Application"

    # MISSING Assertions on subresource-specific received values.
    # assert received.complete.foo == bar

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received
    # MISSING Assertions on subresource-specific updated values.
    # assert received.complete == data.complete
    # assert received.complete.foo == bar


async def test_update_application_complete_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/applications/my-resource/complete"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/complete", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource/complete"
        )
        assert resp.status == 415


async def test_update_application_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Subresource-specific attributes can be set here
    data = ApplicationFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.status.foo = bar

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Application"

    # MISSING Assertions on subresource-specific received values.
    # assert received.status.foo == bar

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received
    # MISSING Assertions on subresource-specific updated values.
    # assert received.status == data.status
    # assert received.status.foo == bar


async def test_update_application_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/applications/my-resource/status"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/status", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource/status"
        )
        assert resp.status == 415


async def test_create_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Resource-specific elements can be set here
    data = ClusterFactory()

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters", json=data.serialize()
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    # MISSING The resource-specific attributes can be verified here.
    # assert received.spec == data.spec

    stored = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/clusters")
        assert resp.status == 415


async def test_create_cluster_with_existing_name(aiohttp_client, config, db):
    existing = ClusterFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    reason = HttpReason.deserialize(received)
    assert reason.code == HttpReasonCode.RESOURCE_ALREADY_EXISTS


async def test_delete_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Resource-specific elements can be set here
    data = ClusterFactory()
    await db.put(data)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ClusterFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/kubernetes/namespaces/testing/clusters/my-resource")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "delete"):
        resp = await client.delete(
            "/kubernetes/namespaces/testing/clusters/my-resource"
        )
        assert resp.status == 404


async def test_delete_cluster_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = ClusterFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_clusters(aiohttp_client, config, db):
    resources = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 200

    body = await resp.json()
    received = ClusterList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources[:-1], key=key)


async def test_list_clusters_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "list"):
        resp = await client.get("/kubernetes/namespaces/testing/clusters")
        assert resp.status == 200


async def test_watch_clusters(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    # MISSING Resource-specific elements can be set here
    resources = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]

    async def watch(created):
        resp = await client.get(
            "/kubernetes/namespaces/testing/clusters?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Cluster.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[1].spec
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Clusters
        for data in resources:
            resp = await client.post(
                f"/kubernetes/namespaces/{data.metadata.namespace}/clusters",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/clusters/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Cluster.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_all_clusters(aiohttp_client, config, db):
    resources = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/clusters")
    assert resp.status == 200

    body = await resp.json()
    received = ClusterList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_all_clusters_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "list"):
        resp = await client.get("/kubernetes/clusters")
        assert resp.status == 200


async def test_watch_all_clusters(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    # MISSING Resource-specific elements can be set here
    resources = [
        ClusterFactory(metadata__namespace="testing"),
        ClusterFactory(metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get("/kubernetes/clusters?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Cluster.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[1].spec
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                # MISSING The resource-specific attributes can be verified here.
                # assert data.spec == resources[0].spec
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Clusters
        for data in resources:
            resp = await client.post(
                "/kubernetes/namespaces/testing/clusters", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/clusters/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Cluster.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_cluster(aiohttp_client, config, db):
    data = ClusterFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())
    assert received == data


async def test_read_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/namespaces/testing/clusters/my-resource")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "get"):
        resp = await client.get("/kubernetes/namespaces/testing/clusters/my-resource")
        assert resp.status == 404


async def test_update_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Resource-specific attributes can be set here
    data = ClusterFactory()
    await db.put(data)
    # MISSING The resource-specific attributes can be updated here
    # data.spec.foo = bar

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert data.metadata.modified < received.metadata.modified
    # MISSING Assertions on resource-specific received values.
    # assert received.spec.foo == bar

    stored = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_cluster_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the Cluster
    data.metadata.finalizers = []
    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The Cluster should be deleted from the database
    stored = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored is None


async def test_update_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/kubernetes/namespaces/testing/clusters/my-resource")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "update"):
        resp = await client.put("/kubernetes/namespaces/testing/clusters/my-resource")
        assert resp.status == 415


async def test_update_cluster_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ClusterFactory()
    await db.put(data)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_cluster_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Subresource-specific attributes can be set here
    data = ClusterFactory()
    await db.put(data)

    # MISSING The subresource-specific attributes can be updated here
    # data.status.foo = bar

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Cluster"

    # MISSING Assertions on subresource-specific received values.
    # assert received.status.foo == bar

    stored = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == received
    # MISSING Assertions on subresource-specific updated values.
    # assert received.status == data.status
    # assert received.status.foo == bar


async def test_update_cluster_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/clusters/my-resource/status"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters/status", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/clusters/my-resource/status"
        )
        assert resp.status == 415

