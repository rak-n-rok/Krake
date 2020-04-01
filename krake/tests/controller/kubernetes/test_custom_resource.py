from textwrap import dedent

from aiohttp import web
import json
import pytz
import yaml

from krake.api.app import create_app
from krake.controller.kubernetes_application.kubernetes_application import ResourceDelta
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes_application import (
    KubernetesController,
    KubernetesClient,
    Hook,
    register_resource_version,
)
from krake.client import Client
from krake.test_utils import server_endpoint, HandlerDeactivator

from factories.fake import fake
from factories.kubernetes import ApplicationFactory, ClusterFactory, make_kubeconfig


async def test_custom_resource_cached_property_called_once(
    aiohttp_server, config, db, loop
):
    """Test case if the `customresourcedefinitions` endpoint is called only once,
    if the application contains multiple custom resources with the same kind,
    but different content

    """
    only_once = True

    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1beta1/customresourcedefinitions/{name}")
    async def _(request):
        nonlocal only_once
        assert only_once, "Function should only be called only once"
        if only_once:
            only_once = False

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
                        name: cron1
                    spec:
                        cronSpec: "* * * * */5"
                        image: cron-image1
                    ---
                    apiVersion: stable.example.com/v1
                    kind: CronTab
                    metadata:
                        name: cron2
                    spec:
                        cronSpec: "* * * * */10"
                        image: cron-image2
                    """
                )
            )
        ),
    )

    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        with HandlerDeactivator(Hook.ResourcePostCreate, register_resource_version):
            await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_custom_resource_cached_property(aiohttp_server):
    """Test case if two clusters uses two different CRD, but with the exact same name

    """
    crd_name = "crontabs.stable.example.com"
    cluster_a_name = "cluster_a"
    cluster_b_name = "cluster_b"

    routes_a = web.RouteTableDef()
    routes_b = web.RouteTableDef()
    routes_common = web.RouteTableDef()

    def get_crd(cluster_name):
        return web.Response(
            status=200,
            body=json.dumps(
                {
                    "api_version": "apiextensions.k8s.io/v1beta1",
                    "kind": "CustomResourceDefinition",
                    "metadata": {"clusterName": cluster_name},
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

    # Determine scope, version, group and plural of custome resource definition
    @routes_a.get("/apis/apiextensions.k8s.io/v1beta1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == crd_name:
            return get_crd(cluster_a_name)
        return web.Response(status=404)

    @routes_b.get("/apis/apiextensions.k8s.io/v1beta1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == crd_name:
            return get_crd(cluster_b_name)
        return web.Response(status=404)

    @routes_common.get("/apis/stable.example.com/v1/namespaces/default/crontabs/cron")
    async def _(request):
        return web.Response(status=404)

    @routes_common.post("/apis/stable.example.com/v1/namespaces/default/crontabs")
    async def _(request):
        return web.Response(status=200)

    async def make_kubernetes_api(cluster):
        kubernetes_app = web.Application()
        routes = routes_a if cluster == cluster_a_name else routes_b
        kubernetes_app.add_routes(routes)
        kubernetes_app.add_routes(routes_common)
        return await aiohttp_server(kubernetes_app)

    kubernetes_server_a = await make_kubernetes_api(cluster=cluster_a_name)
    kubernetes_server_b = await make_kubernetes_api(cluster=cluster_b_name)

    # Clusters uses two different CRD, but with the exact same name
    cluster_a = ClusterFactory(
        metadata__name=cluster_a_name,
        spec__kubeconfig=make_kubeconfig(kubernetes_server_a),
        spec__custom_resources=[crd_name],
    )
    cluster_b = ClusterFactory(
        metadata__name=cluster_b_name,
        spec__kubeconfig=make_kubeconfig(kubernetes_server_b),
        spec__custom_resources=[crd_name],
    )

    for cluster in cluster_a, cluster_b:
        app = ApplicationFactory(
            status__state=ApplicationState.PENDING,
            status__scheduled_to=resource_ref(cluster),
            status__is_scheduled=False,
            status__mangling=list(
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
        async with KubernetesClient(
            cluster.spec.kubeconfig, cluster.spec.custom_resources
        ) as kube:
            delta = ResourceDelta.calculate(app)
            for new in delta.new:
                await kube.apply(new)
                custom_resource_apis = await kube.custom_resource_apis

                assert (
                    custom_resource_apis["CronTab"].metadata.cluster_name
                    == cluster.metadata.name
                )


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
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        with HandlerDeactivator(Hook.ResourcePostCreate, register_resource_version):
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
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        with HandlerDeactivator(Hook.ResourcePostUpdate, register_resource_version):
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
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        with HandlerDeactivator(Hook.ResourcePostCreate, register_resource_version):
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
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored is None
