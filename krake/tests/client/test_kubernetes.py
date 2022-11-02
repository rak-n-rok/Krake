import copy
import yaml
from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.client.kubernetes import KubernetesApi
from krake.data.core import resource_ref, ResourceRef, WatchEventType
from krake.data.kubernetes import (
    Application,
    Cluster,
    ApplicationState,
    ClusterBinding,
    ApplicationComplete,
    ClusterState,
)
from krake.test_utils import with_timeout, aenumerate
from tests.factories import fake

from tests.factories.kubernetes import ApplicationFactory, ClusterFactory, ReasonFactory
from tests.controller.kubernetes import deployment_manifest
from tests.controller.kubernetes.test_tosca import (
    create_tosca_from_resources,
    CSAR_META,
)


async def test_create_application(aiohttp_server, config, db, loop):
    data = ApplicationFactory(status__state=ApplicationState.PENDING)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_application(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    assert stored.spec == data.spec


async def test_delete_application(aiohttp_server, config, db, loop):
    data = ApplicationFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.delete_application(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.deleted is not None

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_list_applications(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_applications(
            namespace="testing",
        )

    assert received.api == "kubernetes"
    assert received.kind == "ApplicationList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_applications(aiohttp_server, config, db, loop):
    data = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_applications(
            namespace="testing",
        ) as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                # '1' because of the offset length-index and '1' for the resource in
                # another namespace
                if i == len(data) - 2:
                    break

            await modifying


async def test_list_all_applications(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(),
        ApplicationFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_all_applications()

    assert received.api == "kubernetes"
    assert received.kind == "ApplicationList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_applications(aiohttp_server, config, db, loop):
    data = [
        ApplicationFactory(metadata__namespace="testing"),
        ApplicationFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_all_applications() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_application(aiohttp_server, config, db, loop):
    data = ApplicationFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.read_application(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


updated_manifest = list(
    yaml.safe_load_all(
        """---
apiVersion: apps/v1 # for versions before 1.9.0 use apps/v1beta2
kind: Deployment
metadata:
  name: nginx-deployment
spec:
  selector:
    matchLabels:
      app: nginx
  replicas: 2 # tells deployment to run 2 pods matching the template
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.7.9
        ports:
        - containerPort: 80
"""
    )
)


updated_observer_schema = list(
    yaml.safe_load_all(
        """---
apiVersion: apps/v1 # for versions before 1.9.0 use apps/v1beta2
kind: Deployment
metadata:
  name: nginx-deployment
  namespace: null
"""
    )
)


async def test_update_application(aiohttp_server, config, db, loop):
    data = ApplicationFactory(status__state=ApplicationState.RUNNING)
    await db.put(data)
    data.spec.manifest = updated_manifest
    data.spec.observer_schema = updated_observer_schema

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.manifest == updated_manifest
    assert received.status.state == data.status.state

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored.spec.manifest == updated_manifest
    assert stored.spec.observer_schema == updated_observer_schema
    assert stored.status.state == data.status.state


async def test_create_application_tosca_from_dict(aiohttp_server, config, db, loop):
    tosca = create_tosca_from_resources([deployment_manifest])
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__tosca=tosca,
        status__state=ApplicationState.RUNNING,
    )

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_application(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_create_application_tosca_from_url(
    aiohttp_server, config, db, loop, file_server
):
    tosca_url = file_server(create_tosca_from_resources([deployment_manifest]))
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__tosca=tosca_url,
        status__state=ApplicationState.RUNNING,
    )

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_application(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_create_application_csar_from_url(
    aiohttp_server, config, db, loop, archive_files, file_server
):
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
        status__state=ApplicationState.RUNNING,
    )

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_application(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_application_tosca_from_dict(aiohttp_server, config, db, loop):
    tosca = create_tosca_from_resources([deployment_manifest])
    data = ApplicationFactory(
        spec__manifest=[],
        spec__tosca=tosca,
        status__state=ApplicationState.RUNNING,
    )
    await db.put(data)
    updated_tosca = copy.deepcopy(tosca)
    updated_tosca["topology_template"]["node_templates"][
        deployment_manifest["metadata"]["name"]
    ]["properties"]["spec"] = updated_manifest[0]
    data.spec.manifest = []
    data.spec.tosca = updated_tosca
    data.spec.observer_schema = updated_observer_schema

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.tosca == updated_tosca
    assert received.status.state == data.status.state

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    assert stored.spec.tosca == updated_tosca
    assert stored.spec.observer_schema == updated_observer_schema
    assert stored.status.state == data.status.state


async def test_update_application_tosca_from_url(
    aiohttp_server, config, db, loop, file_server
):
    tosca_url = file_server(create_tosca_from_resources([deployment_manifest]))
    data = ApplicationFactory(
        spec__manifest=[],
        spec__tosca=tosca_url,
        status__state=ApplicationState.RUNNING,
    )
    await db.put(data)
    # Update CSAR URL
    tosca_updated = fake.url() + "tosca_updated.yaml"
    data.spec.manifest = []
    data.spec.tosca = tosca_updated
    data.spec.observer_schema = updated_observer_schema

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.tosca == tosca_updated
    assert received.status.state == data.status.state

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    assert stored.spec.tosca == tosca_updated
    assert stored.spec.observer_schema == updated_observer_schema
    assert stored.status.state == data.status.state


async def test_update_application_csar_from_url(
    aiohttp_server, config, db, loop, archive_files, file_server
):
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
        spec__manifest=[],
        spec__csar=csar_url,
        status__state=ApplicationState.RUNNING,
    )
    await db.put(data)
    # Update CSAR URL
    csar_updated = fake.url() + "csar_updated.csar"

    data.spec.manifest = []
    data.spec.csar = csar_updated
    data.spec.observer_schema = updated_observer_schema

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.csar == csar_updated
    assert received.status.state == data.status.state

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received
    assert stored.spec.csar == csar_updated
    assert stored.spec.observer_schema == updated_observer_schema
    assert stored.status.state == data.status.state


async def test_update_application_binding(aiohttp_server, config, db, loop):
    data = ApplicationFactory(status__state=ApplicationState.PENDING)
    await db.put(data)
    cluster = ClusterFactory()
    await db.put(cluster)

    cluster_ref = resource_ref(cluster)
    binding = ClusterBinding(cluster=cluster_ref)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application_binding(
            namespace=data.metadata.namespace, name=data.metadata.name, body=binding
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.status.scheduled_to == cluster_ref
    assert received.status.running_on is None
    assert received.status.state == ApplicationState.PENDING
    assert cluster_ref in received.metadata.owners

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored.status.scheduled_to == cluster_ref
    assert stored.status.running_on is None
    assert stored.status.state == ApplicationState.PENDING
    assert cluster_ref in stored.metadata.owners


async def test_update_application_complete(aiohttp_server, config, db, loop):
    token = "a_random_token"
    data = ApplicationFactory(status__complete_token=token)
    await db.put(data)

    complete = ApplicationComplete(token=token)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application_complete(
            namespace=data.metadata.namespace, name=data.metadata.name, body=complete
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.metadata.deleted

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored.metadata.deleted


async def test_update_application_status(aiohttp_server, config, db, loop):
    data = ApplicationFactory()
    await db.put(data)
    data.status.state = ApplicationState.FAILED
    data.status.reason = ReasonFactory()
    data.status.cluster = ResourceRef(
        api="kubernetes", kind="Cluster", namespace="testing", name="test-cluster"
    )
    data.status.services = {"service1": "127.0.0.1:38531"}
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Application"
    assert received.status == data.status

    stored = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_create_cluster(aiohttp_server, config, db, loop):
    data = ClusterFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_cluster(
            namespace=data.metadata.namespace, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace == "testing"
    assert received.metadata.created
    assert received.metadata.modified
    assert received.spec == data.spec

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_delete_cluster(aiohttp_server, config, db, loop):
    data = ClusterFactory(metadata__finalizers="keep-me")
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.delete_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert received.metadata.deleted is not None
    assert received.spec == data.spec

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_list_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_clusters(namespace="testing")

    assert received.api == "kubernetes"
    assert received.kind == "ClusterList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data[:-1], key=key)


@with_timeout(3)
async def test_watch_clusters(aiohttp_server, config, db, loop):
    data = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_clusters(namespace="testing") as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                # '1' because of the offset length-index and '1' for the resource in
                # another namespace
                if i == len(data) - 2:
                    break

            await modifying


async def test_list_all_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(),
        ClusterFactory(metadata__namespace="other"),
    ]
    for elt in data:
        await db.put(elt)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.list_all_clusters()

    assert received.api == "kubernetes"
    assert received.kind == "ClusterList"

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(data, key=key)


@with_timeout(3)
async def test_watch_all_clusters(aiohttp_server, config, db, loop):
    data = [
        ClusterFactory(metadata__namespace="testing"),
        ClusterFactory(metadata__namespace="default"),
    ]

    async def modify():
        for elt in data:
            await db.put(elt)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_all_clusters() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.type == WatchEventType.ADDED
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_read_cluster(aiohttp_server, config, db, loop):
    data = ClusterFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.read_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name
        )
        assert received == data


async def test_update_cluster(aiohttp_server, config, db, loop):
    data = ClusterFactory(spec__custom_resources=[])
    await db.put(data)
    data.spec.custom_resources = ["A", "B"]

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_cluster(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"
    assert data.metadata.modified < received.metadata.modified
    assert received.spec.custom_resources == data.spec.custom_resources

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


async def test_update_cluster_status(aiohttp_server, config, db, loop):
    data = ClusterFactory()
    await db.put(data)

    data.status.state = ClusterState.FAILING_METRICS
    data.status.metrics_reasons = {"my-metric": ReasonFactory()}

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_cluster_status(
            namespace=data.metadata.namespace, name=data.metadata.name, body=data
        )

    assert received.api == "kubernetes"
    assert received.kind == "Cluster"

    assert received.status.state == ClusterState.FAILING_METRICS
    assert list(received.status.metrics_reasons.keys()) == ["my-metric"]

    stored = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored.status.state == ClusterState.FAILING_METRICS
    assert list(stored.status.metrics_reasons.keys()) == ["my-metric"]
