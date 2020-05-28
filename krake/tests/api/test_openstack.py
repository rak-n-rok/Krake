from operator import attrgetter

from krake.data.core import resource_ref, ResourceRef
from krake.data.openstack import (
    Project,
    ProjectList,
    MagnumCluster,
    MagnumClusterList,
    MagnumClusterState,
    MagnumClusterBinding,
)
from krake.api.app import create_app
from krake.api.database import revision

from tests.factories.core import ReasonFactory
from tests.factories.openstack import (
    ProjectFactory,
    AuthMethodFactory,
    MagnumClusterFactory,
)


async def test_list_projects(aiohttp_client, config, db):
    projects = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]
    for project in projects:
        await db.put(project)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/namespaces/testing/projects")
    assert resp.status == 200

    body = await resp.json()
    received = ProjectList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(projects[:-1], key=key)


async def test_list_all_projects(aiohttp_client, config, db):
    projects = [
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(),
        ProjectFactory(metadata__namespace="other"),
    ]
    for project in projects:
        await db.put(project)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/projects")
    assert resp.status == 200

    body = await resp.json()
    received = ProjectList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(projects, key=key)


async def test_list_projects_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/projects")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "list"):
        resp = await client.get("/openstack/namespaces/testing/projects")
        assert resp.status == 200


async def test_create_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ProjectFactory()

    resp = await client.post(
        "/openstack/namespaces/testing/projects", json=data.serialize()
    )
    body = await resp.json()
    assert resp.status == 200
    project = Project.deserialize(body)

    # Ensure read-only fields are generated
    assert project.metadata.created
    assert project.metadata.modified
    assert project.metadata.namespace == "testing"
    assert project.metadata.uid

    assert project.spec == data.spec

    stored = await db.get(Project, namespace="testing", name=data.metadata.name)
    assert stored == project


async def test_create_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

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


async def test_get_project(aiohttp_client, config, db):
    project = ProjectFactory()
    await db.put(project)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/openstack/namespaces/testing/projects/{project.metadata.name}"
    )
    assert resp.status == 200
    data = Project.deserialize(await resp.json())
    assert project == data


async def test_get_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/projects/my-project")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "get"):
        resp = await client.get("/openstack/namespaces/testing/projects/my-project")
        assert resp.status == 404


async def test_update_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    auth = AuthMethodFactory(type="password")
    labels = {"my-label": "my-value"}

    data = ProjectFactory()
    await db.put(data)
    data.spec.auth = auth
    data.metadata.labels = labels

    resp = await client.put(
        f"/openstack/namespaces/{data.metadata.namespace}"
        f"/projects/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    project = Project.deserialize(await resp.json())
    assert project.metadata.labels == labels
    assert project.spec.auth == auth

    stored = await db.get(
        Project, namespace=data.metadata.namespace, name=project.metadata.name
    )
    assert stored == project


async def test_update_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.put("/openstack/namespaces/testing/projects/my-project")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "update"):
        resp = await client.put("/openstack/namespaces/testing/projects/my-project")
        assert resp.status == 415


async def test_delete_project(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create project
    project = ProjectFactory()
    await db.put(project)

    # Delete project
    resp = await client.delete(
        f"/openstack/namespaces/testing/projects/{project.metadata.name}"
    )
    assert resp.status == 200
    data = Project.deserialize(await resp.json())
    assert data.metadata.deleted is not None

    deleted = await db.get(
        Project, namespace=project.metadata.namespace, name=project.metadata.name
    )
    assert deleted.metadata.deleted is not None


async def test_delete_project_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.delete("/openstack/namespaces/testing/projects/my-project")
    assert resp.status == 403

    async with rbac_allow("openstack", "projects", "delete"):
        resp = await client.delete("/openstack/namespaces/testing/projects/my-project")
        assert resp.status == 404


async def test_list_magnum_clusters(aiohttp_client, config, db):
    clusters = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]
    for project in clusters:
        await db.put(project)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/namespaces/testing/magnumclusters")
    assert resp.status == 200

    body = await resp.json()
    received = MagnumClusterList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(clusters[:-1], key=key)


async def test_list_all_magnum_clusters(aiohttp_client, config, db):
    clusters = [
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(),
        MagnumClusterFactory(metadata__namespace="other"),
    ]
    for project in clusters:
        await db.put(project)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/openstack/magnumclusters")
    assert resp.status == 200

    body = await resp.json()
    received = MagnumClusterList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(clusters, key=key)


async def test_list_magnum_clusters_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/magnumclusters")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "list"):
        resp = await client.get("/openstack/namespaces/testing/magnumclusters")
        assert resp.status == 200


async def test_create_magnum_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = MagnumClusterFactory(status=None)

    resp = await client.post(
        "/openstack/namespaces/testing/magnumclusters", json=data.serialize()
    )
    body = await resp.json()
    assert resp.status == 200
    cluster = MagnumCluster.deserialize(body)

    # Ensure read-only fields are generated
    assert cluster.metadata.created
    assert cluster.metadata.modified
    assert cluster.metadata.namespace == "testing"
    assert cluster.metadata.uid

    assert cluster.spec == data.spec

    stored = await db.get(MagnumCluster, namespace="testing", name=data.metadata.name)
    assert stored == cluster


async def test_create_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

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


async def test_get_magnum_cluster(aiohttp_client, config, db):
    cluster = MagnumClusterFactory()
    await db.put(cluster)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/openstack/namespaces/testing/magnumclusters/{cluster.metadata.name}"
    )
    assert resp.status == 200
    data = MagnumCluster.deserialize(await resp.json())
    assert cluster == data


async def test_get_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/openstack/namespaces/testing/magnumclusters/my-cluster")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "get"):
        resp = await client.get(
            "/openstack/namespaces/testing/magnumclusters/my-cluster"
        )
        assert resp.status == 404


async def test_magnum_cluster_update(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory(spec__node_count=5, spec__master_count=1)
    await db.put(data)
    data.spec.master_count = 2
    data.spec.node_count = 10

    resp = await client.put(
        f"/openstack/namespaces/{data.metadata.namespace}"
        f"/magnumclusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    cluster = MagnumCluster.deserialize(await resp.json())
    assert cluster.spec.master_count == 1
    assert cluster.spec.node_count == 10

    stored = await db.get(
        cluster, namespace=data.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.spec == cluster.spec


async def test_update_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.put("/openstack/namespaces/testing/magnumclusters/my-cluster")
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "update"):
        resp = await client.put(
            "/openstack/namespaces/testing/magnumclusters/my-cluster"
        )
        assert resp.status == 415


async def test_magnum_cluster_template_immutable(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = MagnumClusterFactory(status__template="template1")
    await db.put(data)
    data.spec.template = "template2"

    resp = await client.put(
        f"/openstack/namespaces/{data.metadata.namespace}"
        f"/magnumclusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    cluster = MagnumCluster.deserialize(await resp.json())
    assert cluster.status.template == "template1"

    stored = await db.get(
        cluster, namespace=data.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.template == "template1"


async def test_magnum_cluster_status_update(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    cluster = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)

    await db.put(cluster)

    cluster.status.state = MagnumClusterState.FAILED
    cluster.status.reason = ReasonFactory()
    cluster.status.project = ResourceRef(
        api="openstack", kind="Project", namespace="testing", name="test-project"
    )

    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{cluster.metadata.name}/status",
        json=cluster.serialize(),
    )
    assert resp.status == 200
    received = MagnumCluster.deserialize(await resp.json())
    assert received.metadata == cluster.metadata
    assert received.status == cluster.status

    stored = await db.get(
        MagnumCluster, namespace="testing", name=cluster.metadata.name
    )
    assert stored.status == received.status
    assert revision(stored).version == 2


async def test_magnum_cluster_status_update_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.put(
        "/openstack/namespaces/testing/magnumclusters/my-cluster/status"
    )
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters/status", "update"):
        resp = await client.put(
            "/openstack/namespaces/testing/magnumclusters/my-cluster/status"
        )
        assert resp.status == 415


async def test_magnum_cluster_binding_update(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    cluster = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)
    project = ProjectFactory()

    assert not cluster.metadata.owners, "Unexpected owners"
    assert cluster.status.project is None

    await db.put(cluster)
    await db.put(project)

    project_ref = resource_ref(project)
    resp = await client.put(
        f"/openstack/namespaces/testing/magnumclusters/{cluster.metadata.name}/binding",
        json=MagnumClusterBinding(
            project=project_ref, template=project.spec.template
        ).serialize(),
    )
    assert resp.status == 200
    body = await resp.json()
    received = MagnumCluster.deserialize(body)
    assert received.status.project == project_ref
    assert received.status.template == project.spec.template
    assert received.status.state == MagnumClusterState.PENDING
    assert project_ref in received.metadata.owners

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.project == project_ref
    assert stored.status.template == project.spec.template
    assert stored.status.state == MagnumClusterState.PENDING
    assert project_ref in stored.metadata.owners


async def test_magnum_cluster_binding_update_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.put(
        "/openstack/namespaces/testing/magnumclusters/my-cluster/binding"
    )
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters/binding", "update"):
        resp = await client.put(
            "/openstack/namespaces/testing/magnumclusters/my-cluster/binding"
        )
        assert resp.status == 404


async def test_delete_magnum_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create cluster
    cluster = MagnumClusterFactory()
    await db.put(cluster)

    # Delete cluster
    resp = await client.delete(
        f"/openstack/namespaces/testing/magnumclusters/{cluster.metadata.name}"
    )
    assert resp.status == 200
    data = MagnumCluster.deserialize(await resp.json())
    assert data.metadata.deleted is not None

    deleted = await db.get(
        cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert deleted.metadata.deleted is not None


async def test_delete_magnum_cluster_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.delete(
        "/openstack/namespaces/testing/magnumclusters/my-cluster"
    )
    assert resp.status == 403

    async with rbac_allow("openstack", "magnumclusters", "delete"):
        resp = await client.delete(
            "/openstack/namespaces/testing/magnumclusters/my-cluster"
        )
        assert resp.status == 404
