import asyncio
import re
import json
from itertools import count
from operator import attrgetter

from krake.data.core import ReasonCode
from krake.data.kubernetes import (
    Application,
    ApplicationState,
    ApplicationStatus,
    ClusterBinding,
    Cluster,
    ClusterState,
)
from krake.data import serialize, deserialize
from krake.data.core import Conflict, resource_ref
from krake.api.app import create_app

from factories.kubernetes import ApplicationFactory, ClusterFactory
from tests.factories.core import ReasonFactory

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
        ApplicationFactory(status__state=ApplicationState.DELETED),
        ApplicationFactory(
            metadata__namespace="system", status__state=ApplicationState.RUNNING
        ),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps) - 2

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(apps[:-2], key=key)


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
    resp = await client.get("/kubernetes/namespaces/all/applications")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps)

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(apps, key=key)


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
        "/kubernetes/namespaces/testing/applications", json=serialize(data)
    )
    assert resp.status == 200
    app = deserialize(Application, await resp.json())

    assert app.status.state == ApplicationState.PENDING
    assert app.status.created
    assert app.status.modified
    assert app.spec == data.spec

    stored, _ = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == app


async def test_create_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/applications")
        assert resp.status == 422


async def test_create_app_in_all_namespace(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))
    data = ApplicationFactory(metadata__name="all")

    resp = await client.post(
        "/kubernetes/namespaces/all/applications", json=serialize(data)
    )
    assert resp.status == 400


async def test_create_app_with_existing_name(aiohttp_client, config, db):
    existing = ApplicationFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=serialize(existing)
    )
    assert resp.status == 400


async def test_get_app(aiohttp_client, config, db):
    app = ApplicationFactory(status__state=ApplicationState.RUNNING)
    await db.put(app)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}"
    )
    assert resp.status == 200
    data = deserialize(Application, await resp.json())
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
        json=serialize(data),
    )
    assert resp.status == 200
    app = deserialize(Application, await resp.json())

    assert app.status.state == ApplicationState.UPDATED
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
        assert resp.status == 422


async def test_update_app_already_deleted(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create applications
    deleting = ApplicationFactory(status__state=ApplicationState.DELETING)
    deleted = ApplicationFactory(status__state=ApplicationState.DELETED)
    await db.put(deleting)
    await db.put(deleted)

    deleting.spec.manifest = new_manifest
    deleted.spec.manifest = new_manifest

    # Update already deleting application
    resp = await client.put(
        f"/kubernetes/namespaces/{deleting.metadata.namespace}"
        f"/applications/{deleting.metadata.name}",
        json=serialize(deleting),
    )
    assert resp.status == 400

    # Update already deleted application
    resp = await client.put(
        f"/kubernetes/namespaces/{deleted.metadata.namespace}"
        f"/applications/{deleted.metadata.name}",
        json=serialize(deleted),
    )
    assert resp.status == 400


async def test_update_app_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    await db.put(app)

    reason = ReasonFactory()

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/status",
        json={
            "state": "FAILED",
            "reason": serialize(reason),
            "cluster": "/kubernetes/namespaces/testing/clusters/test-cluster",
            "services": {"service1": "127.0.0.1:38531"},
        },
    )
    assert resp.status == 200
    status = deserialize(ApplicationStatus, await resp.json())

    assert status.state == ApplicationState.FAILED
    assert status.created == app.status.created
    assert status.reason == reason
    assert status.cluster == "/kubernetes/namespaces/testing/clusters/test-cluster"
    assert status.services == {"service1": "127.0.0.1:38531"}

    stored, rev = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status == status
    assert rev.version == 2


async def test_update_app_status_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.put("/kubernetes/namespaces/testing/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "update"):
        resp = await client.put("/kubernetes/namespaces/testing/applications/myapp")
        assert resp.status == 422


async def test_update_app_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)
    cluster = ClusterFactory()

    assert app.status.cluster is None, "Application is not scheduled"

    await db.put(app)
    await db.put(cluster)

    cluster_ref = (
        f"/kubernetes/namespaces/{cluster.metadata.namespace}"
        f"/clusters/{cluster.metadata.name}"
    )
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/binding",
        json={"cluster": cluster_ref},
    )
    assert resp.status == 200
    binding = deserialize(ClusterBinding, await resp.json())

    assert binding.cluster == cluster_ref

    updated, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert updated.status.cluster == cluster_ref
    assert updated.status.state == ApplicationState.SCHEDULED


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
    assert resp.status == 200

    deleted, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert deleted.status.state == ApplicationState.DELETING


async def test_delete_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/kubernetes/namespaces/testing/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "delete"):
        resp = await client.delete("/kubernetes/namespaces/testing/applications/myapp")
        assert resp.status == 404


async def test_delete_already_deleted(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create applications
    deleting = ApplicationFactory(status__state=ApplicationState.DELETING)
    deleted = ApplicationFactory(status__state=ApplicationState.DELETED)
    await db.put(deleting)
    await db.put(deleted)

    # Delete already deleting application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{deleting.metadata.name}"
    )
    assert resp.status == 304

    # Delete already deleted application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{deleted.metadata.name}"
    )
    assert resp.status == 304


async def test_watch_app(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))

    async def watch(created):
        resp = await client.get(
            "/kubernetes/namespaces/testing/applications?watch&heartbeat=0"
        )
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexecpted EOF"

            data = json.loads(line.decode())
            assert uuid_re.match(data["metadata"]["uid"])

            if i == 0:
                assert data["status"]["state"] == "PENDING"
            elif i == 1:
                assert data["status"]["state"] == "PENDING"
            elif i == 2:
                assert data["status"]["state"] == "DELETING"
                return

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications
        for i in range(2):
            app = ApplicationFactory(status=None, metadata__name=f"test-app-{i}")
            resp = await client.post(
                "/kubernetes/namespaces/testing/applications", json=serialize(app)
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/applications/{app.metadata.name}"
        )
        assert resp.status == 200

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_watch_app_from_all_namespaces(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))

    async def watch(created):
        resp = await client.get(
            "/kubernetes/namespaces/all/applications?watch&heartbeat=0"
        )
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexecpted EOF"

            data = json.loads(line.decode())
            assert uuid_re.match(data["metadata"]["uid"])

            if i == 0:
                assert data["status"]["state"] == "PENDING"
            elif i == 1:
                assert data["status"]["state"] == "PENDING"
                return

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications in different namespaces
        for i, namespace in enumerate(["testing", "system"]):
            app = ApplicationFactory(
                status=None,
                metadata__name=f"test-app-{i}",
                metadata__namespace=namespace,
            )
            resp = await client.post(
                f"/kubernetes/namespaces/{namespace}/applications", json=serialize(app)
            )
            assert resp.status == 200

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_clusters(aiohttp_client, config, db):
    clusters = [
        ClusterFactory(status__state=ClusterState.RUNNING),
        ClusterFactory(status__state=ClusterState.RUNNING),
        ClusterFactory(status__state=ClusterState.PENDING),
    ]
    for cluster in clusters:
        await db.put(cluster)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Cluster, item) for item in data]

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(clusters, key=key)


async def test_list_clusters_from_all_namespaces(aiohttp_client, config, db):
    clusters = [
        ClusterFactory(status__state=ClusterState.RUNNING),
        ClusterFactory(status__state=ClusterState.RUNNING),
        ClusterFactory(status__state=ClusterState.PENDING),
        ClusterFactory(
            metadata__namespace="system", status__state=ClusterState.RUNNING
        ),
    ]
    for cluster in clusters:
        await db.put(cluster)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/all/clusters")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Cluster, item) for item in data]

    assert len(received) == len(clusters)

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(clusters, key=key)


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
        json=serialize(data),
    )
    assert resp.status == 200
    cluster = deserialize(Cluster, await resp.json())

    assert cluster.status.created
    assert cluster.status.modified
    assert cluster.status.state == ClusterState.RUNNING
    assert cluster.spec == data.spec

    stored, _ = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == cluster


async def test_create_clusters_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/clusters")
        assert resp.status == 422


async def test_create_cluster_in_all_namespace(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(metadata__namespace="all")

    resp = await client.post(
        "/kubernetes/namespaces/all/clusters", json=serialize(data)
    )
    assert resp.status == 400


async def test_create_invalid_cluster(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(spec__kubeconfig={"invalid": "kubeconfig"})

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters", json=serialize(data)
    )
    assert resp.status == 400


async def test_update_cluster_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    running = ClusterFactory(status__state=ClusterState.RUNNING)
    deleted = ClusterFactory(status__state=ClusterState.DELETING)

    await db.put(running)
    await db.put(deleted)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{running.metadata.name}/status",
        json={
            "state": "FAILED",
            "reason": "Stupid error",
            "cluster": "/kubernetes/namespaces/testing/clusters/test-cluster",
        },
    )
    assert resp.status == 304

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{deleted.metadata.name}/status",
        json={
            "state": "DELETED",
            "reason": "App has been deleted",
            "cluster": "/kubernetes/namespaces/testing/clusters/test-cluster",
        },
    )
    assert resp.status == 200

    stored, rev = await db.get(Cluster, namespace="testing", name=running.metadata.name)
    assert stored.status.created == running.status.created
    assert stored.status.reason is None
    assert rev.version == 1

    stored, _ = await db.get(Cluster, namespace="testing", name=deleted.metadata.name)
    assert stored is None


async def test_update_delete_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    cluster = ClusterFactory(status__state=ClusterState.RUNNING)
    await db.put(cluster)

    # Delete application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}"
    )
    assert resp.status == 200

    deleted, rev = await db.get(
        Application, namespace="testing", name=cluster.metadata.name
    )
    assert deleted is None
    assert rev is None


async def test_delete_cluster_with_apps(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    cluster = ClusterFactory(status__state=ClusterState.RUNNING)
    cluster_ref = (
        f"/kubernetes/namespaces/{cluster.metadata.namespace}"
        f"/clusters/{cluster.metadata.name}"
    )
    cluster_resource_ref = resource_ref(cluster)

    running = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__cluster=cluster_ref
    )
    running_res_ref = resource_ref(running)
    deleting = ApplicationFactory(
        status__state=ApplicationState.DELETING, status__cluster=cluster_ref
    )

    await db.put(cluster)
    await db.put(running)
    await db.put(deleting)

    # Try to delete application, conflict
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}"
    )
    assert resp.status == 409
    conflict = deserialize(Conflict, await resp.json())

    assert conflict.source == cluster_resource_ref
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

    # Force deletion
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}?cascade"
    )
    assert resp.status == 200

    deleting, rev = await db.get(
        Cluster, namespace="testing", name=cluster.metadata.name
    )
    assert deleting.status.state == ClusterState.DELETING


async def test_delete_cluster_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/kubernetes/namespaces/testing/clusters/my-cluster")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "delete"):
        resp = await client.delete("/kubernetes/namespaces/testing/clusters/my-cluster")
        assert resp.status == 404


async def test_delete_cluster_already_deleted(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create applications
    deleting = ClusterFactory(status__state=ClusterState.DELETING)
    deleted = ClusterFactory(status__state=ClusterState.DELETED)
    await db.put(deleting)
    await db.put(deleted)

    # Delete already deleting application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{deleting.metadata.name}"
    )
    assert resp.status == 304

    # Delete already deleted application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{deleted.metadata.name}"
    )
    assert resp.status == 304
