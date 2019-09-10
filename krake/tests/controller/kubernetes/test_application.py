import asyncio
from copy import deepcopy
from aiohttp import web
import pytz
import yaml

from krake.api.app import create_app
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import Application, ApplicationState
from krake.controller import Worker
from krake.controller.kubernetes.application import (
    ApplicationController,
    ApplicationWorker,
)
from krake.client import Client
from krake.test_utils import server_endpoint

from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory, make_kubeconfig


async def test_app_reception(aiohttp_server, config, db, loop):
    created = ApplicationFactory(status__state=ApplicationState.PENDING)
    updated = ApplicationFactory(status__state=ApplicationState.UPDATED)
    scheduled = ApplicationFactory(status__state=ApplicationState.SCHEDULED)

    server = await aiohttp_server(create_app(config))

    class SimpleWorker(Worker):
        def __init__(self):
            self.done = loop.create_future()

        async def resource_received(self, app):
            assert app == scheduled

            if not self.done.done():
                self.done.set_result(None)

    worker = SimpleWorker()

    async with ApplicationController(
        api_endpoint=server_endpoint(server),
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
    ) as controller:

        await db.put(created)
        await db.put(updated)
        await db.put(scheduled)

        await asyncio.wait(
            [controller, worker.done], timeout=1, return_when=asyncio.FIRST_COMPLETED
        )
    assert worker.done.done()


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
        status__state=ApplicationState.SCHEDULED,
        status__cluster=resource_ref(cluster),
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
        worker = ApplicationWorker(client=client)
        await worker.resource_received(app)

    stored, _ = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "cleanup"


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
        status__cluster=resource_ref(cluster),
        spec__manifest=nginx_manifest,
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        worker = ApplicationWorker(client=client)
        await worker.resource_received(app)


async def test_app_deletion_without_binding(aiohttp_server, config, db, loop):
    app = ApplicationFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        status__state=ApplicationState.RUNNING,
        status__cluster=None,
        spec__manifest=nginx_manifest,
    )
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = ApplicationWorker(client=client)
        await worker.resource_received(app)

    # Ensure the application is completly removed from database
    stored, _ = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored is None


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
        status__state=ApplicationState.SCHEDULED,
        status__cluster=resource_ref(cluster),
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

    api_server = await aiohttp_server(create_app(config))

    # Start Kubernetes worker
    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        worker = ApplicationWorker(client=client)
        await worker.resource_received(app)


async def test_kubernetes_error_handling(aiohttp_server, config, db, loop):
    failed_manifest = deepcopy(nginx_manifest)
    failed_manifest[0]["kind"] = "Unsupported"

    cluster = ClusterFactory()
    app = ApplicationFactory(
        status__state=ApplicationState.SCHEDULED,
        status__cluster=resource_ref(cluster),
        spec__manifest=failed_manifest,
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = ApplicationWorker(client=client)
        await worker.resource_received(app)

    stored, _ = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.state == ApplicationState.FAILED
    assert stored.status.reason.code == ReasonCode.INVALID_RESOURCE
