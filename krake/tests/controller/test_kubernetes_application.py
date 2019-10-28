from copy import deepcopy
from textwrap import dedent

from aiohttp import web
import pytz
import yaml

from krake.api.app import create_app
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes_application import ApplicationController
from krake.client import Client
from krake.test_utils import server_endpoint

from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory, make_kubeconfig


async def test_app_reception(aiohttp_server, config, db, loop):
    # Pending and not scheduled
    pending = ApplicationFactory(
        status__state=ApplicationState.PENDING, status__is_scheduled=False
    )
    # Running and not scheduled
    waiting = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__is_scheduled=False
    )
    # Running and scheduled
    scheduled = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__is_scheduled=True
    )
    # Failed and scheduled
    failed = ApplicationFactory(
        status__state=ApplicationState.FAILED, status__is_scheduled=True
    )
    # Running and deleted without finalizers
    deleted = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )
    # Running, not scheduled and deleted without finalizers
    deleted_with_finalizer = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=False,
        metadata__finalizers=["kubernetes_resources_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )
    # Failed, not scheduled and deleted with finalizers
    deleted_and_failed_with_finalizer = ApplicationFactory(
        status__is_scheduled=False,
        status__state=ApplicationState.FAILED,
        metadata__finalizers=["kubernetes_resources_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    assert pending.status.scheduled is None
    assert waiting.status.scheduled < waiting.metadata.modified
    assert scheduled.status.scheduled >= scheduled.metadata.modified
    assert failed.status.scheduled >= failed.metadata.modified

    await db.put(pending)
    await db.put(waiting)
    await db.put(scheduled)
    await db.put(failed)
    await db.put(deleted)
    await db.put(deleted_with_finalizer)
    await db.put(deleted_and_failed_with_finalizer)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(server_endpoint(server), worker_count=0)
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


nginx_manifest = list(
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
---
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
)


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
        controller = ApplicationController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app)

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
        return web.Response(status=404)

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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app)

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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app)

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
        spec__manifest=nginx_manifest,
        metadata__finalizers=["kubernetes_resources_deletion"],
    )
    assert resource_ref(cluster) in app.metadata.owners

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.running_on is None
    assert "kubernetes_resources_deletion" not in stored.metadata.finalizers
    assert resource_ref(cluster) not in stored.metadata.owners


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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    # The API server of the Kubernetes cluster listens on "127.0.0.1"
    assert stored.status.services == {"nginx-demo": "127.0.0.1:30886"}


async def test_service_unregistration(aiohttp_server, config, db, loop):
    # Setup Kubernetes API mock server
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.json_response(
            {
                "api_version": "v1",
                "kind": "Service",
                "metadata": {
                    "creation_timestamp": "2019-11-12 08:44:02+00:00",
                    "name": "nginx-demo",
                    "namespace": "default",
                    "resource_version": "2075568",
                    "self_link": "/api/v1/namespaces/default/services/nginx-demo",
                    "uid": "4da165e0-e58f-4058-be44-fa393a58c2c8",
                },
                "spec": {
                    "cluster_ip": "10.98.197.124",
                    "external_traffic_policy": "Cluster",
                    "ports": [
                        {
                            "node_port": 30704,
                            "port": 8080,
                            "protocol": "TCP",
                            "target_port": 8080,
                        }
                    ],
                    "selector": {"app": "echo"},
                    "session_affinity": "None",
                    "type": "NodePort",
                },
                "status": {"load_balancer": {}},
            }
        )
        return web.Response(status=404)

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.json_response(
            {
                "api_version": "v1",
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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.services == {}


async def test_kubernetes_error_handling(aiohttp_server, config, db, loop):
    failed_manifest = deepcopy(nginx_manifest)
    for resource in failed_manifest:
        resource["kind"] = "Unsupported"

    cluster = ClusterFactory()
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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.queue.put(app.metadata.uid, app)
        await controller.handle_resource(run_once=True)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.state == ApplicationState.FAILED
    assert stored.status.reason.code == ReasonCode.INVALID_RESOURCE
