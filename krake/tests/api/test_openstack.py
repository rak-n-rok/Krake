import asyncio
import json
import pytz

from itertools import count
from operator import attrgetter

from krake.api.app import create_app
from krake.api.helpers import HttpProblem, HttpProblemTitle
from krake.data.core import WatchEventType, WatchEvent, resource_ref, ResourceRef
from krake.data.openstack import (
    MagnumClusterList,
    Project,
    MagnumCluster,
    ProjectList,
    MagnumClusterBinding,
    MagnumClusterState,
    ProjectState,
)
from tests.factories.openstack import (
    AuthMethodFactory,
    ProjectFactory,
    ReasonFactory,
    MagnumClusterFactory,
)

from tests.factories.fake import fake


async def test_create_magnum_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory()

    resp = await client.post(
        "/openstack/namespaces/testing/magnumclusters", json=data.serialize()
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    assert received.spec == data.spec

    stored = await db.get(MagnumCluster, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/openstack/namespaces/testing/magnumclusters")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "create"):
        resp = await client.post("/openstack/namespaces/testing/magnumclusters")
        assert resp.status == 415


async def test_create_magnum_cluster_with_existing_name(aiohttp_client, config, db):
    existing = MagnumClusterFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/openstack/namespaces/testing/magnumclusters", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_delete_magnum_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory()
    await db.put(data)

    resp = await client.delete(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}"
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(MagnumCluster, namespace="testing", name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_magnum_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert body["detail"] == "Finalizers can only be removed" \
                             " if a deletion is in progress."


async def test_delete_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete(
        "/openstack/namespaces/testing/magnumclusters/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "delete"):
        resp = await client.delete(
            "/openstack/namespaces/testing/magnumclusters/my-resource"
        )
        assert resp.status == 404


async def test_delete_magnum_cluster_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = MagnumClusterFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/openstack/namespaces/testing/magnumclusters/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_magnum_clusters(aiohttp_client, config, db):
    resources = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/namespaces/testing/magnumclusters")
    assert resp.status == 200

    body = await resp.json()
    received = MagnumClusterList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources[:-1], key=key)


async def test_list_magnum_clusters_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/magnumclusters")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "list"):
        resp = await client.get("/openstack/namespaces/testing/magnumclusters")
        assert resp.status == 200


async def test_watch_magnum_clusters(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]

    async def watch(created):
        resp = await client.get(
            "/openstack/namespaces/testing/magnumclusters?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = MagnumCluster.deserialize(event.object)

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

        # Create the MagnumClusters
        for data in resources:
            resp = await client.post(
                f"/openstack/namespaces/{data.metadata.namespace}/magnumclusters",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/openstack/namespaces/testing/magnumclusters/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = MagnumCluster.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_all_magnum_clusters(aiohttp_client, config, db):
    resources = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/magnumclusters")
    assert resp.status == 200

    body = await resp.json()
    received = MagnumClusterList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_all_magnum_clusters_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/magnumclusters")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "list"):
        resp = await client.get("/openstack/magnumclusters")
        assert resp.status == 200


async def test_watch_all_magnum_clusters(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        MagnumClusterFactory(metadata__namespace="testing"),
        MagnumClusterFactory(metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get("/openstack/magnumclusters?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = MagnumCluster.deserialize(event.object)

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

        # Create the MagnumClusters
        for data in resources:
            resp = await client.post(
                "/openstack/namespaces/testing/magnumclusters", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/openstack/namespaces/testing/magnumclusters/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = MagnumCluster.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_magnum_cluster(aiohttp_client, config, db):
    data = MagnumClusterFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}"
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())
    assert received == data


async def test_read_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/magnumclusters/my-resource")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "get"):
        resp = await client.get(
            "/openstack/namespaces/testing/magnumclusters/my-resource"
        )
        assert resp.status == 404


async def test_update_magnum_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory(spec__node_count=5, spec__master_count=1)
    await db.put(data)

    data.spec.node_count = 10

    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())
    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.master_count == 1
    assert received.spec.node_count == 10

    stored = await db.get(MagnumCluster, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_magnum_cluster_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the MagnumCluster
    data.metadata.finalizers = []
    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The MagnumCluster should be deleted from the database
    stored = await db.get(MagnumCluster, namespace="testing", name=data.metadata.name)
    assert stored is None


async def test_update_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/openstack/namespaces/testing/magnumclusters/my-resource")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "update"):
        resp = await client.put(
            "/openstack/namespaces/testing/magnumclusters/my-resource"
        )
        assert resp.status == 415


async def test_update_magnum_cluster_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory()
    await db.put(data)

    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_magnum_cluster_immutable_field(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_update_magnum_cluster_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)
    project = ProjectFactory()

    assert not data.metadata.owners, "Unexpected owners"
    assert data.status.project is None

    await db.put(data)
    await db.put(project)

    project_ref = resource_ref(project)
    binding = MagnumClusterBinding(project=project_ref, template=project.spec.template)

    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}/binding",
        json=binding.serialize(),
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())
    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert received.status.project == project_ref
    assert received.status.template == project.spec.template
    assert received.status.state == MagnumClusterState.PENDING
    assert project_ref in received.metadata.owners

    stored = await db.get(MagnumCluster, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_magnum_cluster_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/openstack/namespaces/testing/magnumclusters/my-resource/binding"
    )
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters/binding", "update"):
        resp = await client.put(
            "/openstack/namespaces/testing/magnumclusters/my-resource/binding"
        )
        assert resp.status == 404


async def test_update_magnum_cluster_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)
    await db.put(data)

    data.status.state = MagnumClusterState.FAILED
    data.status.reason = ReasonFactory()
    data.status.project = ResourceRef(
        api="openstack", kind="Project", namespace="testing", name="test-project"
    )

    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())
    assert received.api == "openstack"
    assert received.kind == "MagnumCluster"
    assert received.metadata == data.metadata
    assert received.status == data.status

    stored = await db.get(MagnumCluster, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_magnum_cluster_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/openstack/namespaces/testing/magnumclusters/my-resource/status"
    )
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters/status", "update"):
        resp = await client.put(
            "/openstack/namespaces/testing/magnumclusters/my-resource/status"
        )
        assert resp.status == 415


async def test_create_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ProjectFactory()

    resp = await client.post(
        "/openstack/namespaces/testing/projects", json=data.serialize()
    )
    assert resp.status == 200
    received = Project.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
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
    assert body["detail"] == "Finalizers can only be removed" \
                             " if a deletion is in progress."


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
