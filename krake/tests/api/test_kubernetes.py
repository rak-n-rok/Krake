import asyncio
import copy
import json
import pytz
import yaml
from itertools import count
from operator import attrgetter
from secrets import token_urlsafe
from copy import deepcopy
from krake.utils import now

from krake.api.app import create_app
from krake.api.helpers import HttpProblem, HttpProblemTitle
from krake.data.core import WatchEventType, WatchEvent, resource_ref, ResourceRef
from krake.data.kubernetes import (
    Application,
    ApplicationList,
    ApplicationState,
    ApplicationComplete,
    ApplicationShutdown,
    Cluster,
    ClusterList,
    ClusterBinding,
    ClusterState,
)

from tests.factories.kubernetes import (
    ClusterFactory,
    ApplicationFactory,
    ReasonFactory,
)
from tests.factories.fake import fake
from tests.controller.kubernetes import deployment_manifest
from tests.controller.kubernetes.test_tosca import (
    create_tosca_from_resources,
    CSAR_META,
)


async def test_create_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(status=None)

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    assert received.spec == data.spec
    assert received.status.state == ApplicationState.PENDING

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/applications")
        assert resp.status == 415


async def test_create_application_with_existing_name(aiohttp_client, config, db):
    existing = ApplicationFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_delete_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory()
    await db.put(data)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_add_finalizer_in_deleted_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(
        metadata__deleted=fake.date_time(), metadata__finalizers=["my-finalizer"]
    )
    await db.put(data)

    data.metadata.finalizers = ["a-different-finalizer"]
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 409
    body = await resp.json()
    assert (
        body["detail"] == "Finalizers can only be removed"
        " if a deletion is in progress."
    )


async def test_delete_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete(
        "/kubernetes/namespaces/testing/applications/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "delete"):
        resp = await client.delete(
            "/kubernetes/namespaces/testing/applications/my-resource"
        )
        assert resp.status == 404


async def test_delete_application_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = ApplicationFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_list_applications(aiohttp_client, config, db):
    resources = [
        ApplicationFactory(status__state=ApplicationState.PENDING),
        ApplicationFactory(status__state=ApplicationState.CREATING),
        ApplicationFactory(status__state=ApplicationState.RECONCILING),
        ApplicationFactory(status__state=ApplicationState.MIGRATING),
        ApplicationFactory(status__state=ApplicationState.DELETING),
        ApplicationFactory(
            metadata__namespace="other", status__state=ApplicationState.RUNNING
        ),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 200

    body = await resp.json()
    received = ApplicationList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources[:-1], key=key)


async def test_list_applications_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "list"):
        resp = await client.get("/kubernetes/namespaces/testing/applications")
        assert resp.status == 200


async def test_watch_applications(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]

    async def watch(created):
        resp = await client.get(
            "/kubernetes/namespaces/testing/applications?watch&heartbeat=0"
        )
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Application.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Applications
        for data in resources:
            resp = await client.post(
                f"/kubernetes/namespaces/{data.metadata.namespace}/applications",
                json=data.serialize(),
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/applications/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Application.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_list_all_applications(aiohttp_client, config, db):
    resources = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]
    for elt in resources:
        await db.put(elt)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/kubernetes/applications")
    assert resp.status == 200

    body = await resp.json()
    received = ApplicationList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(resources, key=key)


async def test_list_all_applications_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "list"):
        resp = await client.get("/kubernetes/applications")
        assert resp.status == 200


async def test_watch_all_applications(aiohttp_client, config, db, loop):
    client = await aiohttp_client(create_app(config=config))
    resources = [
        ApplicationFactory(metadata__namespace="testing"),
        ApplicationFactory(metadata__namespace="system"),
    ]

    async def watch(created):
        resp = await client.get("/kubernetes/applications?watch&heartbeat=0")
        assert resp.status == 200
        created.set_result(None)

        for i in count():
            line = await resp.content.readline()
            assert line, "Unexpected EOF"

            event = WatchEvent.deserialize(json.loads(line.decode()))
            data = Application.deserialize(event.object)

            if i == 0:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 1:
                assert event.type == WatchEventType.ADDED
                assert data.metadata.name == resources[1].metadata.name
                assert data.spec == resources[1].spec
                assert data.status.state == ApplicationState.PENDING
            elif i == 2:
                assert event.type == WatchEventType.MODIFIED
                assert data.metadata.name == resources[0].metadata.name
                assert data.spec == resources[0].spec
                assert data.status.state == ApplicationState.PENDING
                return
            elif i == 3:
                assert False

    async def modify(created):
        # Wait for watcher to be established
        await created

        # Create the Applications
        for data in resources:
            resp = await client.post(
                "/kubernetes/namespaces/testing/applications", json=data.serialize()
            )
            assert resp.status == 200

        resp = await client.delete(
            f"/kubernetes/namespaces/testing/applications/{resources[0].metadata.name}"
        )
        assert resp.status == 200

        received = Application.deserialize(await resp.json())
        assert resource_ref(received) == resource_ref(resources[0])
        assert received.metadata.deleted is not None

    created = loop.create_future()
    watching = loop.create_task(watch(created))
    modifying = loop.create_task(modify(created))

    await asyncio.wait_for(asyncio.gather(modifying, watching), timeout=3)


async def test_read_application(aiohttp_client, config, db):
    data = ApplicationFactory()
    await db.put(data)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}"
    )

    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received == data


async def test_read_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config))

    resp = await client.get("/kubernetes/namespaces/testing/applications/my-resource")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "get"):
        resp = await client.get(
            "/kubernetes/namespaces/testing/applications/my-resource"
        )
        assert resp.status == 404


new_manifest = list(
    yaml.safe_load_all(
        """---
apiVersion: v1
kind: Pod
metadata:
  name: busybox-sleep
  namespace: default
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
  namespace: default
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

new_observer_schema = list(
    yaml.safe_load_all(
        """---
apiVersion: v1
kind: Pod
metadata:
  name: busybox-sleep
  namespace: null
---
apiVersion: v1
kind: Pod
metadata:
  name: busybox-sleep-less
  namespace: null
"""
    )
)


async def test_update_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(data)
    data.spec.manifest = new_manifest
    data.spec.observer_schema = new_observer_schema

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.status.state == data.status.state
    assert received.spec.manifest == new_manifest
    assert received.spec.observer_schema == new_observer_schema

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_to_delete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["cascade_deletion"],
    )
    await db.put(data)

    # Delete the Application
    data.metadata.finalizers = []
    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)

    # The Application should be deleted from the database
    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored is None


async def test_update_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put("/kubernetes/namespaces/testing/applications/my-resource")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource"
        )
        assert resp.status == 415


async def test_update_application_no_changes(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory()
    await db.put(data)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400


async def test_update_application_immutable_field(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory()
    await db.put(data)
    data.metadata.namespace = "override"

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 400

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.UPDATE_ERROR
    assert problem.detail == "Trying to update an immutable field: namespace"


async def test_create_application_tosca_from_dict(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    tosca = create_tosca_from_resources([deployment_manifest])
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__tosca=tosca,
    )

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    assert received.status.state == ApplicationState.PENDING
    assert received.spec == data.spec

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_application_tosca_from_url(
    aiohttp_client, config, db, file_server
):
    client = await aiohttp_client(create_app(config=config))

    tosca_url = file_server(create_tosca_from_resources([deployment_manifest]))
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__tosca=tosca_url,
    )

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    assert received.status.state == ApplicationState.PENDING
    assert received.spec == data.spec

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_application_csar_from_url(
    aiohttp_client, config, db, archive_files, file_server
):
    client = await aiohttp_client(create_app(config=config))

    tosca = create_tosca_from_resources([deployment_manifest])
    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("tosca.yaml", tosca),
            (
                "TOSCA-Metadata/TOSCA.meta",
                CSAR_META.format(entry_definition="tosca.yaml"),
            ),
        ],
    )
    csar_url = file_server(csar_path, file_name="example.csar")
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__csar=csar_url,
    )

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
    assert received.status.state == ApplicationState.PENDING
    assert received.spec == data.spec

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_tosca_from_dict(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    tosca = create_tosca_from_resources([deployment_manifest])
    data = ApplicationFactory(
        spec__manifest=[deployment_manifest],
        spec__tosca=tosca,
        status__state=ApplicationState.PENDING,
    )
    await db.put(data)
    updated_tosca = copy.deepcopy(tosca)
    updated_tosca["topology_template"]["node_templates"][
        deployment_manifest["metadata"]["name"]
    ]["properties"]["spec"] = new_manifest[0]
    data.spec.manifest = []
    data.spec.tosca = updated_tosca
    data.spec.observer_schema = [new_observer_schema[0]]

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.status.state == data.status.state
    assert received.spec.tosca == updated_tosca
    assert received.spec.observer_schema == [new_observer_schema[0]]

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_tosca_from_url(
    aiohttp_client, config, db, file_server
):
    client = await aiohttp_client(create_app(config=config))

    tosca_url = file_server(create_tosca_from_resources([deployment_manifest]))
    data = ApplicationFactory(
        spec__manifest=[deployment_manifest],
        spec__tosca=tosca_url,
        status__state=ApplicationState.PENDING,
    )
    await db.put(data)
    # Update CSAR URL
    tosca_updated = fake.url() + "tosca_updated.yaml"
    data.spec.manifest = []
    data.spec.tosca = tosca_updated
    data.spec.observer_schema = [new_observer_schema[0]]

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.status.state == data.status.state
    assert received.spec.tosca == tosca_updated
    assert received.spec.observer_schema == [new_observer_schema[0]]

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_csar_from_url(
    aiohttp_client, config, db, archive_files, file_server
):
    client = await aiohttp_client(create_app(config=config))

    tosca = create_tosca_from_resources([deployment_manifest])
    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("tosca.yaml", tosca),
            (
                "TOSCA-Metadata/TOSCA.meta",
                CSAR_META.format(entry_definition="tosca.yaml"),
            ),
        ],
    )
    csar_url = file_server(csar_path, file_name="example.csar")
    data = ApplicationFactory(
        spec__manifest=[deployment_manifest],
        spec__csar=csar_url,
        status__state=ApplicationState.PENDING,
    )
    await db.put(data)
    # Update CSAR URL
    csar_updated = fake.url() + "csar_updated.csar"
    data.spec.manifest = []
    data.spec.csar = csar_updated
    data.spec.observer_schema = [new_observer_schema[0]]

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.status.state == data.status.state
    assert received.spec.csar == csar_updated
    assert received.spec.observer_schema == [new_observer_schema[0]]

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(status__state=ApplicationState.PENDING)
    cluster = ClusterFactory()

    await db.put(data)
    await db.put(cluster)

    assert not data.metadata.owners, "There are no owners"
    assert data.status.scheduled_to is None, "Application is not scheduled"
    assert data.status.running_on is None, "Application is not running on a cluster"

    cluster_ref = resource_ref(cluster)
    binding = ClusterBinding(cluster=cluster_ref)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/binding",
        json=binding.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Application"

    assert received.status.scheduled_to == cluster_ref
    assert received.status.scheduled
    assert received.status.scheduled == received.status.kube_controller_triggered
    assert received.status.running_on is None
    assert received.status.state == ApplicationState.PENDING
    assert cluster_ref in received.metadata.owners

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_binding_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/applications/my-resource/binding"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/binding", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource/binding"
        )
        assert resp.status == 415


async def test_update_application_complete(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    token = token_urlsafe()
    data = ApplicationFactory(status__complete_token=token)
    await db.put(data)

    complete = ApplicationComplete(token=token)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/complete",
        json=complete.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_complete_unauthorized(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    token = token_urlsafe()
    data = ApplicationFactory(status__complete_token=token)
    await db.put(data)

    complete = ApplicationComplete()

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/complete",
        json=complete.serialize(),
    )
    assert resp.status == 401


async def test_update_application_complete_disabled(aiohttp_client, config, db):
    """An Application for which the "complete" hook is not set should not be able to be
    deleted.
    """
    client = await aiohttp_client(create_app(config=config))

    app = ApplicationFactory(status__complete_token=None)
    await db.put(app)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/complete",
        json=ApplicationComplete(token=None).serialize(),
    )
    assert resp.status == 401

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.metadata.deleted is None


async def test_update_application_complete_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/applications/my-resource/complete"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/complete", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource/complete"
        )
        assert resp.status == 415


async def test_update_application_shutdown(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    token = token_urlsafe()
    data = ApplicationFactory(
        status__shutdown_token=token,
        status__state=ApplicationState.WAITING_FOR_CLEANING,
        metadata__deleted=now(),
    )
    await db.put(data)

    shutdown = ApplicationShutdown(token=token)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/shutdown",
        json=shutdown.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_shutdown_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/applications/my-resource/complete"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/shutdown", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource/shutdown"
        )
        assert resp.status == 415


async def test_retry_application_shutdown(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    token = token_urlsafe()
    data = ApplicationFactory(
        status__shutdown_token=token,
        status__state=ApplicationState.DEGRADED,
        metadata__deleted=now(),
    )
    await db.put(data)

    shutdown = ApplicationShutdown(token=token)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/retry",
        json=shutdown.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.status.shutdown_grace_period is None

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_retry_application_shutdown_wrong_state(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    token = token_urlsafe()
    app = ApplicationFactory(
        status__shutdown_token=token,
        status__state=ApplicationState.RUNNING,
        metadata__deleted=now(),
    )
    await db.put(app)

    shutdown = ApplicationShutdown(token=token)

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/retry",
        json=shutdown.serialize(),
    )
    assert resp.status == 400

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.metadata.deleted is not None


async def test_update_application_status(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(data)

    data.status.state = ApplicationState.FAILED
    data.status.reason = ReasonFactory()
    data.status.cluster = ResourceRef(
        api="kubernetes", kind="Cluster", namespace="testing", name="test-cluster"
    )
    data.status.services = {"service1": "127.0.0.1:38531"}

    resp = await client.put(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}/status",
        json=data.serialize(),
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.status == data.status

    # Only the "modified" attribute of the metadata should be modified
    received_copy = deepcopy(received)
    received_copy.metadata.modified = data.metadata.modified
    assert received_copy.metadata == data.metadata

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_update_application_status_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.put(
        "/kubernetes/namespaces/testing/applications/my-resource/status"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications/status", "update"):
        resp = await client.put(
            "/kubernetes/namespaces/testing/applications/my-resource/status"
        )
        assert resp.status == 415


async def test_create_cluster(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ClusterFactory()

    resp = await client.post(
        "/kubernetes/namespaces/testing/clusters", json=data.serialize()
    )
    assert resp.status == 200
    received = Cluster.deserialize(await resp.json())

    assert received.metadata.created
    assert received.metadata.modified
    assert received.metadata.namespace == "testing"
    assert received.metadata.uid
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
