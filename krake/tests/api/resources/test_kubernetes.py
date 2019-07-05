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
    Cluster,
    ClusterState,
)
from krake.data import serialize, deserialize
from krake.api.app import create_app

from factories.kubernetes import ApplicationFactory


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


async def test_list_apps(aiohttp_client, config, user, db):
    apps = [
        ApplicationFactory(user=user, status__state=ApplicationState.PENDING),
        ApplicationFactory(user=user, status__state=ApplicationState.SCHEDULED),
        ApplicationFactory(user=user, status__state=ApplicationState.UPDATED),
        ApplicationFactory(user=user, status__state=ApplicationState.DELETING),
        ApplicationFactory(user=user, status__state=ApplicationState.DELETED),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/applications")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps) - 1

    key = attrgetter("uid")
    assert sorted(received, key=key) == sorted(apps[:-1], key=key)


async def test_list_all_apps(aiohttp_client, config, user, db):
    apps = [
        ApplicationFactory(user=user, status__state=ApplicationState.PENDING),
        ApplicationFactory(user=user, status__state=ApplicationState.DELETED),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/applications?all")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps)

    key = attrgetter("uid")
    assert sorted(received, key=key) == sorted(apps, key=key)


async def test_create_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/applications", json={"manifest": manifest, "name": "test-app"}
    )
    assert resp.status == 200
    data = await resp.json()

    assert uuid_re.match(data["uid"]) is not None

    app, rev = await db.get(Application, name=data["name"], user=data["user"])
    assert rev.version == 1
    assert app.status.state == ApplicationState.PENDING
    assert app.manifest == manifest


async def test_create_invalid_app(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/applications", json={"manifest": None})
    assert resp.status == 422
    data = await resp.json()

    assert data["manifest"]


async def test_create_app_with_existing_name(aiohttp_client, config, db, user):
    existing = ApplicationFactory(user=user, name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/applications", json={"manifest": manifest, "name": "existing"}
    )
    assert resp.status == 400


async def test_get_app(aiohttp_client, user, config, db):
    app = ApplicationFactory(user=user, status__state=ApplicationState.RUNNING)
    await db.put(app)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/kubernetes/applications/{app.name}")
    assert resp.status == 200
    data = deserialize(Application, await resp.json())
    assert app == data


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


async def test_update_manifest(aiohttp_client, config, db, user):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(user=user, status__state=ApplicationState.PENDING)

    await db.put(app)

    resp = await client.put(
        f"/kubernetes/applications/{app.name}", json={"manifest": new_manifest}
    )
    assert resp.status == 200
    data = await resp.json()

    assert data["manifest"] == new_manifest

    stored, rev = await db.get(Application, user=user, name=app.name)
    assert stored.manifest == new_manifest
    assert rev.version == 2


async def test_update_manifest_already_deleted(aiohttp_client, config, db, user):
    client = await aiohttp_client(create_app(config=config))

    # Create applications
    deleting = ApplicationFactory(user=user, status__state=ApplicationState.DELETING)
    deleted = ApplicationFactory(user=user, status__state=ApplicationState.DELETED)
    await db.put(deleting)
    await db.put(deleted)

    # Update already deleting application
    resp = await client.put(
        f"/kubernetes/applications/{deleting.name}", json={"manifest": new_manifest}
    )
    assert resp.status == 400

    # Update already deleted application
    resp = await client.put(
        f"/kubernetes/applications/{deleted.name}", json={"manifest": new_manifest}
    )
    assert resp.status == 400


async def test_update_status(aiohttp_client, config, db, user):
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(user=user, status__state=ApplicationState.PENDING)

    await db.put(app)

    resp = await client.put(
        f"/kubernetes/applications/{app.name}/status",
        json={
            "state": "FAILED",
            "reason": "Stupid error",
            "cluster": {"name": "1234", "user": user},
        },
    )
    assert resp.status == 200
    status = deserialize(ApplicationStatus, await resp.json())

    assert status.state == ApplicationState.FAILED
    assert status.created == app.status.created
    assert status.reason == "Stupid error"
    assert status.cluster == (user, "1234")

    stored, rev = await db.get(Application, user=user, name=app.name)
    assert stored.status == status
    assert rev.version == 2


async def test_delete(aiohttp_client, config, db, user):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    client = await aiohttp_client(create_app(config=config))
    app = ApplicationFactory(user=user, status__state=ApplicationState.PENDING)
    await db.put(app)

    # Delete application
    resp = await client.delete(f"/kubernetes/applications/{app.name}")
    assert resp.status == 200

    deleted, rev = await db.get(Application, user=user, name=app.name)
    assert deleted.status.state == ApplicationState.DELETING
    assert deleted.manifest == manifest


async def test_delete_already_deleted(aiohttp_client, config, db, user):
    client = await aiohttp_client(create_app(config=config))

    # Create applications
    deleting = ApplicationFactory(user=user, status__state=ApplicationState.DELETING)
    deleted = ApplicationFactory(user=user, status__state=ApplicationState.DELETED)
    await db.put(deleting)
    await db.put(deleted)

    # Delete already deleting application
    resp = await client.delete(f"/kubernetes/applications/{deleting.name}")
    assert resp.status == 304

    # Delete already deleted application
    resp = await client.delete(f"/kubernetes/applications/{deleted.name}")
    assert resp.status == 304


async def test_watch(aiohttp_client, config, loop):
    client = await aiohttp_client(create_app(config=config))

    async def watch(created):
        resp = await client.get("/kubernetes/applications?watch")
        created.set_result(True)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexecpted EOF"

            data = json.loads(line.decode())
            assert uuid_re.match(data["uid"])

            if i == 0:
                assert data["status"]["state"] == "PENDING"
            elif i == 1:
                assert data["status"]["state"] == "PENDING"
            elif i == 2:
                assert data["status"]["state"] == "DELETING"

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications
        for i in range(2):
            resp = await client.post(
                "/kubernetes/applications",
                json={"manifest": manifest, "name": f"test-app-{i}"},
            )
            assert resp.status == 200

        data = await resp.json()
        resp = await client.delete(f'/kubernetes/applications/{data["name"]}')
        assert resp.status == 200

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await modifying

    # Stop watcher
    watching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watching


async def test_list_clusters(aiohttp_client, config, k8s_magnum_cluster_factory, db):
    clusters = [
        k8s_magnum_cluster_factory(),
        k8s_magnum_cluster_factory(),
        k8s_magnum_cluster_factory(),
    ]
    for cluster in clusters:
        await db.put(cluster)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/clusters")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Cluster, item) for item in data]

    key = attrgetter("uid")
    assert sorted(received, key=key) == sorted(clusters, key=key)


async def test_create_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/clusters", json=yaml.safe_load(kubeconfig))
    assert resp.status == 200
    data = await resp.json()

    assert uuid_re.match(data["uid"]) is not None

    cluster, rev = await db.get(Cluster, name=data["name"], user=data["user"])
    assert rev.version == 1
    assert cluster.status.state == ClusterState.RUNNING


async def test_create_invalid_cluster(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/clusters", json={"invalid": "kubeconfig"})
    assert resp.status == 400
