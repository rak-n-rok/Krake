import asyncio
from contextlib import suppress
from copy import deepcopy
from textwrap import dedent

from aiohttp import web
from aiohttp.test_utils import TestServer as Server
import pytz
import yaml
from krake.data.config import TlsClientConfiguration, TlsServerConfiguration
from kubernetes_asyncio.client import V1Status, V1Service, V1ServiceSpec, V1ServicePort

from krake.api.app import create_app
from krake.controller import create_ssl_context
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes import (
    KubernetesController,
    register_service,
    unregister_service,
)
from krake.client import Client
from krake.test_utils import server_endpoint

from tests.factories.fake import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)
from tests.controller.kubernetes import nginx_manifest, hooks_config


async def test_app_reception(aiohttp_server, config, db, loop):
    cluster = ClusterFactory()

    # Pending and not scheduled
    pending = ApplicationFactory(
        status__state=ApplicationState.PENDING, status__is_scheduled=False
    )
    # Running and not scheduled
    waiting = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=False,
        status__running_on=resource_ref(cluster),
    )
    # Running and scheduled
    scheduled = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster),
    )
    # Failed and scheduled
    failed = ApplicationFactory(
        status__state=ApplicationState.FAILED,
        status__is_scheduled=True,
        status__running_on=None,
    )
    # Running and deleted without finalizers
    deleted = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster),
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )
    # Running, not scheduled and deleted without finalizers
    deleted_with_finalizer = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=False,
        status__running_on=resource_ref(cluster),
        metadata__finalizers=["kubernetes_resources_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )
    # Failed, not scheduled and deleted with finalizers
    deleted_and_failed_with_finalizer = ApplicationFactory(
        status__is_scheduled=False,
        status__running_on=resource_ref(cluster),
        status__state=ApplicationState.FAILED,
        metadata__finalizers=["kubernetes_resources_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    assert pending.status.scheduled is None
    assert waiting.status.scheduled < waiting.metadata.modified
    assert scheduled.status.scheduled >= scheduled.metadata.modified
    assert failed.status.scheduled >= failed.metadata.modified

    await db.put(cluster)
    await db.put(pending)
    await db.put(waiting)
    await db.put(scheduled)
    await db.put(failed)
    await db.put(deleted)
    await db.put(deleted_with_finalizer)
    await db.put(deleted_and_failed_with_finalizer)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await controller.prepare(client)  # need to be called explicitly
        await controller.reflector.list_resource()

    assert pending.metadata.uid not in controller.queue.dirty
    assert waiting.metadata.uid not in controller.queue.dirty
    assert scheduled.metadata.uid in controller.queue.dirty
    assert failed.metadata.uid not in controller.queue.dirty
    assert deleted.metadata.uid not in controller.queue.dirty
    assert deleted_with_finalizer.metadata.uid in controller.queue.dirty
    assert deleted_and_failed_with_finalizer.metadata.uid in controller.queue.dirty


async def test_app_creation(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=list(
            yaml.safe_load_all(
                """---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: nginx-demo
            spec:
              selector:
                matchLabels:
                  app: nginx
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
        ),
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_update(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    deleted = set()
    patched = set()

    @routes.patch("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def patch_deployment(request):
        patched.add(request.match_info["name"])
        return web.Response(status=200)

    @routes.delete("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def delete_deployment(request):
        deleted.add(request.match_info["name"])
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        deployments = ("nginx-demo-1", "nginx-demo-2", "nginx-demo-3")
        if request.match_info["name"] in deployments:
            return web.Response(status=200)
        assert False

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        status__manifest=list(
            yaml.safe_load_all(
                dedent(
                    """
                    ---
                    apiVersion: apps/v1
                    kind: Deployment
                    metadata:
                      name: nginx-demo-1
                    spec:
                      selector:
                        matchLabels:
                          app: nginx
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
                    ---
                    apiVersion: apps/v1
                    kind: Deployment
                    metadata:
                      name: nginx-demo-2
                    spec:
                      selector:
                        matchLabels:
                          app: nginx
                      template:
                        metadata:
                          labels:
                            app: nginx
                        spec:
                          containers:
                          - name: nginx
                            image: nginx:1.7.9
                            ports:
                            - containerPort: 433
                    ---
                    apiVersion: apps/v1
                    kind: Deployment
                    metadata:
                      name: nginx-demo-3
                    spec:
                      selector:
                        matchLabels:
                          app: nginx
                      template:
                        metadata:
                          labels:
                            app: nginx
                        spec:
                          containers:
                          - name: nginx
                            image: nginx:1.7.9
                            ports:
                            - containerPort: 8080
                    """
                )
            )
        ),
        spec__manifest=list(
            yaml.safe_load_all(
                dedent(
                    """
                    ---
                    # Deployment "nginx-demo-1" was removed
                    # Deployment "nginx-demo-2" is unchanged
                    apiVersion: apps/v1
                    kind: Deployment
                    metadata:
                      name: nginx-demo-2
                    spec:
                      selector:
                        matchLabels:
                          app: nginx
                      template:
                        metadata:
                          labels:
                            app: nginx
                        spec:
                          containers:
                          - name: nginx
                            image: nginx:1.7.9
                            ports:
                            - containerPort: 433
                    ---
                    apiVersion: apps/v1
                    kind: Deployment
                    metadata:
                      name: nginx-demo-3
                    spec:
                      selector:
                        matchLabels:
                          app: nginx
                      template:
                        metadata:
                          labels:
                            app: nginx
                        spec:
                          containers:
                          - name: nginx
                            image: nginx:1.7.10  # updated image version
                            ports:
                            - containerPort: 8080
                    """
                )
            )
        ),
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

    assert "nginx-demo-1" in deleted
    assert "nginx-demo-3" in patched

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_migration(aiohttp_server, config, db, loop):
    """Application was scheduled to a different cluster. The controller should
    delete objects from the old cluster and create objects on the new cluster.
    """
    routes = web.RouteTableDef()

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        body = await request.json()
        request.app["created"].add(body["metadata"]["name"])
        return web.Response(status=201)

    @routes.delete("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def delete_deployment(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        if request.match_info["name"] in request.app["existing"]:
            return web.Response(status=200)
        return web.Response(status=404)

    async def make_kubernetes_api(existing=()):
        app = web.Application()
        app["created"] = set()
        app["deleted"] = set()
        app["existing"] = set(existing)  # Set of existing deployments

        app.add_routes(routes)

        return await aiohttp_server(app)

    kubernetes_server_A = await make_kubernetes_api({"nginx-demo"})
    kubernetes_server_B = await make_kubernetes_api()

    cluster_A = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server_A))
    cluster_B = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server_B))

    old_manifest = list(
        yaml.safe_load_all(
            dedent(
                """
                apiVersion: apps/v1
                kind: Deployment
                metadata:
                  name: nginx-demo
                spec:
                  selector:
                    matchLabels:
                      app: nginx
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
    )
    new_manifest = list(
        yaml.safe_load_all(
            dedent(
                """
                apiVersion: apps/v1
                kind: Deployment
                metadata:
                  name: echoserver
                spec:
                  selector:
                    matchLabels:
                      app: echo
                  template:
                    metadata:
                      labels:
                        app: echo
                    spec:
                      containers:
                      - name: echo
                        image: k8s.gcr.io/echoserver:1.4
                        ports:
                        - containerPort: 8080
        """
            )
        )
    )

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster_A),
        status__scheduled_to=resource_ref(cluster_B),
        status__manifest=old_manifest,
        spec__manifest=new_manifest,
    )

    assert resource_ref(cluster_A) in app.metadata.owners
    assert resource_ref(cluster_B) in app.metadata.owners

    await db.put(cluster_A)
    await db.put(cluster_B)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

    assert "nginx-demo" in kubernetes_server_A.app["deleted"]
    assert "echoserver" in kubernetes_server_B.app["created"]

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.status.running_on == resource_ref(cluster_B)
    assert resource_ref(cluster_A) not in stored.metadata.owners
    assert resource_ref(cluster_B) in stored.metadata.owners


async def test_app_multi_migration(aiohttp_server, config, db, loop):
    """Migrating an application back and forth between num_clusters clusters,
    num_cycles times.

    First the application is scheduled to an initial cluster.

    Then it is migrated between the num_clusters clusters (one after the other)
    num_cycles times.

    After each scheduling we assert that the kubernetes controller behaves correctly.
    In particular, we verify that the kubernetes controller:

    - correctly updates
        - application.status.state
        - application.status.running_on
        - application.status.scheduled_to
        - application.metadata.owners
    - correctly calls the servers on the clusters involved, i.e.,
        - creates the application on the target cluster
        - when migrating the application, deletes it from the start cluster
    """

    # In this test we want to perform migration, i.e, num_cycles must be > 0.
    # If num_cycles == 0 we only create an application, but do not migrate it.
    num_cycles = 3
    # In this test we want to migrate an application between clusters,
    # i.e, num_clusters must be > 1.
    num_clusters = 4

    routes = web.RouteTableDef()
    app_categories = ["created", "deleted", "existing"]

    def clear_server(srv):
        """
        Reset the created, deleted and existing sets of a cluster kubernetes server
        Args:
            srv (TestServer): server of a kubernetes cluster
        """
        for c in app_categories:
            srv.app[c].clear()

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        body = await request.json()
        request.app["created"].add(body["metadata"]["name"])
        return web.Response(status=201)

    @routes.delete("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        if request.match_info["name"] in request.app["existing"]:
            return web.Response(status=200)
        return web.Response(status=404)

    async def make_kubernetes_api():
        app = web.Application()
        for category in app_categories:
            app[category] = set()
        app.add_routes(routes)
        return await aiohttp_server(app)

    def assert_owners(application, *owners):
        """
        Assert that the application is owned by exactly the clusters in owners
        Args:
            application (Application): the application
            *owners (Cluster): the clusters that are expected to be in the
                application's list of owners
        """
        assert len(owners) == len(application.metadata.owners)
        for o in owners:
            assert resource_ref(o) in application.metadata.owners

    # clusters[first_index] is the cluster where the application will be created
    first_index = 0

    deployment_manifest = yaml.safe_load(
        """---
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: nginx-demo
    spec:
      selector:
        matchLabels:
          app: nginx
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
    app_name = deployment_manifest["metadata"]["name"]

    assert num_cycles > 0
    assert num_clusters > 1

    # Create clusters and the kubernetes server on each cluster
    kube_servers = [await make_kubernetes_api() for _ in range(num_clusters)]
    clusters = [
        ClusterFactory(spec__kubeconfig=make_kubeconfig(s)) for s in kube_servers
    ]

    # Create the application
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
        status__scheduled_to=resource_ref(clusters[first_index]),
        spec__manifest=[deployment_manifest],
    )

    # Assert correct initial state before inserting the application into the db.
    assert app.status.state == ApplicationState.PENDING
    assert not app.status.running_on
    assert app.status.scheduled_to == resource_ref(clusters[first_index])
    assert_owners(app, clusters[first_index])
    assert not any(
        [kube_servers[first_index].app[category] for category in app_categories]
    )

    [await db.put(cluster) for cluster in clusters]

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # Let the kubernetes controller create the application
        await db.put(app)
        await controller.resource_received(app, start_observer=False)
        # Remove app's observer from dict to prevent the observer from being
        # stopped next time controller.resource_received(app) is called
        # (although it was not started).
        controller.observers.pop(app.metadata.uid)

        # Assert correct state after creating the application on the
        # initial cluster clusters[first_index].
        app = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert app.status.state == ApplicationState.RUNNING
        assert app.status.running_on == resource_ref(clusters[first_index])
        assert app.status.running_on == app.status.scheduled_to
        assert_owners(app, clusters[first_index])
        assert app_name in kube_servers[first_index].app["created"]
        assert app_name not in kube_servers[first_index].app["deleted"]
        assert app_name not in kube_servers[first_index].app["existing"]

        # We migrate the app from one cluster to another num_clusters*num_cycles times.
        # Initially the app is running on clusters[first_index].
        for migration in range(first_index, first_index + num_clusters * num_cycles):
            # We migrate the app from the cluster at start_index to the
            # cluster at target_index.
            start_index = migration % num_clusters
            target_index = (migration + 1) % num_clusters

            # Setup servers
            [clear_server(server) for server in kube_servers]
            kube_servers[start_index].app["existing"].add(app_name)

            # Setup app
            app.status.scheduled_to = resource_ref(clusters[target_index])
            app.metadata.owners.append(resource_ref(clusters[target_index]))
            assert_owners(app, clusters[start_index], clusters[target_index])

            # Let the kubernetes controller migrate the application from
            # clusters[start_index] to clusters[target_index]
            await db.put(app)
            await controller.resource_received(app, start_observer=False)
            # Remove app's observer from dict to prevent the observer from being
            # stopped next time controller.resource_received(app) is called
            # (although it was not started).
            controller.observers.pop(app.metadata.uid)

            # Assert correct state after migrating the application
            # from clusters[start_index] to clusters[target_index].
            app = await db.get(
                Application, namespace=app.metadata.namespace, name=app.metadata.name
            )
            assert app.status.state == ApplicationState.RUNNING
            assert app.status.running_on == resource_ref(clusters[target_index])
            assert app.status.running_on == app.status.scheduled_to
            assert_owners(app, clusters[target_index])
            assert app_name in kube_servers[start_index].app["deleted"]
            assert app_name not in kube_servers[start_index].app["created"]
            assert app_name in kube_servers[target_index].app["created"]
            assert app_name not in kube_servers[target_index].app["deleted"]


async def test_app_deletion(aiohttp_server, config, db, loop):
    kubernetes_app = web.Application()
    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    app = ApplicationFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=resource_ref(cluster),
        status__running_on=resource_ref(cluster),
        status__manifest=nginx_manifest,
        metadata__finalizers=["kubernetes_resources_deletion"],
    )
    assert resource_ref(cluster) in app.metadata.owners

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        reflector_task = loop.create_task(controller.reflector())

        await controller.handle_resource(run_once=True)
        # During deletion, the Application is updated, thus reenqueued
        assert controller.queue.size() == 1

        # The reenqueued Application is ignored, as not present on the database anymore.
        await controller.handle_resource(run_once=True)
        assert controller.queue.size() == 0

        reflector_task.cancel()

        with suppress(asyncio.CancelledError):
            await reflector_task

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored is None


async def test_register_service():
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    cluster = ClusterFactory()
    app = ApplicationFactory()
    response = V1Service(
        spec=V1ServiceSpec(
            ports=[V1ServicePort(port=80, target_port=80, node_port=1234)]
        )
    )
    await register_service(app, cluster, resource, response)

    assert app.status.services == {"nginx": "127.0.0.1:1234"}


async def test_register_service_without_spec():
    """Ensure that the old endpoint of the service is removed if the new
    service does not have and node port.
    """
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    cluster = ClusterFactory()
    app = ApplicationFactory(status__services={"nginx": "127.0.0.1:1234"})
    response = V1Service()
    await register_service(app, cluster, resource, response)
    assert app.status.services == {}


async def test_register_service_without_ports():
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    cluster = ClusterFactory()
    app = ApplicationFactory(status__services={"nginx": "127.0.0.1:1234"})
    response = V1Service(spec=V1ServiceSpec())
    await register_service(app, cluster, resource, response)
    assert app.status.services == {}


async def test_register_service_with_empty_ports():
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    cluster = ClusterFactory()
    app = ApplicationFactory(status__services={"nginx": "127.0.0.1:1234"})
    response = V1Service(spec=V1ServiceSpec(ports=[]))
    await register_service(app, cluster, resource, response)
    assert app.status.services == {}


async def test_register_service_without_node_port():
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    cluster = ClusterFactory()
    app = ApplicationFactory(status__services={"nginx": "127.0.0.1:1234"})
    response = V1Service(spec=V1ServiceSpec(ports=[]))
    await register_service(app, cluster, resource, response)
    assert app.status.services == {}


async def test_service_registration(aiohttp_server, config, db, loop):
    # Setup Kubernetes API mock server
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/api/v1/namespaces/default/services")
    async def _(request):
        return web.json_response(
            {
                "kind": "Service",
                "apiVersion": "v1",
                "metadata": {
                    "name": "nginx-demo",
                    "namespace": "default",
                    "selfLink": "/api/v1/namespaces/default/services/nginx-demo",
                    "uid": "266728ad-090a-4282-8185-9328eb673cd3",
                    "resourceVersion": "115304",
                    "creationTimestamp": "2019-07-30T15:11:15Z",
                },
                "spec": {
                    "ports": [
                        {
                            "protocol": "TCP",
                            "port": 80,
                            "targetPort": 80,
                            "nodePort": 30886,
                        }
                    ],
                    "selector": {"app": "nginx"},
                    "clusterIP": "10.107.207.206",
                    "type": "NodePort",
                    "sessionAffinity": "None",
                    "externalTrafficPolicy": "Cluster",
                },
                "status": {"loadBalancer": {}},
            }
        )

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    # Setup API Server
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=list(
            yaml.safe_load_all(
                """---
            apiVersion: v1
            kind: Service
            metadata:
              name: nginx-demo
            spec:
              type: NodePort
              selector:
                app: nginx
              ports:
              - port: 80
                protocol: TCP
                targetPort: 80
            """
            )
        ),
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    # The API server of the Kubernetes cluster listens on "127.0.0.1"
    assert stored.status.services == {"nginx-demo": "127.0.0.1:30886"}


async def test_unregister_service():
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    cluster = ClusterFactory()
    app = ApplicationFactory(status__services={"nginx": "127.0.0.1:1234"})
    response = V1Status()
    await unregister_service(app, cluster, resource, response)
    assert app.status.services == {}


async def test_unregister_service_without_previous_service():
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    cluster = ClusterFactory()
    app = ApplicationFactory(status__services={})
    response = V1Status()
    await unregister_service(app, cluster, resource, response)
    assert app.status.services == {}


async def test_service_unregistration(aiohttp_server, config, db, loop):
    # Setup Kubernetes API mock server
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.json_response(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "creationTimestamp": "2019-11-12 08:44:02+00:00",
                    "name": "nginx-demo",
                    "namespace": "default",
                    "resourceVersion": "2075568",
                    "selfLink": "/api/v1/namespaces/default/services/nginx-demo",
                    "uid": "4da165e0-e58f-4058-be44-fa393a58c2c8",
                },
                "spec": {
                    "clusterIp": "10.98.197.124",
                    "externalTrafficPolicy": "Cluster",
                    "ports": [
                        {
                            "nodePort": 30704,
                            "port": 8080,
                            "protocol": "TCP",
                            "targetPort": 8080,
                        }
                    ],
                    "selector": {"app": "echo"},
                    "sessionAffinity": "None",
                    "type": "NodePort",
                },
                "status": {"loadBalancer": {}},
            }
        )

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.json_response(
            {
                "apiVersion": "v1",
                "details": {
                    "kind": "services",
                    "name": "nginx-demo",
                    "uid": "4da165e0-e58f-4058-be44-fa393a58c2c8",
                },
                "kind": "Status",
                "metadata": {},
                "status": "Success",
            }
        )

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    # Setup API Server
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    manifest = list(
        yaml.safe_load_all(
            """---
            apiVersion: v1
            kind: Service
            metadata:
              name: nginx-demo
            spec:
              type: NodePort
              selector:
                app: nginx
              ports:
              - port: 8080
                protocol: TCP
                targetPort: 8080
        """
        )
    )
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=[],
        status__services={"nginx-demo": "127.0.0.1:30704"},
        status__manifest=manifest,
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.services == {}


async def test_complete_hook(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=list(
            yaml.safe_load_all(
                """---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: nginx-demo
            spec:
              selector:
                matchLabels:
                  app: nginx
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
        ),
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(
            server_endpoint(api_server), worker_count=0, hooks=deepcopy(hooks_config)
        )
        await controller.prepare(client)
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    for resource in stored.status.manifest:
        if resource["kind"] != "Deployment":
            continue

        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "KRAKE_TOKEN" in [env["name"] for env in container["env"]]
            assert "KRAKE_COMPLETE_URL" in [env["name"] for env in container["env"]]

    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_complete_hook_disable_by_user(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=list(
            yaml.safe_load_all(
                """---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: nginx-demo
            spec:
              selector:
                matchLabels:
                  app: nginx
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
        ),
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(
            server_endpoint(api_server), worker_count=0, hooks=deepcopy(hooks_config)
        )
        await controller.prepare(client)
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    for resource in stored.status.manifest:
        if resource["kind"] != "Deployment":
            continue

        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "env" not in container

    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_complete_hook_tls(aiohttp_server, config, pki, db, loop):
    routes = web.RouteTableDef()

    server_cert = pki.gencert("api-server")
    client_cert = pki.gencert("client")
    client_tls = TlsClientConfiguration(
        enabled=True,
        client_ca=pki.ca.cert,
        client_cert=client_cert.cert,
        client_key=client_cert.key,
    )
    ssl_context = create_ssl_context(client_tls)
    config.tls = TlsServerConfiguration(
        enabled=True, client_ca=pki.ca.cert, cert=server_cert.cert, key=server_cert.key
    )

    @routes.get("/api/v1/namespaces/default/configmaps/ca.pem")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/api/v1/namespaces/default/configmaps")
    async def _(request):
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks="complete",
        spec__manifest=list(
            yaml.safe_load_all(
                """---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: nginx-demo
            spec:
              selector:
                matchLabels:
                  app: nginx
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
        ),
    )
    await db.put(cluster)
    await db.put(app)

    server_app = create_app(config)
    api_server = Server(server_app)

    await api_server.start_server(ssl=server_app["ssl_context"])
    assert api_server.scheme == "https"

    async with Client(
        url=server_endpoint(api_server), loop=loop, ssl_context=ssl_context
    ) as client:
        controller = KubernetesController(
            server_endpoint(api_server),
            worker_count=0,
            ssl_context=ssl_context,
            hooks=deepcopy(hooks_config),
        )
        await controller.prepare(client)
        await controller.resource_received(app, start_observer=False)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    for resource in stored.status.manifest:
        if resource["kind"] != "Deployment":
            continue

        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "volumeMounts" in container
            assert "KRAKE_TOKEN" in [env["name"] for env in container["env"]]
            assert "KRAKE_COMPLETE_URL" in [env["name"] for env in container["env"]]

    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_kubernetes_controller_error_handling(aiohttp_server, config, db, loop):
    """Test the behavior of the Controller in case of a ControllerError.
    """
    failed_manifest = deepcopy(nginx_manifest)
    for resource in failed_manifest:
        resource["kind"] = "Unsupported"

    cluster = ClusterFactory(spec__custom_resources=[])
    app = ApplicationFactory(
        spec__manifest=failed_manifest,
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(cluster),
        status__manifest=[],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.queue.put(app.metadata.uid, app)
        await controller.handle_resource(run_once=True)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.state == ApplicationState.FAILED
    assert stored.status.reason.code == ReasonCode.INVALID_RESOURCE


async def test_kubernetes_api_error_handling(aiohttp_server, config, db, loop):
    """Test the behavior of the Controller in case of a Kubernetes error.
    """
    # Create an actual "kubernetes cluster" with no route, so it responds wrongly
    # to the requests of the Controller.
    kubernetes_app = web.Application()
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    app = ApplicationFactory(
        spec__manifest=nginx_manifest,
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(cluster),
        status__manifest=[],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.queue.put(app.metadata.uid, app)
        await controller.handle_resource(run_once=True)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.state == ApplicationState.FAILED
    assert stored.status.reason.code == ReasonCode.KUBERNETES_ERROR
