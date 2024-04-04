import pytz

from krake.data.infrastructure import CloudBinding

from krake.api.app import create_app
from krake.api.helpers import HttpProblem, HttpProblemTitle
from krake.data.core import WatchEvent, WatchEventType, resource_ref
from krake.data.kubernetes import (
    Cluster,
    ClusterList,
    ClusterState,
)
from tests.factories.infrastructure import CloudFactory

from tests.factories.kubernetes import (
    ClusterFactory,
    ReasonFactory,
)
from tests.factories.fake import fake

import asyncio
import json
from itertools import count
from operator import attrgetter


from tests.api.test_core import assert_valid_metadata


# region Create cluster tests
async def test_create_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ClusterFactory()

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters", json=data.serialize()
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())

    assert_valid_metadata(received.metadata, "testing")
    assert received.spec == data.spec

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
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_create_invalid_cluster(aiohttp_client, config):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(spec__kubeconfig={"invalid": "kubeconfig"})

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters", json=data.serialize()
    )
    assert resp.status == 422


# endregion Create cluster tests


# region Read cluster tests
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


# endregion Read cluster tests


# region Update clusters tests


async def test_update_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ClusterFactory(spec__custom_resources=[])
    await db.put(data)
    new_custom_resources = ["crontabs.stable.example.com"]
    data.spec.custom_resources = new_custom_resources

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.kubeconfig == data.spec.kubeconfig
    assert received.spec.custom_resources == new_custom_resources

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


async def test_update_cluster_immutable_field(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ClusterFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_update_cluster_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(status__state=ClusterState.PENDING)
    cloud = CloudFactory()

    await db.put(data)
    await db.put(cloud)

    assert not data.metadata.owners, "There are no owners"
    assert data.status.scheduled_to is None, "Cluster is scheduled"
    assert data.status.running_on is None, "Cluster is running on a cloud"

    cloud_ref = resource_ref(cloud)
    binding = CloudBinding(cloud=cloud_ref)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}/binding",
        json=binding.serialize(),
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Cluster"

    assert received.status.scheduled_to == cloud_ref
    assert received.status.scheduled
    assert received.status.running_on is None
    assert received.status.state == ClusterState.PENDING
    assert cloud_ref in received.metadata.owners

    stored = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_cluster_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/clusters/my-resource/binding"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "clusters/binding", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/clusters/my-resource/binding"
        )
        assert resp.status == 415


async def test_update_cluster_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # MISSING Subresource-specific attributes can be set here
    data = ClusterFactory()
    await db.put(data)

    data.status.state = ClusterState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    resp = await client.put(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Cluster"

    assert received.status.state == ClusterState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert stored == received
    assert stored.status.state == ClusterState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]


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
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )


# endregion Update clusters tests


# region Delete Clusters
async def test_delete_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

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


async def test_force_delete_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ClusterFactory(status__state=ClusterState.OFFLINE)
    await db.put(data)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/clusters/{data.metadata.name}?force=True"
    )

    assert resp.status == 200

    received = Cluster.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Cluster, namespace="testing", name=data.metadata.name)
    assert deleted is None


# endregion Delete
