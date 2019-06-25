import pytest
import asyncio
import re
import json
from itertools import count
from operator import attrgetter

from krake.data.kubernetes import (
    Application,
    ApplicationState,
    ApplicationStatus,
    Cluster,
)
from krake.data import serialize, deserialize
from krake.api.app import create_app


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


async def test_list_apps(aiohttp_client, config, k8s_app_factory, db):
    apps = [
        k8s_app_factory(status__state=ApplicationState.PENDING),
        k8s_app_factory(status__state=ApplicationState.SCHEDULED),
        k8s_app_factory(status__state=ApplicationState.UPDATED),
        k8s_app_factory(status__state=ApplicationState.DELETING),
        k8s_app_factory(status__state=ApplicationState.DELETED),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/applications")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps) - 1

    key = attrgetter("id")
    assert sorted(received, key=key) == sorted(apps[:-1], key=key)


async def test_list_all_apps(aiohttp_client, config, k8s_app_factory, db):
    apps = [
        k8s_app_factory(status__state=ApplicationState.PENDING),
        k8s_app_factory(status__state=ApplicationState.DELETED),
    ]
    for app in apps:
        await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/applications?all")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Application, item) for item in data]

    assert len(received) == len(apps)

    key = attrgetter("id")
    assert sorted(received, key=key) == sorted(apps, key=key)


async def test_create_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    payload = {"manifest": manifest}

    resp = await client.post("/kubernetes/applications", json=payload)
    assert resp.status == 200
    data = await resp.json()

    assert uuid_re.match(data["id"]) is not None

    app, rev = await db.get(Application, data["id"])
    assert rev.version == 1
    assert app.status.state == ApplicationState.PENDING
    assert app.manifest == manifest


async def test_create_invalid_app(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))

    payload = {"manifest": None}

    resp = await client.post("/kubernetes/applications", json=payload)
    assert resp.status == 422
    data = await resp.json()

    assert data["manifest"]


async def test_get_app(aiohttp_client, config, db, k8s_app_factory):
    app = k8s_app_factory(status__state=ApplicationState.RUNNING)
    await db.put(app)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/kubernetes/applications/{app.id}")
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


async def test_update_manifest(aiohttp_client, config, db, k8s_app_factory):
    client = await aiohttp_client(create_app(config=config))
    app = k8s_app_factory(status__state=ApplicationState.PENDING)

    await db.put(app)

    resp = await client.put(
        f"/kubernetes/applications/{app.id}", json={"manifest": new_manifest}
    )
    assert resp.status == 200
    data = await resp.json()

    assert data["manifest"] == new_manifest

    stored, rev = await db.get(Application, app.id)
    assert stored.manifest == new_manifest
    assert rev.version == 2


async def test_update_status(aiohttp_client, config, db, k8s_app_factory):
    client = await aiohttp_client(create_app(config=config))
    app = k8s_app_factory(status__state=ApplicationState.PENDING)

    await db.put(app)

    resp = await client.put(
        f"/kubernetes/applications/{app.id}/status",
        json={"state": "FAILED", "reason": "Stupid error", "cluster": "1234"},
    )
    assert resp.status == 200
    status = deserialize(ApplicationStatus, await resp.json())

    assert status.state == ApplicationState.FAILED
    assert status.created == app.status.created
    assert status.reason == "Stupid error"
    assert status.cluster == "1234"

    stored, rev = await db.get(Application, app.id)
    assert stored.status == status
    assert rev.version == 2


async def test_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    resp = await client.post("/kubernetes/applications", json={"manifest": manifest})
    assert resp.status == 200
    data = await resp.json()

    # Delete application
    resp = await client.delete(f'/kubernetes/applications/{data["id"]}')
    assert resp.status == 200

    app, rev = await db.get(Application, data["id"])
    assert app.status.state == ApplicationState.DELETED
    assert app.manifest == manifest


async def test_watch(aiohttp_client, config, loop):
    client = await aiohttp_client(create_app(config=config))

    async def watch(created):
        resp = await client.get("/kubernetes/applications?watch")
        created.set_result(True)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexecpted EOF"

            data = json.loads(line.decode())
            assert uuid_re.match(data["id"])

            if i == 0:
                assert data["status"]["state"] == "PENDING"
            elif i == 1:
                assert data["status"]["state"] == "PENDING"
            elif i == 2:
                assert data["status"]["state"] == "DELETED"

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create two applications
        for _ in range(2):
            resp = await client.post(
                "/kubernetes/applications", json={"manifest": manifest}
            )
            assert resp.status == 200

        data = await resp.json()
        resp = await client.delete(f'/kubernetes/applications/{data["id"]}')
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

    key = attrgetter("id")
    assert sorted(received, key=key) == sorted(clusters, key=key)
