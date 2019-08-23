import asyncio
import re
import json
from itertools import count
from operator import attrgetter

from krake.data.core import (
    WatchEvent,
    WatchEventType,
    ResourceRef,
    resource_ref,
    Conflict,
)
from krake.data.kubernetes import (
    Application,
    ApplicationList,
    ApplicationState,
    ClusterBinding,
    Cluster,
    ClusterList,
    ClusterState,
)
from krake.api.app import create_app

from factories.kubernetes import ApplicationFactory, ClusterFactory
from tests.factories.core import ReasonFactory
from factories.fake import fake


uuid_re = re.compile(
    r"^[0-9A-F]{8}-[0-9A-F]{4}-[4][0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$",
    re.IGNORECASE,
)


async def test_list_apps(aiohttp_client, config, db):
    apps = [
        ApplicationFactory(status__state=ApplicationState.PENDING),
        ApplicationFactory(status__state=ApplicationState.SCHEDULED),
        ApplicationFactory(status__state=ApplicationState.UPDATED),
        ApplicationFactory(status__state=ApplicationState.DELETING),
        ApplicationFactory(
            metadata__namespace="system", status__state=ApplicationState.RUNNING
        ),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 200

    body = await resp.json()
    received = ApplicationList.deserialize(body)

    assert len(received.items) == len(apps) - 1

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(apps[:-1], key=key)


async def test_list_apps_from_all_namespaces(aiohttp_client, config, db):
    apps = [
        ApplicationFactory(status__state=ApplicationState.RUNNING),
        ApplicationFactory(status__state=ApplicationState.RUNNING),
        ApplicationFactory(status__state=ApplicationState.RUNNING),
        ApplicationFactory(
            metadata__namespace="sytem", status__state=ApplicationState.RUNNING
        ),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/applications")
    assert resp.status == 200

    body = await resp.json()
    received = ApplicationList.deserialize(body)

    assert len(received.items) == len(apps)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(apps, key=key)


async def test_list_apps_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "list"):
        resp = await client.get("/kubernetes/namespaces/testing/applications")
        assert resp.status == 200


async def test_create_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ApplicationFactory(status=None)

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications",
        json=data.serialize(subresources=set()),
    )
    assert resp.status == 200
    app = Application.deserialize(await resp.json())

    assert app.metadata.created
    assert app.metadata.modified
    assert app.spec == data.spec
    assert app.status.state == ApplicationState.PENDING

    stored, _ = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == app


async def test_create_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/applications")
        assert resp.status == 415


async def test_create_app_with_existing_name(aiohttp_client, config, db):
    existing = ApplicationFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=existing.serialize()
    )
    assert resp.status == 409


async def test_get_app(aiohttp_client, config, db):
    app = ApplicationFactory(status__state=ApplicationState.RUNNING)
    await db.put(app)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}"
    )
    assert resp.status == 200
    data = Application.deserialize(await resp.json())
    assert app == data


async def test_get_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/kubernetes/namespaces/testing/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "get"):
        resp = await client.get("/kubernetes/namespaces/testing/applications/myapp")
        assert resp.status == 404


new_manifest = """
apiVersion: v1
kind: Pod
metadata:
  name: busybox-sleep
spec:
  containers:
  - name: busybox
    image: busybox
    args:
    - sleep
    - "1000000"
---
apiVersion: v1
kind: Pod
metadata:
  name: busybox-sleep-less
spec:
  containers:
  - name: busybox
    image: busybox
    args:
    - sleep
    - "1000"
"""


async def test_update_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(data)
    data.spec.manifest = new_manifest

    resp = await client.put(
        f"/kubernetes/namespaces/{data.metadata.namespace}"
        f"/applications/{data.metadata.name}",
        json=data.serialize(subresources=set(), readonly=False),
    )
    assert resp.status == 200
    app = Application.deserialize(await resp.json())

    assert app.status.state == data.status.state
    assert app.spec.manifest == new_manifest

    stored, _ = await db.get(
        Application, namespace=data.metadata.namespace, name=app.metadata.name
    )
    assert stored == app


async def test_update_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.put("/kubernetes/namespaces/testing/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "update"):
        resp = await client.put("/kubernetes/namespaces/testing/applications/myapp")
        assert resp.status == 415


async def test_update_app_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    await db.put(app)

    app.status.state = ApplicationState.FAILED
    app.status.reason = ReasonFactory()
    app.status.cluster = ResourceRef(
        api="kubernetes", kind="Cluster", namespace="testing", name="test-cluster"
    )
    app.status.services = {"service1": "127.0.0.1:38531"}

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/status",
        json=app.serialize(subresources={"status"}, readonly=False),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received.metadata == app.metadata
    assert received.status == app.status

    stored, rev = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status == received.status
    assert rev.version == 2


async def test_update_app_status_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.put("/kubernetes/namespaces/testing/applications/myapp/status")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/status", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/myapp/status"
        )
        assert resp.status == 415


async def test_update_app_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)
    cluster = ClusterFactory()

    assert app.status.cluster is None, "Application is not scheduled"

    await db.put(app)
    await db.put(cluster)

    cluster_ref = resource_ref(cluster)
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/binding",
        json=ClusterBinding(cluster=cluster_ref).serialize(),
    )
    assert resp.status == 200
    body = await resp.json()
    received = Application.deserialize(body)
    received.status.cluster == cluster_ref
    received.status.state == ApplicationState.SCHEDULED

    stored, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.cluster == cluster_ref
    assert stored.status.state == ApplicationState.SCHEDULED


async def test_delete_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(app)

    # Delete application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}"
    )
    assert resp.status == 204

    deleted, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert deleted is None


async def test_delete_app_with_finalizers(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING, metadata__finalizers=["test-finializer"]
    )
    await db.put(app)

    # Delete application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}"
    )
    assert resp.status == 200

    received = Application.deserialize(await resp.json())
    assert received.metadata.deleted

    stored, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.metadata.deleted


async def test_add_finializer_in_deleted_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    app = ApplicationFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(app)

    app.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/kubernetes/namespaces/{app.metadata.namespace}"
        f"/applications/{app.metadata.name}",
        json=app.serialize(subresources=set(), readonly=False),
    )
    assert resp.status == 422
    body = await resp.json()
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/kubernetes/namespaces/testing/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "delete"):
        resp = await client.delete("/kubernetes/namespaces/testing/applications/myapp")
        assert resp.status == 404


async def test_delete_already_deleting(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create applications
    deleting = ApplicationFactory(metadata__deleted=fake.date_time())
    await db.put(deleting)

    # Delete already deleting application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{deleting.metadata.name}"
    )
    assert resp.status == 200


async def test_watch_app(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    apps = [ApplicationFactory(status=None), ApplicationFactory(status=None)]

    async def watch(created):
        resp = await client.get(
            "/kubernetes/namespaces/testing/applications?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexecpted EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            app = Application.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert app.metadata.name == apps[0].metadata.name
                assert app.spec == apps[0].spec
                assert app.status.state == ApplicationState.PENDING
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert app.metadata.name == apps[1].metadata.name
                assert app.spec == apps[1].spec
                assert app.status.state == ApplicationState.PENDING
            elif i == 2:
                assert event.type == WatchEventType.DELETED
                assert app.metadata.name == apps[0].metadata.name
                assert app.spec == apps[0].spec
                assert app.status.state == ApplicationState.PENDING
                return

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications
        for app in apps:
            resp = await client.post(
                "/kubernetes/namespaces/testing/applications",
                json=app.serialize(subresources=set(), readonly=False),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/applications/{apps[0].metadata.name}"
        )
        assert resp.status == 204

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_watch_app_from_all_namespaces(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))

    apps = [
        ApplicationFactory(status=None, metadata__namespace="testing"),
        ApplicationFactory(status=None, metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get("/kubernetes/applications?watch&heartbeat=0")
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexecpted EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            app = Application.deserialize(event.object)

            assert event.type == WatchEventType.ADDED
            assert app.metadata.name == apps[i].metadata.name
            assert app.spec == apps[i].spec

            if i == 1:
                return

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications in different namespaces
        for app in apps:
            resp = await client.post(
                f"/kubernetes/namespaces/{app.metadata.namespace}/applications",
                json=app.serialize(subresources=set(), readonly=False),
            )
            assert resp.status == 200

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_clusters(aiohttp_client, config, db):
    clusters = [ClusterFactory(), ClusterFactory(), ClusterFactory()]
    for cluster in clusters:
        await db.put(cluster)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 200

    body = await resp.json()
    received = ClusterList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(clusters, key=key)


async def test_list_clusters_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "list"):
        resp = await client.get("/kubernetes/namespaces/testing/clusters")
        assert resp.status == 200


async def test_create_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(status=None)

    resp = await client.post(
        f"/kubernetes/namespaces/{data.metadata.namespace}/clusters",
        json=data.serialize(subresources=set(), readonly=False),
    )
    assert resp.status == 200
    cluster = Cluster.deserialize(await resp.json())

    assert cluster.metadata.created
    assert cluster.metadata.modified
    assert cluster.spec == data.spec

    stored, _ = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == cluster


async def test_create_clusters_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/clusters")
        assert resp.status == 415


async def test_create_invalid_cluster(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(spec__kubeconfig={"invalid": "kubeconfig"})

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters",
        json=data.serialize(subresources=set(), readonly=False),
    )
    assert resp.status == 422


async def test_update_cluster_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    cluster = ClusterFactory(status__state=ClusterState.RUNNING)

    await db.put(cluster)

    cluster.status.state = ClusterState.FAILED
    cluster.status.reason = ReasonFactory()
    cluster.status.cluster = ResourceRef(
        api="kubernetes", kind="Cluster", namespace="testing", name="test-cluster"
    )
    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}/status",
        json=cluster.serialize(subresources={"status"}),
    )
    assert resp.status == 200

    stored, rev = await db.get(Cluster, namespace="testing", name=cluster.metadata.name)
    assert stored.status == cluster.status


async def test_update_cluster_status_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.put("/kubernetes/namespaces/testing/clusters/mycluster/status")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters/status", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/clusters/mycluster/status"
        )
        assert resp.status == 415


async def test_delete_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    cluster = ClusterFactory(status__state=ClusterState.RUNNING)
    await db.put(cluster)

    # Delete application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}"
    )
    assert resp.status == 204

    deleted, rev = await db.get(
        Application, namespace="testing", name=cluster.metadata.name
    )
    assert deleted is None
    assert rev is None


async def test_delete_cluster_with_finalizers(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    client = await aiohttp_client(create_app(config=config))
    cluster = ClusterFactory(metadata__finalizers=["test-finializer"])
    await db.put(cluster)

    # Delete application
    resp = await client.delete(
        f"/kubernetes/namespaces/{cluster.metadata.namespace}"
        f"/clusters/{cluster.metadata.name}"
    )
    assert resp.status == 200

    received = Cluster.deserialize(await resp.json())
    assert received.metadata.deleted

    stored, _ = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.metadata.deleted


async def test_delete_cluster_with_apps(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    cluster = ClusterFactory(status__state=ClusterState.RUNNING)
    cluster_ref = resource_ref(cluster)

    running = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__cluster=cluster_ref
    )
    running_res_ref = resource_ref(running)
    deleting = ApplicationFactory(
        metadata__deleted=fake.date_time(),
        status__state=ApplicationState.DELETING,
        status__cluster=cluster_ref,
    )

    await db.put(cluster)
    await db.put(running)
    await db.put(deleting)

    # Try to delete application, conflict
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}"
    )
    assert resp.status == 409
    body = await resp.json()
    conflict = Conflict.deserialize(body)

    assert conflict.source == cluster_ref
    assert len(conflict.conflicting) == 1
    assert conflict.conflicting[0] == running_res_ref

    stored_cluster, rev = await db.get(
        Cluster, namespace="testing", name=cluster.metadata.name
    )
    assert stored_cluster == cluster

    stored_app, rev = await db.get(
        Application, namespace="testing", name=running.metadata.name
    )
    assert stored_app == running

    # Cascade deletion
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}?cascade"
    )
    assert resp.status == 200

    body = await resp.json()
    received = Cluster.deserialize(body)
    assert received.metadata.deleted
    assert received.metadata.finalizers[0] == "cascading_deletion"

    stored, _ = await db.get(Cluster, namespace="testing", name=cluster.metadata.name)
    assert stored == received


async def test_delete_cluster_already_deleting(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    deleting = ClusterFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["sticky"]
    )
    await db.put(deleting)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{deleting.metadata.name}"
    )
    assert resp.status == 200


async def test_delete_cluster_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/kubernetes/namespaces/testing/clusters/my-cluster")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "delete"):
        resp = await client.delete("/kubernetes/namespaces/testing/clusters/my-cluster")
        assert resp.status == 404
