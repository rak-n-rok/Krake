from operator import attrgetter
import yaml

from krake.api.app import create_app
from krake.client import Client
from krake.client.kubernetes import KubernetesApi
from krake.data.kubernetes import (
    Application,
    ApplicationList,
    ApplicationState,
    ClusterState,
    ClusterList,
    Cluster,
)
from krake.test_utils import with_timeout

from factories.kubernetes import ApplicationFactory
from tests.factories.kubernetes import ClusterFactory

manifest = list(
    yaml.safe_load_all(
        """---
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
    )
)


async def test_list_applications(aiohttp_server, config, db, loop):
    # Populate database
    data = [ApplicationFactory(), ApplicationFactory()]
    for app in data:
        await db.put(app)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        apps = await kubernetes_api.list_applications(namespace="testing")
        assert isinstance(apps, ApplicationList)

    key = attrgetter("metadata.name")
    assert sorted(apps.items, key=key) == sorted(data, key=key)


async def test_create_application(aiohttp_server, config, db, loop):
    data = ApplicationFactory(status__state=ApplicationState.PENDING)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_application(
            namespace=data.metadata.namespace, body=data
        )

    assert received.spec == data.spec
    assert received.status.state == ApplicationState.PENDING

    stored, _ = await db.get(
        Application, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


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


async def test_update_application(aiohttp_server, config, db, loop):
    app = ApplicationFactory(status__state=ApplicationState.RUNNING)
    await db.put(app)
    app.spec.manifest = updated_manifest

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

    # State is changed through an update
    assert received.spec.manifest == updated_manifest
    assert received.status.state == app.status.state

    stored, _ = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.spec.manifest == updated_manifest
    assert stored.status.state == app.status.state


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


async def aenumerate(iterable):
    i = 0
    async for item in iterable:
        yield i, item
        i += 1


@with_timeout(3)
async def test_watch_applications_in_namespace(aiohttp_server, config, db, loop):
    data = [ApplicationFactory(), ApplicationFactory(), ApplicationFactory()]

    async def modify():
        for app in data:
            await db.put(app)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_applications(namespace="testing") as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


@with_timeout(3)
async def test_watch_applications_all_namespaces(aiohttp_server, config, db, loop):
    data = [
        ApplicationFactory(metadata__namespace="testing"),
        ApplicationFactory(metadata__namespace="default"),
    ]

    async def modify():
        for app in data:
            await db.put(app)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_all_applications() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_list_clusters(aiohttp_server, config, db, loop):
    # Populate database
    data = [
        ClusterFactory(status__state=ClusterState.PENDING),
        ClusterFactory(status__state=ClusterState.RUNNING),
    ]
    for cluster in data:
        await db.put(cluster)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        clusters = await kubernetes_api.list_clusters(namespace="testing")
        assert isinstance(clusters, ClusterList)

    key = attrgetter("metadata.name")
    assert sorted(clusters.items, key=key) == sorted(data, key=key)


async def test_create_cluster(aiohttp_server, config, db, loop):
    data = ClusterFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.create_cluster(
            namespace=data.metadata.namespace, body=data
        )

    assert received.spec == data.spec

    stored, _ = await db.get(
        Cluster, namespace=data.metadata.namespace, name=data.metadata.name
    )
    assert stored == received


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


@with_timeout(3)
async def test_watch_clusters_in_namespace(aiohttp_server, config, db, loop):
    data = [ClusterFactory(), ClusterFactory(), ClusterFactory()]

    async def modify():
        for cluster in data:
            await db.put(cluster)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_clusters(namespace="testing") as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


@with_timeout(3)
async def test_watch_clusters_all_namespaces(aiohttp_server, config, db, loop):
    data = [
        ClusterFactory(metadata__namespace="testing"),
        ClusterFactory(metadata__namespace="default"),
    ]

    async def modify():
        for cluster in data:
            await db.put(cluster)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        async with kubernetes_api.watch_all_clusters() as watcher:
            modifying = loop.create_task(modify())

            async for i, event in aenumerate(watcher):
                expected = data[i]
                assert event.object == expected

                if i == len(data) - 1:
                    break

            await modifying


async def test_delete_cluster(aiohttp_server, config, db, loop):
    cluster = ClusterFactory(metadata__finalizers="keep-me")
    await db.put(cluster)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.delete_cluster(
            namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )

    assert received.spec == cluster.spec
    assert received.metadata.deleted

    stored, _ = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored == received
