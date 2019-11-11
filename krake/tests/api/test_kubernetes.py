import asyncio
import json
import pytest
import pytz
import yaml

from itertools import count
from operator import attrgetter
from secrets import token_urlsafe

from krake.data.core import WatchEvent, WatchEventType, ResourceRef, resource_ref
from krake.data.kubernetes import (
    Application,
    ApplicationList,
    ApplicationState,
    ClusterBinding,
    Cluster,
    ClusterList,
    LabelConstraint,
    EqualConstraint,
    NotEqualConstraint,
    InConstraint,
    NotInConstraint,
    ApplicationComplete,
)
from krake.api.app import create_app
from krake.api.database import revision

from factories.kubernetes import ApplicationFactory, ClusterFactory
from factories.core import ReasonFactory
from factories.fake import fake


@pytest.mark.parametrize(
    "expression", ["location == DE", "location = DE", "location is DE"]
)
def test_parse_equal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, EqualConstraint)
    assert constraint.value == "DE"


@pytest.mark.parametrize("expression", ["location != DE", "location is not DE"])
def test_parse_notequal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, NotEqualConstraint)
    assert constraint.value == "DE"


@pytest.mark.parametrize(
    "expression", ["location in (DE, SK)", "location in (DE, SK,)"]
)
def test_parse_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE", "SK")


@pytest.mark.parametrize("expression", ["location in (DE)", "location in (DE,)"])
def test_parse_single_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE",)


@pytest.mark.parametrize(
    "expression", ["location not in (DE, SK)", "location not in (DE, SK,)"]
)
def test_parse_notin_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, NotInConstraint)
    assert constraint.values == ("DE", "SK")


def test_equal_constraint_match():
    assert LabelConstraint.parse("location is DE").match({"location": "DE"})
    assert not LabelConstraint.parse("location is DE").match({"location": "SK"})


def test_notequal_constraint_match():
    assert LabelConstraint.parse("location is not DE").match({"location": "SK"})
    assert not LabelConstraint.parse("location is not DE").match({"location": "DE"})


def test_in_constraint_match():
    assert LabelConstraint.parse("location in (DE, SK)").match({"location": "SK"})
    assert not LabelConstraint.parse("location in (DE, SK)").match({"location": "EU"})


def test_notin_constraint_match():
    assert LabelConstraint.parse("location not in (DE, SK)").match({"location": "EU"})
    assert not LabelConstraint.parse("location not in (DE, SK)").match(
        {"location": "DE"}
    )


def test_str_equal_constraint():
    constraint = EqualConstraint(label="location", value="DE")
    assert str(constraint) == "location is DE"


def test_str_notequal_constraint():
    constraint = NotEqualConstraint(label="location", value="DE")
    assert str(constraint) == "location is not DE"


def test_str_in_constraint():
    constraint = InConstraint(label="location", values=("DE", "SK"))
    assert str(constraint) == "location in (DE, SK)"


def test_str_notin_constraint():
    constraint = NotInConstraint(label="location", values=("DE", "SK"))
    assert str(constraint) == "location not in (DE, SK)"


async def test_list_apps(aiohttp_client, config, db):
    apps = [
        ApplicationFactory(status__state=ApplicationState.PENDING),
        ApplicationFactory(status__state=ApplicationState.CREATING),
        ApplicationFactory(status__state=ApplicationState.RECONCILING),
        ApplicationFactory(status__state=ApplicationState.MIGRATING),
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
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "list"):
        resp = await client.get("/kubernetes/namespaces/testing/applications")
        assert resp.status == 200


async def test_create_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ApplicationFactory(status=None)

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    app = Application.deserialize(await resp.json())

    assert app.metadata.created
    assert app.metadata.modified
    assert app.spec == data.spec
    assert app.status.state == ApplicationState.PENDING

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == app


async def test_create_app_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

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
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.get("/kubernetes/namespaces/testing/applications/myapp")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "get"):
        resp = await client.get("/kubernetes/namespaces/testing/applications/myapp")
        assert resp.status == 404


new_manifest = list(
    yaml.safe_load_all(
        """---
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
    )
)


async def test_update_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(data)
    data.spec.manifest = new_manifest

    resp = await client.put(
        f"/kubernetes/namespaces/{data.metadata.namespace}"
        f"/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    app = Application.deserialize(await resp.json())

    assert app.status.state == data.status.state
    assert app.spec.manifest == new_manifest

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=app.metadata.name
    )
    assert stored == app


async def test_update_app_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

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
        json=app.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received.metadata == app.metadata
    assert received.status == app.status

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status == received.status
    assert revision(stored).version == 2


async def test_update_app_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

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

    assert not app.metadata.owners, "There are no owners"
    assert app.status.scheduled_to is None, "Application is not scheduled"
    assert app.status.running_on is None, "Application is not running on a cluster"

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
    assert received.status.scheduled_to == cluster_ref
    assert received.status.running_on is None
    assert received.status.state == ApplicationState.PENDING
    assert cluster_ref in received.metadata.owners

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.scheduled_to == cluster_ref
    assert stored.status.running_on is None
    assert stored.status.state == ApplicationState.PENDING
    assert cluster_ref in stored.metadata.owners


async def test_update_app_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(app)

    # Delete application
    app.metadata.finalizers = []
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}",
        json=app.serialize(),
    )
    assert resp.status == 200
    data = Application.deserialize(await resp.json())
    assert resource_ref(data) == resource_ref(app)

    # The Application should be deleted from the database
    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored is None


async def test_delete_app(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
    app = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(app)

    # Delete application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}"
    )
    assert resp.status == 200
    data = Application.deserialize(await resp.json())
    assert resource_ref(data) == resource_ref(app)

    deleted = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


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
        json=app.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert len(body["metadata"]["finalizers"]) == 1


async def test_delete_app_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

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
                assert event.type == WatchEventType.MODIFIED
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
                "/kubernetes/namespaces/testing/applications", json=app.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/applications/{apps[0].metadata.name}"
        )
        assert resp.status == 200

        received = Application.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(apps[0])
        assert received.metadata.deleted is not None

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
                json=app.serialize(),
            )
            assert resp.status == 200

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_complete_hook(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    token = token_urlsafe()

    # Create application
    app = ApplicationFactory(status__token=token)
    await db.put(app)

    # Complete application
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/complete",
        json=ApplicationComplete(token=token).serialize(),
    )
    assert resp.status == 200
    data = Application.deserialize(await resp.json())
    assert resource_ref(data) == resource_ref(app)

    completed = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert completed.metadata.deleted is not None


async def test_complete_hook_unauthorized(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    token = token_urlsafe()

    # Create application
    app = ApplicationFactory(status__token=token)
    await db.put(app)

    # Complete application
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/complete",
        json=ApplicationComplete().serialize(),
    )
    assert resp.status == 401


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
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.get("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "list"):
        resp = await client.get("/kubernetes/namespaces/testing/clusters")
        assert resp.status == 200


async def test_create_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory()

    resp = await client.post(
        f"/kubernetes/namespaces/{data.metadata.namespace}/clusters",
        json=data.serialize(),
    )
    assert resp.status == 200
    cluster = Cluster.deserialize(await resp.json())

    assert cluster.metadata.created
    assert cluster.metadata.modified
    assert cluster.spec == data.spec

    stored = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == cluster


async def test_create_clusters_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/namespaces/testing/clusters")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/clusters")
        assert resp.status == 415


async def test_create_invalid_cluster(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(spec__kubeconfig={"invalid": "kubeconfig"})

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters", json=data.serialize()
    )
    assert resp.status == 422


async def test_delete_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    cluster = ClusterFactory()
    await db.put(cluster)

    # Delete application
    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}"
    )
    assert resp.status == 200
    data = Cluster.deserialize(await resp.json())
    assert resource_ref(data) == resource_ref(cluster)

    deleted = await db.get(Cluster, namespace="testing", name=cluster.metadata.name)
    assert deleted.metadata.deleted is not None


async def test_delete_cluster_with_finalizers(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create application
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

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.metadata.deleted


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
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/kubernetes/namespaces/testing/clusters/my-cluster")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters", "delete"):
        resp = await client.delete("/kubernetes/namespaces/testing/clusters/my-cluster")
        assert resp.status == 404
