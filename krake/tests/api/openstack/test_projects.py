import asyncio
import json
import pytz

from itertools import count
from operator import attrgetter

from krake.api.app import create_app
from krake.api.helpers import HttpProblem, HttpProblemTitle
from krake.data.core import WatchEventType, WatchEvent, resource_ref
from krake.data.openstack import (
    Project,
    ProjectList,
    ProjectState,
)
from tests.factories.openstack import (
    AuthMethodFactory,
    ProjectFactory,
    ReasonFactory,
)

from tests.factories.fake import fake
from tests.api.test_core import assert_valid_metadata


# region Create
async def test_create_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory()

    resp = await client.post(
        "/openstack/namespaces/testing/projects", json=data.serialize()
    )
    assert resp.status == 200
    received = Project.deserialize(await resp.json())

    assert_valid_metadata(received.metadata, "testing")
    assert received.spec == data.spec

    stored = await db.get(Project, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/openstack/namespaces/testing/projects")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "create"):
        resp = await client.post("/openstack/namespaces/testing/projects")
        assert resp.status == 415


async def test_create_project_with_existing_name(aiohttp_client, config, db):
    existing = ProjectFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/openstack/namespaces/testing/projects", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


# endregion Create


# region Read
async def test_list_projects(aiohttp_client, config, db):
    resources = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/namespaces/testing/projects")
    assert resp.status == 200

    body = await resp.json()
    received = ProjectList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources[:-1], key=key)


async def test_list_projects_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/projects")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "list"):
        resp = await client.get("/openstack/namespaces/testing/projects")
        assert resp.status == 200


async def test_watch_projects(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]

    async def watch(created):
        resp = await client.get(
            "/openstack/namespaces/testing/projects?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Project.deserialize(event.object)

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

        # Create the Projects
        for data in resources:
            resp = await client.post(
                f"/openstack/namespaces/{data.metadata.namespace}/projects",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/openstack/namespaces/testing/projects/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Project.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_all_projects(aiohttp_client, config, db):
    resources = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/projects")
    assert resp.status == 200

    body = await resp.json()
    received = ProjectList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_all_projects_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/projects")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "list"):
        resp = await client.get("/openstack/projects")
        assert resp.status == 200


async def test_watch_all_projects(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        ProjectFactory(metadata__namespace="testing"),
        ProjectFactory(metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get("/openstack/projects?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Project.deserialize(event.object)

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

        # Create the Projects
        for data in resources:
            resp = await client.post(
                "/openstack/namespaces/testing/projects", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/openstack/namespaces/testing/projects/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Project.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_project(aiohttp_client, config, db):
    data = ProjectFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Project.deserialize(await resp.json())
    assert received == data


async def test_read_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/projects/my-resource")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "get"):
        resp = await client.get("/openstack/namespaces/testing/projects/my-resource")
        assert resp.status == 404


# endregion Read


# region Update
async def test_update_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory()
    await db.put(data)

    auth = AuthMethodFactory(type="password")
    labels = {"my-label": "my-value"}
    data.spec.auth = auth
    data.metadata.labels = labels

    resp = await client.put(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Project.deserialize(await resp.json())

    assert received.api == "openstack"
    assert received.kind == "Project"
    assert data.metadata.modified < received.metadata.modified
    assert received.metadata.labels == labels
    assert received.spec.auth == auth

    stored = await db.get(Project, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_project_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the Project
    data.metadata.finalizers = []
    resp = await client.put(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Project.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The Project should be deleted from the database
    stored = await db.get(Project, namespace="testing", name=data.metadata.name)
    assert stored is None


async def test_update_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/openstack/namespaces/testing/projects/my-resource")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "update"):
        resp = await client.put("/openstack/namespaces/testing/projects/my-resource")
        assert resp.status == 415


async def test_update_project_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory()
    await db.put(data)

    resp = await client.put(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_project_immutable_field(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_update_project_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory()
    await db.put(data)

    data.status.state = ProjectState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    resp = await client.put(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Project.deserialize(await resp.json())
    assert received.api == "openstack"
    assert received.kind == "Project"

    assert received.status.state == ProjectState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(Project, namespace="testing", name=data.metadata.name)
    assert stored == received
    assert stored.status.state == ProjectState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]


async def test_update_project_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/openstack/namespaces/testing/projects/my-resource/status")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects/status", "update"):
        resp = await client.put(
            "/openstack/namespaces/testing/projects/my-resource/status"
        )
        assert resp.status == 415


# endregion Update


# region Delete
async def test_delete_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory()
    await db.put(data)

    resp = await client.delete(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Project.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Project, namespace="testing", name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/openstack/namespaces/testing/projects/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )


async def test_delete_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete("/openstack/namespaces/testing/projects/my-resource")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "delete"):
        resp = await client.delete("/openstack/namespaces/testing/projects/my-resource")
        assert resp.status == 404


async def test_delete_project_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = ProjectFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/openstack/namespaces/testing/projects/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


# region Delete
