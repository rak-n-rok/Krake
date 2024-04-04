import copy
import pytz
from secrets import token_urlsafe
from copy import deepcopy

import yaml

from krake.utils import now

from krake.api.app import create_app
from krake.api.helpers import HttpProblem, HttpProblemTitle
from krake.data.core import resource_ref, ResourceRef
from krake.data.kubernetes import (
    Application,
    ApplicationState,
    ApplicationComplete,
    ApplicationShutdown,
    ClusterBinding,
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


# region Manifests
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
# endregion Manifests


# region Application Update
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


# endregion Application Update


# region Application binding
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


# endregion Application binding


# region Application complete
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


# endregion Application complete


# region Application shutdown
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


# endregion Application shutdown


# region Application status
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


# endregion Application status
