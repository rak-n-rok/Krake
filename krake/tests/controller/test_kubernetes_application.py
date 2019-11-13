import asyncio
from contextlib import suppress
from copy import deepcopy
from textwrap import dedent

from aiohttp import web
from aiohttp.test_utils import TestServer as Server
import json
import pytz
import yaml
from krake.data.config import (
    HooksConfiguration,
    TlsClientConfiguration,
    TlsServerConfiguration,
)
from kubernetes_asyncio.client import V1Status, V1Service, V1ServiceSpec, V1ServicePort

from krake.api.app import create_app
from krake.controller import create_ssl_context
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes_application import (
    ApplicationController,
    register_service,
    unregister_service,
    KubernetesObserver,
    merge_status,
)
from krake.client import Client
from krake.test_utils import server_endpoint

from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory, make_kubeconfig


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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
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


async def test_app_custom_resource_creation(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custome resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1beta1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(
                    {
                        "api_version": "apiextensions.k8s.io/v1beta1",
                        "kind": "CustomResourceDefinition",
                        "spec": {
                            "group": "stable.example.com",
                            "names": {"kind": "CronTab", "plural": "crontabs"},
                            "scope": "Namespaced",
                            "versions": [
                                {"name": "v1", "served": "True", "storage": "True"}
                            ],
                        },
                    }
                ),
                content_type="application/json",
            )
        return web.Response(status=404)

    @routes.get("/apis/stable.example.com/v1/namespaces/default/crontabs/cron")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/stable.example.com/v1/namespaces/default/crontabs")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server),
        spec__custom_resources=["crontabs.stable.example.com"],
    )

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=list(
            yaml.safe_load_all(
                dedent(
                    """
                    ---
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron
                    spec:
                        cronSpec: "* * * * */5"
                        image: cron-image
                    """
                )
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


async def test_app_custom_resource_update(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    deleted = set()
    patched = set()

    # Determine scope, version, group and plural of custome resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1beta1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(
                    {
                        "api_version": "apiextensions.k8s.io/v1beta1",
                        "kind": "CustomResourceDefinition",
                        "spec": {
                            "group": "stable.example.com",
                            "names": {"kind": "CronTab", "plural": "crontabs"},
                            "scope": "Namespaced",
                            "versions": [
                                {"name": "v1", "served": "True", "storage": "True"}
                            ],
                        },
                    }
                ),
                content_type="application/json",
            )
        return web.Response(status=404)

    @routes.patch("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def patch_deployment(request):
        patched.add(request.match_info["name"])
        return web.Response(status=200)

    @routes.delete("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def delete_deployment(request):
        deleted.add(request.match_info["name"])
        return web.Response(status=200)

    @routes.get("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def _(request):
        deployments = ("cron-demo-1", "cron-demo-2", "cron-demo-3")
        if request.match_info["name"] in deployments:
            return web.Response(status=200)
        return web.Response(status=404)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server),
        spec__custom_resources=["crontabs.stable.example.com"],
    )

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
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron-demo-1
                    spec:
                        cronSpec: "* * * * */5"
                        image: cron-image
                    ---
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron-demo-2
                    spec:
                        cronSpec: "* * * * */15"
                        image: cron-image
                    ---
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron-demo-3
                    spec:
                        cronSpec: "* * * * */35"
                        image: cron-image
                    """
                )
            )
        ),
        spec__manifest=list(
            yaml.safe_load_all(
                dedent(
                    """
                    ---
                    # Deployment "cron-demo-1" was removed
                    # Deployment "cron-demo-2" is unchanged
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron-demo-2
                    spec:
                        cronSpec: "* * * * */15"
                        image: cron-image
                    ---
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron-demo-3
                    spec:
                        cronSpec: "* * * * */35"
                        image: cron-image:1.2 # updated image version
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

    assert "cron-demo-1" in deleted
    assert "cron-demo-3" in patched

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_custom_resource_migration(aiohttp_server, config, db, loop):
    """Application was scheduled to a different cluster. The controller should
    delete objects from the old cluster and create objects on the new cluster.
    """
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custome resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1beta1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(
                    {
                        "api_version": "apiextensions.k8s.io/v1beta1",
                        "kind": "CustomResourceDefinition",
                        "spec": {
                            "group": "stable.example.com",
                            "names": {"kind": "CronTab", "plural": "crontabs"},
                            "scope": "Namespaced",
                            "versions": [
                                {"name": "v1", "served": "True", "storage": "True"}
                            ],
                        },
                    }
                ),
                content_type="application/json",
            )
        return web.Response(status=404)

    @routes.post("/apis/stable.example.com/v1/namespaces/default/crontabs")
    async def _(request):
        body = await request.json()
        request.app["created"].add(body["metadata"]["name"])
        return web.Response(status=201)

    @routes.delete("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def delete_deployment(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

    @routes.get("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def _(request):
        return web.Response(status=404)

    async def make_kubernetes_api(existing=()):
        app = web.Application()
        app["created"] = set()
        app["deleted"] = set()

        app.add_routes(routes)

        return await aiohttp_server(app)

    kubernetes_server_A = await make_kubernetes_api()
    kubernetes_server_B = await make_kubernetes_api()

    cluster_A = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server_A),
        spec__custom_resources=["crontabs.stable.example.com"],
    )
    cluster_B = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server_B),
        spec__custom_resources=["crontabs.stable.example.com"],
    )

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
                ---
                apiVersion: stable.example.com/v1
                kind: CronTab
                metadata:
                    name: cron
                spec:
                    cronSpec: "* * * * */5"
                    image: cron-image
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
    assert "cron" in kubernetes_server_B.app["created"]

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.status.running_on == resource_ref(cluster_B)
    assert resource_ref(cluster_A) not in stored.metadata.owners
    assert resource_ref(cluster_B) in stored.metadata.owners


async def test_app_custom_resource_deletion(aiohttp_server, config, db, loop):
    kubernetes_app = web.Application()
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custome resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1beta1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(
                    {
                        "api_version": "apiextensions.k8s.io/v1beta1",
                        "kind": "CustomResourceDefinition",
                        "spec": {
                            "group": "stable.example.com",
                            "names": {"kind": "CronTab", "plural": "crontabs"},
                            "scope": "Namespaced",
                            "versions": [
                                {"name": "v1", "served": "True", "storage": "True"}
                            ],
                        },
                    }
                ),
                content_type="application/json",
            )
        return web.Response(status=404)

    @routes.delete("/apis/stable.example.com/v1/namespaces/default/crontabs/cron")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server),
        spec__custom_resources=["crontabs.stable.example.com"],
    )
    app = ApplicationFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=resource_ref(cluster),
        status__running_on=resource_ref(cluster),
        metadata__finalizers=["kubernetes_resources_deletion"],
        status__manifest=list(
            yaml.safe_load_all(
                dedent(
                    """
                    ---
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron
                    spec:
                        cronSpec: "* * * * */5"
                        image: cron-image
                    """
                )
            )
        ),
    )
    assert resource_ref(cluster) in app.metadata.owners

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
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


hooks_config = HooksConfiguration.deserialize(
    {
        "complete": {
            "ca_dest": "/etc/krake_ca/ca.pem",
            "env_token": "KRAKE_TOKEN",
            "env_complete": "KRAKE_COMPLETE_URL",
        }
    }
)


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
        controller = ApplicationController(
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
        controller = ApplicationController(
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
        controller = ApplicationController(
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


async def test_kubernetes_error_handling(aiohttp_server, config, db, loop):
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
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.queue.put(app.metadata.uid, app)
        await controller.handle_resource(run_once=True)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.state == ApplicationState.FAILED
    assert stored.status.reason.code == ReasonCode.INVALID_RESOURCE


def get_first_container(deployment):
    return deployment["spec"]["template"]["spec"]["containers"][0]


async def test_reception_for_observer(aiohttp_server, config, db, loop):
    cluster = ClusterFactory()
    pending = ApplicationFactory(status__state=ApplicationState.PENDING)
    running = ApplicationFactory(
        status__running_on=resource_ref(cluster), status__state=ApplicationState.RUNNING
    )

    server = await aiohttp_server(create_app(config))

    await db.put(cluster)
    await db.put(pending)
    await db.put(running)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await controller.prepare(client)  # need to be called explicitly
        await controller.reflector.list_resource()
    # Each running Application has a corresponding observer
    assert len(controller.observers) == 1
    assert running.metadata.uid in controller.observers


# TODO change
service_response = yaml.safe_load(
    """
    apiVersion: v1
    kind: Service
    metadata:
      creationTimestamp: "2019-11-11T12:01:05Z"
      name: nginx-demo
      namespace: default
      resourceVersion: "8080020"
      selfLink: /api/v1/namespaces/default/services/nginx-demo
      uid: e2b789b0-19a1-493d-9f23-3f2a63fade52
    spec:
      clusterIP: 10.100.78.172
      externalTrafficPolicy: Cluster
      ports:
      - nodePort: 32566
        port: 80
        protocol: TCP
        targetPort: 80
      selector:
        app: nginx
      sessionAffinity: None
      type: NodePort
    status:
      loadBalancer: {}
    """
)

app_response = yaml.safe_load(
    """
    apiVersion: extensions/v1beta1
    kind: Deployment
    metadata:
      annotations:
        deployment.kubernetes.io/revision: "1"
      creationTimestamp: "2019-11-11T12:01:05Z"
      generation: 1
      name: nginx-demo
      namespace: default
      resourceVersion: "8080030"
      selfLink: /apis/extensions/v1beta1/namespaces/default/deployments/nginx-demo
      uid: 047686e4-af52-4264-b2a4-2f82b890e809
    spec:
      progressDeadlineSeconds: 600
      replicas: 1
      revisionHistoryLimit: 10
      selector:
        matchLabels:
          app: nginx
      strategy:
        rollingUpdate:
          maxSurge: 25%
          maxUnavailable: 25%
        type: RollingUpdate
      template:
        metadata:
          creationTimestamp: null
          labels:
            app: nginx
        spec:
          containers:
          - image: nginx:1.7.9
            imagePullPolicy: IfNotPresent
            name: nginx
            ports:
            - containerPort: 80
              protocol: TCP
            resources: {}
            terminationMessagePath: /dev/termination-log
            terminationMessagePolicy: File
          dnsPolicy: ClusterFirst
          restartPolicy: Always
          schedulerName: default-scheduler
          securityContext: {}
          terminationGracePeriodSeconds: 30
    status:
      availableReplicas: 1
      conditions:
      - lastTransitionTime: "2019-11-11T12:01:07Z"
        lastUpdateTime: "2019-11-11T12:01:07Z"
        message: Deployment has minimum availability.
        reason: MinimumReplicasAvailable
        status: "True"
        type: Available
      - lastTransitionTime: "2019-11-11T12:01:05Z"
        lastUpdateTime: "2019-11-11T12:01:07Z"
        message: ReplicaSet "nginx-demo-5754944d6c" has successfully progressed.
        reason: NewReplicaSetAvailable
        status: "True"
        type: Progressing
      observedGeneration: 1
      readyReplicas: 1
      replicas: 1
      updatedReplicas: 1
    """
)


async def test_observer_on_poll_update(aiohttp_server, db, config, loop):
    """Test the Observer's behavior on update of an actual resource.

    State (0):
        a Deployment and a Service are present, the Deployment has an nginx
        image with version "1.7.9"
    State (1):
        both resources are still present, but the Deployment image version
        changed to "1.6"
    State (2):
        only the Deployment is present, with the version "1.6"
    """
    routes = web.RouteTableDef()

    # Actual resource, with container image changed
    updated_app = deepcopy(app_response)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        if actual_state[0] in (0, 1):
            return web.json_response(service_response)
        elif actual_state[0] == 2:
            return web.Response(status=404)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        if actual_state[0] == 0:
            return web.json_response(app_response)
        elif actual_state[0] >= 1:
            return web.json_response(updated_app)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__manifest=nginx_manifest,
    )

    async def on_res_update(resource):
        assert resource.metadata.name == app.metadata.name

        status_image = get_first_container(resource.status.manifest[0])["image"]
        if actual_state[0] == 0:
            assert status_image == "nginx:1.7.9"
            assert len(resource.status.manifest) == 2
        elif actual_state[0] == 1:
            assert status_image == "nginx:1.6"
            assert len(resource.status.manifest) == 2
        elif actual_state[0] == 2:
            assert status_image == "nginx:1.6"
            manifests = resource.status.manifest
            assert len(manifests) == 1
            assert manifests[0]["kind"] == "Deployment"

        # The spec never changes
        spec_image = get_first_container(resource.spec.manifest[0])["image"]
        assert spec_image == "nginx:1.7.9"

    observer = KubernetesObserver(cluster, app, on_res_update, time_step=-1)

    # Observe an unmodified resource
    actual_state = [0]
    await observer.observe_resource()

    # Modify the actual resource "externally", and observe
    actual_state = [1]
    await observer.observe_resource()

    # Delete the service "externally"
    actual_state = [2]
    await observer.observe_resource()


async def test_observer_on_status_update(aiohttp_server, db, config, loop):
    """Test the ``on_status_update`` method of the Kubernetes Controller
    """
    routes = web.RouteTableDef()

    # Actual resource, with container image changed
    updated_app = deepcopy(app_response)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.json_response(updated_app)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__manifest=nginx_manifest,
        spec__manifest=nginx_manifest,
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        observer = KubernetesObserver(
            cluster, app, controller.on_status_update, time_step=-1
        )

        await observer.observe_resource()
        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert updated.spec == app.spec
        assert updated.metadata.created == app.metadata.created
        first_container = get_first_container(updated.status.manifest[0])
        assert first_container["image"] == "nginx:1.6"


deploy_mangled_response = yaml.safe_load(
    """
    apiVersion: extensions/v1beta1
    kind: Deployment
    metadata:
      annotations:
        deployment.kubernetes.io/revision: "1"
      creationTimestamp: "2019-12-03T08:21:11Z"
      generation: 1
      name: nginx-demo
      namespace: default
      resourceVersion: "10373629"
      selfLink: /apis/extensions/v1beta1/namespaces/default/deployments/nginx-demo
      uid: 5ee5cbe8-6b18-4b2c-9691-3c9517748fe1
    spec:
      progressDeadlineSeconds: 600
      replicas: 1
      revisionHistoryLimit: 10
      selector:
        matchLabels:
          app: nginx
      strategy:
        rollingUpdate:
          maxSurge: 25%
          maxUnavailable: 25%
        type: RollingUpdate
      template:
        metadata:
          creationTimestamp: null
          labels:
            app: nginx
        spec:
          containers:
          - env:
            - name: KRAKE_TOKEN
              value: will_change
            - name: KRAKE_COMPLETE_URL
              value: will_change
            image: nginx:1.7.9
            imagePullPolicy: IfNotPresent
            name: nginx
            ports:
            - containerPort: 80
              protocol: TCP
            resources: {}
            terminationMessagePath: /dev/termination-log
            terminationMessagePolicy: File
          dnsPolicy: ClusterFirst
          restartPolicy: Always
          schedulerName: default-scheduler
          securityContext: {}
          terminationGracePeriodSeconds: 30
    status:
      availableReplicas: 1
      conditions:
      - lastTransitionTime: "2019-12-03T08:21:13Z"
        lastUpdateTime: "2019-12-03T08:21:13Z"
        message: Deployment has minimum availability.
        reason: MinimumReplicasAvailable
        status: "True"
        type: Available
      - lastTransitionTime: "2019-12-03T08:21:11Z"
        lastUpdateTime: "2019-12-03T08:21:13Z"
        message: ReplicaSet "nginx-demo-75466d4479" has successfully progressed.
        reason: NewReplicaSetAvailable
        status: "True"
        type: Progressing
      observedGeneration: 1
      readyReplicas: 1
      replicas: 1
      updatedReplicas: 1
    """
)


async def test_observer_on_status_update_mangled(aiohttp_server, db, config, loop):
    """Test the ``on_status_update`` method of the Kubernetes Controller in case of
    an Application mangled with the "complete" hook.

    State (0):
        the Application is created, the hook is added. This is used to update the
        Kubernetes response.
    State (1):
        the state of the resource is observed. The observer should not notify the API.
    State (2):
        the image of the Deployment changed. The observer should notify the API.
    """
    routes = web.RouteTableDef()

    actual_state = [0]
    copy_deploy_mangled_response = deepcopy(deploy_mangled_response)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        if actual_state[0] == 0:
            return web.Response(status=404)
        if actual_state[0] == 1:
            return web.json_response(copy_deploy_mangled_response)
        if actual_state[0] == 2:
            return web.json_response(updated_app)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        return web.Response(status=200)

    @routes.patch("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.json_response(updated_app)

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        if actual_state[0] == 0:
            return web.Response(status=404)
        elif actual_state[0] >= 1:
            return web.json_response(service_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__manifest=nginx_manifest,
        spec__hooks=["complete"],
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    def update_decorator(func):
        async def on_res_update(resource):
            if actual_state[0] == 1:
                assert False
            if actual_state[0] == 2:
                await func(resource)

        return on_res_update

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(
            server_endpoint(server), worker_count=0, hooks=deepcopy(hooks_config)
        )
        controller.on_status_update = update_decorator(controller.on_status_update)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)
        # Remove from dict to prevent cancellation in KubernetesController.stop_observer
        observer, _ = controller.observers.pop(app.metadata.uid)

        # Modify the response of the cluster to match the Application specific token and
        # endpoint that are stored in the Observer
        first_container = get_first_container(copy_deploy_mangled_response)
        first_container["env"][0]["value"] = observer.resource.status.token
        app_container = get_first_container(observer.resource.status.manifest[0])
        first_container["env"][1]["value"] = app_container["env"][1]["value"]

        actual_state = [1]

        # The observer should not call on_res_update
        await observer.observe_resource()

        actual_state = [2]

        # Actual resource, with container image changed
        updated_app = deepcopy(copy_deploy_mangled_response)
        first_container = get_first_container(updated_app)
        first_container["image"] = "nginx:1.6"

        await observer.observe_resource()
        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert updated.spec == app.spec
        # Check that the hook is present in the stored Application
        assert "env" in get_first_container(updated.status.manifest[0])
        assert updated.metadata.created == app.metadata.created
        first_container = get_first_container(updated.status.manifest[0])
        assert first_container["image"] == "nginx:1.6"


async def check_observer_does_not_update(observer, app, db):
    """Ensure that the given observer is up-to-date with the Application on the API.

    Args:
        observer (KubernetesObserver): the observer to check.
        app (Application): the Application that the observer has to monitor. Used just
            for its references (name and namespace).
        db (krake.api.database.Session): the database session to access the API data

    Returns:
        Application: the latest version of the Application on the API.

    """
    before = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    await observer.observe_resource()
    after = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert after == before
    return after


async def test_observer_on_api_update(aiohttp_server, config, db, loop):
    """Test the connectivity between the Controller and Observer on update of
    a resource by the API.
    State (0):
        a Deployment and a Service are present, the Deployment has an nginx
        image with version "1.7.9"
    State (1):
        both resources are still present, but the API changed the Deployment
        image version to "1.6"
    State (2):
        the Service is deleted by the API. Only the Deployment is present, with
        the version "1.6"
    """
    routes = web.RouteTableDef()

    actual_state = [0]

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        if actual_state[0] in (0, 1):
            return web.json_response(service_response)
        elif actual_state[0] == 2:
            return web.Response(status=404)

    updated_app = deepcopy(app_response)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        if actual_state[0] == 0:
            return web.json_response(app_response)
        elif actual_state[0] >= 1:
            return web.json_response(updated_app)

    @routes.patch("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        assert actual_state[0] in (0, 1)
        return web.json_response(updated_app)

    @routes.patch("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        assert actual_state[0] in (0, 2)
        return web.json_response(service_response)

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        assert actual_state[0] == 2
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    cluster_ref = resource_ref(cluster)

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=cluster_ref,
        status__scheduled_to=cluster_ref,
        status__manifest=deepcopy(nginx_manifest),
        spec__manifest=deepcopy(nginx_manifest),
        metadata__finalizers=["kubernetes_resources_deletion"],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    def update_decorator(func):
        async def on_res_update(resource):
            # As the update on resources is performed by the API, the Observer should
            # never see an difference on the actual resource, and thus, the current
            # function should never be called
            assert False

        return on_res_update

    async def mock():
        # When a resource is updated, the task corresponding to the observer is stopped
        # automatically. This mock is used as a fake task to cancel
        await asyncio.sleep(1)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(server_endpoint(server), worker_count=0)
        controller.on_status_update = update_decorator(controller.on_status_update)

        await controller.prepare(client)

        ##
        # In state 0
        ##

        # Create actual application, starts the Observer
        # ``start_observer`` prevents starting the observer as background task
        await controller.resource_received(app, start_observer=False)

        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Observe an unmodified resource
        after_0 = await check_observer_does_not_update(obs, app, db)

        ##
        # Modify the image version on the API, and observe --> go into state 1
        ##

        actual_state = [1]
        # Modify the manifest of the Application
        first_container = get_first_container(after_0.spec.manifest[0])
        first_container["image"] = "nginx:1.6"
        after_0.status.state = ApplicationState.RUNNING
        await db.put(after_0)

        # Update the actual resource
        await controller.resource_received(after_0, start_observer=False)
        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Assert the resource on the observer has been updated.
        first_container = get_first_container(obs.resource.spec.manifest[0])
        assert first_container["image"] == "nginx:1.6"

        # Status should not be updated by observer
        after_1 = await check_observer_does_not_update(obs, app, db)

        ##
        # Remove the service on the API, and observe--> go into state 2
        ##

        actual_state = [2]
        # Modify the manifest of the Application
        after_1.spec.manifest = after_1.spec.manifest[:1]
        after_1.status.state = ApplicationState.RUNNING
        await db.put(after_1)

        # Update the actual resource
        await controller.resource_received(after_1, start_observer=False)
        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Status should not be updated by observer
        await check_observer_does_not_update(obs, app, db)


async def test_observer_on_delete(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.json_response(service_response)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.json_response(app_response)

    @routes.delete("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        metadata__deleted=fake.date_time(),
        status__state=ApplicationState.RUNNING,
        status__manifest=nginx_manifest,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        metadata__finalizers=["kubernetes_resources_deletion"],
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = ApplicationController(
            server_endpoint(server), worker_count=0, time_step=100
        )
        await controller.prepare(client)

        # Start the observer, which will not observe due to time step
        await controller.register_observer(app)
        observer, _ = controller.observers[app.metadata.uid]

        # Observe a resource actually in deletion.
        before = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        await observer.observe_resource()
        after = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert after == before

        # Clean the application resources
        await controller.resource_received(app)
        # The observer task should be cancelled
        assert app.metadata.uid not in controller.observers


def test_merge_status():
    to_update = {
        "first": "foo",
        "second": "no_change",
        "third": "not_in_newest",
        "fourth": ["list", "with", "different", "length"],
        "sixth": [{"six_1": True}, {"six_2": True}],
        "seventh": ["same", "also same"],
        "eighth": {"changing": 0, "recursive_dict": {"changing": 0, "fixed": "lorem"}},
    }
    newest = {
        "first": "bar",
        "second": "no_change",
        "fourth": ["list", "with", "different", "length", "yes"],
        "fifth": "no_in_to_update",
        "sixth": [{"six_1": True}, {"six_2": False}],
        "seventh": ["same", "different"],
        "eighth": {
            "changing": 42,
            "recursive_dict": {"changing": 42, "fixed": "lorem"},
        },
    }

    to_update_copy = deepcopy(to_update)
    newest_copy = deepcopy(newest)

    res = merge_status(to_update, newest)

    expected = {
        "first": "bar",  # value changed
        "second": "no_change",
        "third": "not_in_newest",  # value kept, even if not in newest
        "fourth": ["list", "with", "different", "length", "yes"],  # new list kept
        "sixth": [{"six_1": True}, {"six_2": False}],  # list recursively updated
        "seventh": ["same", "different"],  # simple elements in list updated
        "eighth": {  # dict recursively updated
            "changing": 42,
            "recursive_dict": {"changing": 42, "fixed": "lorem"},
        },
    }

    assert expected == res
    # The given dictionary should not be modified by the merge
    assert to_update == to_update_copy
    assert newest == newest_copy
