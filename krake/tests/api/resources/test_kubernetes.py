import pytest
import asyncio
import re
import json
from itertools import count
from operator import attrgetter
import yaml

from krake.data.kubernetes import (
    Application,
    ApplicationState,
    ApplicationStatus,
    ClusterBinding,
    Cluster,
    ClusterState,
)
from krake.data import deserialize
from krake.api.app import create_app

from factories.kubernetes import ApplicationFactory, ClusterFactory


uuid_re = re.compile(
    r"^[0-9A-F]{8}-[0-9A-F]{4}-[4][0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$",
    re.IGNORECASE,
)

manifest = """---
apiVersion: v1
kind: Service
metadata:
  name: wordpress-mysql
  labels:
    app: wordpress
spec:
  ports:
    - port: 3306
  selector:
    app: wordpress
    tier: mysql
  clusterIP: None
"""


kubeconfig = """
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: REMOVED
    server: https://127.0.0.1:8443
  name: test-cluster
contexts:
- context:
    cluster: test-cluster
    user: test-user
  name: test-context
current-context: "test-context"
kind: Config
preferences: {}
users:
- name: test-user
  user:
    client-certificate-data: REMOVED
    client-key-data: REMOVED
"""


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
    resp = await client.get("/namespaces/testing/kubernetes/applications")
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
    resp = await client.get("/namespaces/all/kubernetes/applications")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps)

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(apps, key=key)


async def test_list_deleted_apps(aiohttp_client, config, db):
    apps = [
        ApplicationFactory(status__state=ApplicationState.PENDING),
        ApplicationFactory(status__state=ApplicationState.DELETED),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/namespaces/testing/kubernetes/applications?deleted")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps)

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(apps, key=key)


async def test_list_apps_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/namespaces/testing/kubernetes/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes/applications", "list"):
        resp = await client.get("/namespaces/testing/kubernetes/applications")
        assert resp.status == 200


async def test_create_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/namespaces/testing/kubernetes/applications",
        json={"manifest": manifest, "name": "test-app"},
    )
    assert resp.status == 200
    data = await resp.json()

    assert uuid_re.match(data["metadata"]["uid"]) is not None

    app, rev = await db.get(
        Application, namespace="testing", name=data["metadata"]["name"]
    )
    assert rev.version == 1
    assert app.status.state == ApplicationState.PENDING
    assert app.spec.manifest == manifest


async def test_create_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/namespaces/testing/kubernetes/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes/applications", "create"):
        resp = await client.post("/namespaces/testing/kubernetes/applications")
        assert resp.status == 422


async def test_create_app_in_all_namespace(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/namespaces/all/kubernetes/applications",
        json={"manifest": manifest, "name": "test-app"},
    )
    assert resp.status == 400


async def test_create_invalid_app(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/namespaces/testing/kubernetes/applications", json={"manifest": None}
    )
    assert resp.status == 422
    data = await resp.json()

    assert data["manifest"]


async def test_create_app_with_existing_name(aiohttp_client, config, db):
    existing = ApplicationFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/namespaces/testing/kubernetes/applications",
        json={"manifest": manifest, "name": "existing"},
    )
    assert resp.status == 400


async def test_get_app(aiohttp_client, config, db):
    app = ApplicationFactory(status__state=ApplicationState.RUNNING)
    await db.put(app)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}"
    )
    assert resp.status == 200
    data = deserialize(Application, await resp.json())
    assert app == data


async def test_get_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/namespaces/testing/kubernetes/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes/applications", "get"):
        resp = await client.get("/namespaces/testing/kubernetes/applications/myapp")
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
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    await db.put(app)

    resp = await client.put(
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}",
        json={"manifest": new_manifest},
    )
    assert resp.status == 200
    data = await resp.json()

    assert data["spec"]["manifest"] == new_manifest

    stored, rev = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.spec.manifest == new_manifest
    assert rev.version == 2


async def test_update_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.put("/namespaces/testing/kubernetes/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes/applications", "update"):
        resp = await client.put("/namespaces/testing/kubernetes/applications/myapp")
        assert resp.status == 422


async def test_update_app_already_deleted(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create applications
    deleting = ApplicationFactory(status__state=ApplicationState.DELETING)
    deleted = ApplicationFactory(status__state=ApplicationState.DELETED)
    await db.put(deleting)
    await db.put(deleted)

    # Update already deleting application
    resp = await client.put(
        f"/namespaces/testing/kubernetes/applications/{deleting.metadata.name}",
        json={"manifest": new_manifest},
    )
    assert resp.status == 400

    # Update already deleted application
    resp = await client.put(
        f"/namespaces/testing/kubernetes/applications/{deleted.metadata.name}",
        json={"manifest": new_manifest},
    )
    assert resp.status == 400


async def test_update_app_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    await db.put(app)

    resp = await client.put(
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}/status",
        json={
            "state": "FAILED",
            "reason": "Stupid error",
            "cluster": "/namespaces/testing/kubernetes/clusters/test-cluster",
        },
    )
    assert resp.status == 200
    status = deserialize(ApplicationStatus, await resp.json())

    assert status.state == ApplicationState.FAILED
    assert status.created == app.status.created
    assert status.reason == "Stupid error"
    assert status.cluster == "/namespaces/testing/kubernetes/clusters/test-cluster"

    stored, rev = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status == status
    assert rev.version == 2


async def test_update_app_status_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.put("/namespaces/testing/kubernetes/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes/applications", "update"):
        resp = await client.put("/namespaces/testing/kubernetes/applications/myapp")
        assert resp.status == 422


async def test_update_app_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)
    cluster = ClusterFactory()

    assert app.spec.cluster is None, "Application is not scheduled"

    await db.put(app)
    await db.put(cluster)

    cluster_ref = f"/namespaces/{cluster.metadata.namespace}/kubernetes/clusters/{cluster.metadata.name}"
    resp = await client.put(
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}/binding",
        json={"cluster": cluster_ref},
    )
    assert resp.status == 200
    binding = deserialize(ClusterBinding, await resp.json())

    assert binding.cluster == cluster_ref

    updated, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert updated.spec.cluster == cluster_ref
    assert updated.status.state == ApplicationState.SCHEDULED


async def test_delete_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(app)

    # Delete application
    resp = await client.delete(
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}"
    )
    assert resp.status == 200

    deleted, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert deleted.status.state == ApplicationState.DELETING
    assert deleted.spec.manifest == manifest


async def test_delete_app_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/namespaces/testing/kubernetes/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes/applications", "delete"):
        resp = await client.delete("/namespaces/testing/kubernetes/applications/myapp")
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
        f"/namespaces/testing/kubernetes/applications/{deleting.metadata.name}"
    )
    assert resp.status == 304

    # Delete already deleted application
    resp = await client.delete(
        f"/namespaces/testing/kubernetes/applications/{deleted.metadata.name}"
    )
    assert resp.status == 304


async def test_watch_app(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))

    async def watch(created, received):
        resp = await client.get(
            "/namespaces/testing/kubernetes/applications?watch&heartbeat=0"
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
                received.set_result(None)

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications
        for i in range(2):
            resp = await client.post(
                "/namespaces/testing/kubernetes/applications",
                json={"manifest": manifest, "name": f"test-app-{i}"},
            )
            assert resp.status == 200

        data = await resp.json()
        resp = await client.delete(
            f'/namespaces/testing/kubernetes/applications/{data["metadata"]["name"]}'
        )
        assert resp.status == 200

    created = loop.create_future()
    received = loop.create_future()
    watching = loop.create_task(watch(created, received))
    modifying = loop.create_task(modify(created))

    await modifying
    assert received.done(), "Not all changes were propagated"

    # Stop watcher
    watching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watching


async def test_watch_app_from_all_namespaces(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))

    async def watch(created, received):
        resp = await client.get(
            "/namespaces/all/kubernetes/applications?watch&heartbeat=0"
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
                received.set_result(None)

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications in different namespaces
        for i, namespace in enumerate(["testing", "system"]):
            resp = await client.post(
                f"/namespaces/{namespace}/kubernetes/applications",
                json={"manifest": manifest, "name": f"test-app-{i}"},
            )
            assert resp.status == 200

    created = loop.create_future()
    received = loop.create_future()
    watching = loop.create_task(watch(created, received))
    modifying = loop.create_task(modify(created))

    await modifying
    assert received.done(), "Not all changes were propagated"

    # Stop watcher
    watching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watching


async def test_list_clusters(aiohttp_client, config, db):
    clusters = [ClusterFactory(), ClusterFactory(), ClusterFactory(magnum=True)]
    for cluster in clusters:
        await db.put(cluster)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/namespaces/testing/kubernetes/clusters")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Cluster, item) for item in data]

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(clusters, key=key)


async def test_list_clusters_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/namespaces/testing/kubernetes/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes/clusters", "list"):
        resp = await client.get("/namespaces/testing/kubernetes/clusters")
        assert resp.status == 200


async def test_create_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/namespaces/testing/kubernetes/clusters", json=yaml.safe_load(kubeconfig)
    )
    assert resp.status == 200
    data = await resp.json()

    assert uuid_re.match(data["metadata"]["uid"]) is not None

    cluster, rev = await db.get(
        Cluster, namespace="testing", name=data["metadata"]["name"]
    )
    assert rev.version == 1
    assert cluster.status.state == ClusterState.RUNNING


async def test_create_clusters_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/namespaces/testing/kubernetes/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes/clusters", "create"):
        resp = await client.post("/namespaces/testing/kubernetes/clusters")
        assert resp.status == 422


async def test_create_cluster_in_all_namespace(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/namespaces/all/kubernetes/clusters", json=yaml.safe_load(kubeconfig)
    )
    assert resp.status == 400


async def test_create_invalid_cluster(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/namespaces/testing/kubernetes/clusters", json={"invalid": "kubeconfig"}
    )
    assert resp.status == 400
