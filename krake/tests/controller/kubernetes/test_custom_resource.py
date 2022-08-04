from textwrap import dedent

from aiohttp import web
from copy import deepcopy

import json
import pytz
import yaml

from krake.api.app import create_app
from krake.controller.kubernetes.client import InvalidCustomResourceDefinitionError
from krake.controller.kubernetes.application.application import ResourceDelta
from krake.data.core import resource_ref
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes.application import KubernetesApplicationController
from krake.controller.kubernetes.application.application import KubernetesClient
from krake.client import Client
from krake.test_utils import server_endpoint
from tests.controller.kubernetes import crontab_crd, create_cron_resource

from tests.factories.fake import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)


# snake_case response
crontab_response = yaml.safe_load(
    """
---
api_version: stable.example.com/v1
kind: CronTab
metadata:
  creation_timestamp: "2017-05-31T12:56:35Z"
  generation: 1
  name: cron
  namespace: default
  resource_version: "285"
  uid: 9423255b-4600-11e7-af6a-28d2447dc82b
spec:
  cron_spec: '* * * * 5'
  image: cron-image
"""
)

observer_schema = yaml.safe_load_all(
    dedent(
        """
    ---
    apiVersion: stable.example.com/v1
    kind: CronTab
    metadata:
        name: cron
        namespace: null
    spec:
        cronSpec: null
        image: null
    """
    )
)


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
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        nonlocal only_once
        assert only_once, "Function should only be called only once"
        if only_once:
            only_once = False

        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd()),
                content_type="application/json",
            )
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if the CronTabs already exists.
    @routes.get("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def _(request):
        return web.Response(status=404)

    # As part of the reconciliation, the k8s controller creates the CronTabs
    @routes.post("/apis/stable.example.com/v1/namespaces/default/crontabs")
    async def _(request):
        rd = await request.read()
        app = json.loads(rd)

        # Craft a response to be used by the Hooks
        resp = deepcopy(crontab_response)

        resp["metadata"]["name"] = app["metadata"]["name"]
        resp["spec"]["image"] = app["spec"]["image"]
        resp["spec"]["cron_spec"] = app["spec"]["cronSpec"]

        return web.json_response(resp, status=201)

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
        spec__manifest=[
            create_cron_resource("cron1", image="cron-image-1"),
            create_cron_resource("cron2", minute=10, image="cron-image-2"),
        ],
    )

    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, and updates the application in the DB accordingly.
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.last_applied_manifest == app.spec.manifest
    # The resource doesn't contain any list (therefore no special control dictionary is
    # present in last_observed_manifest), and no custom observer_schema is used
    # (therefore all fields present in spec.manifest are observed). In this specific
    # case, the last_observed_manifest should be equal to spec.manifest
    assert stored.status.last_observed_manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_custom_resource_cached_property(aiohttp_server):
    """Test case if two clusters uses two different CRD, but with the exact same name"""
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
                    "api_version": "apiextensions.k8s.io/v1",
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

    # Determine scope, version, group and plural of custom resource definition
    @routes_a.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == crd_name:
            return get_crd(cluster_a_name)
        return web.Response(status=404)

    @routes_b.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == crd_name:
            return get_crd(cluster_b_name)
        return web.Response(status=404)

    @routes_common.get("/apis/stable.example.com/v1/namespaces/default/crontabs/cron")
    async def _(request):
        return web.Response(status=404)

    @routes_common.post("/apis/stable.example.com/v1/namespaces/default/crontabs")
    async def _(request):
        return web.Response(status=201)

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
    mangled_observer_schema = list(observer_schema)
    for cluster in cluster_a, cluster_b:
        app = ApplicationFactory(
            status__state=ApplicationState.PENDING,
            status__scheduled_to=resource_ref(cluster),
            status__is_scheduled=False,
            status__last_applied_manifest=[create_cron_resource()],
            status__mangled_observer_schema=mangled_observer_schema,
            spec__manifest=[create_cron_resource()],
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

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd()),
                content_type="application/json",
            )
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a CronTab named `cron` already exists.
    @routes.get("/apis/stable.example.com/v1/namespaces/default/crontabs/cron")
    async def _(request):
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller creates the CronTab named `cron`.
    @routes.post("/apis/stable.example.com/v1/namespaces/default/crontabs")
    async def _(request):
        return web.json_response(crontab_response, status=201)

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
        spec__manifest=[create_cron_resource()],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, and updates the application in the DB accordingly.
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.last_applied_manifest == app.spec.manifest
    # The resource doesn't contain any list (therefore no special control dictionary is
    # present in last_observed_manifest), and no custom observer_schema is used
    # (therefore all fields present in spec.manifest are observed). In this specific
    # case, the last_observed_manifest should be equal to spec.manifest
    assert stored.status.last_observed_manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_custom_resource_update(aiohttp_server, config, db, loop):
    """Test the update of a running application using CRD

    The Kubernetes Controller should patch the application and update the DB.

    """
    routes = web.RouteTableDef()

    deleted = set()
    patched = set()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd()),
                content_type="application/json",
            )
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if the CronTabs named `cron-demo-1`, `cron-demo-2`
    # and `cron-demo-3` already exists.
    @routes.get("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def _(request):
        deployments = ("cron-demo-1", "cron-demo-2", "cron-demo-3")
        if request.match_info["name"] in deployments:
            return web.Response(status=200)
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller patch the existing
    # CronTab which has been modified.
    @routes.patch("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def _(request):
        rd = await request.read()
        app = json.loads(rd)

        # Craft a response to be used by the Hooks
        resp = deepcopy(crontab_response)

        resp["metadata"]["name"] = app["metadata"]["name"]
        resp["spec"]["image"] = app["spec"]["image"]
        resp["spec"]["cron_spec"] = app["spec"]["cronSpec"]

        patched.add(request.match_info["name"])
        return web.json_response(resp)

    # As part the reconciliation loop, the k8s controller deletes the CronTab which
    # are not present in the manifest file anymore.
    @routes.delete("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def _(request):
        deleted.add(request.match_info["name"])
        return web.Response(status=200)

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
        status__last_observed_manifest=[
            create_cron_resource("cron-demo-1", minute=5),
            create_cron_resource("cron-demo-2", minute=15),
            create_cron_resource("cron-demo-3", minute=35),
        ],
        spec__manifest=[
            create_cron_resource("cron-demo-2", minute=15),
            create_cron_resource("cron-demo-3", minute=35, image="cron-image:1.2"),
        ],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, deletes `cron-demo-1` and update `cron-demo-3`, and update the
        # applications in the DB accordingly.
        await controller.resource_received(app)

    assert "cron-demo-1" in deleted
    assert "cron-demo-3" in patched

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.last_applied_manifest == app.spec.manifest
    # The resource doesn't contain any list (therefore no special control dictionary is
    # present in last_observed_manifest), and no custom observer_schema is used
    # (therefore all fields present in spec.manifest are observed). In this specific
    # case, the last_observed_manifest should be equal to spec.manifest
    assert stored.status.last_observed_manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_custom_resource_migration(aiohttp_server, config, db, loop):
    """Application was scheduled to a different cluster. The controller should
    delete objects from the old cluster and create objects on the new cluster.
    """
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd()),
                content_type="application/json",
            )
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if the CronTabs already exists.
    @routes.get("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def _(request):
        return web.Response(status=404)

    # As part of the reconciliation, the k8s controller creates a new CronTab on the
    # target cluster
    @routes.post("/apis/stable.example.com/v1/namespaces/default/crontabs")
    async def _(request):

        rd = await request.read()
        app = json.loads(rd)

        # Craft a response to be used by the Hooks
        resp = deepcopy(crontab_response)

        resp["metadata"]["name"] = app["metadata"]["name"]
        resp["spec"]["image"] = app["spec"]["image"]
        resp["spec"]["cron_spec"] = app["spec"]["cronSpec"]

        request.app["created"].add(app["metadata"]["name"])
        return web.json_response(resp, status=201)

    # As part of the migration, the k8s controller deletes the Deployment on the old
    # cluster
    @routes.delete("/apis/stable.example.com/v1/namespaces/default/crontabs/{name}")
    async def delete_deployment(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

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

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster_A),
        status__scheduled_to=resource_ref(cluster_B),
        status__last_observed_manifest=[create_cron_resource(name="cron1", minute=10)],
        spec__manifest=[create_cron_resource(name="cron2")],
    )

    assert resource_ref(cluster_A) in app.metadata.owners
    assert resource_ref(cluster_B) in app.metadata.owners

    await db.put(cluster_A)
    await db.put(cluster_B)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, migrate the application and updates the DB accordingly.
        await controller.resource_received(app)

    assert "cron1" in kubernetes_server_A.app["deleted"]
    assert "cron2" in kubernetes_server_B.app["created"]

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.last_applied_manifest == app.spec.manifest
    # The resource doesn't contain any list (therefore no special control dictionary is
    # present in last_observed_manifest), and no custom observer_schema is used
    # (therefore all fields present in spec.manifest are observed). In this specific
    # case, the last_observed_manifest should be equal to spec.manifest
    assert stored.status.last_observed_manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.status.running_on == resource_ref(cluster_B)
    assert resource_ref(cluster_A) not in stored.metadata.owners
    assert resource_ref(cluster_B) in stored.metadata.owners


async def test_app_custom_resource_deletion(aiohttp_server, config, db, loop):
    kubernetes_app = web.Application()
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custome resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd()),
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
        status__last_observed_manifest=[create_cron_resource()],
    )
    assert resource_ref(cluster) in app.metadata.owners

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored is None


async def test_app_custom_resource_creation_non_ns(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd(namespaced=False)),
                content_type="application/json",
            )
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a CronTab named `cron` already exists.
    @routes.get("/apis/stable.example.com/v1/crontabs/cron")
    async def _(request):
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller creates the CronTab named `cron`.
    @routes.post("/apis/stable.example.com/v1/crontabs")
    async def _(request):
        return web.json_response(crontab_response, status=201)

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
        spec__manifest=[create_cron_resource()],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, and updates the application in the DB accordingly.
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.last_applied_manifest == app.spec.manifest
    # The resource doesn't contain any list (therefore no special control dictionary is
    # present in last_observed_manifest), and no custom observer_schema is used
    # (therefore all fields present in spec.manifest are observed). In this specific
    # case, the last_observed_manifest should be equal to spec.manifest
    assert stored.status.last_observed_manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_custom_resource_update_non_ns(aiohttp_server, config, db, loop):
    """Test the update of a running application using CRD

    The Kubernetes Controller should patch the application and update the DB.

    """
    routes = web.RouteTableDef()

    deleted = set()
    patched = set()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd(namespaced=False)),
                content_type="application/json",
            )
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if the CronTabs named `cron-demo-1`, `cron-demo-2`
    # and `cron-demo-3` already exists.
    @routes.get("/apis/stable.example.com/v1/crontabs/{name}")
    async def _(request):
        deployments = ("cron-demo-1", "cron-demo-2", "cron-demo-3")
        if request.match_info["name"] in deployments:
            return web.Response(status=200)
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller patch the existing
    # CronTab which has been modified.
    @routes.patch("/apis/stable.example.com/v1/crontabs/{name}")
    async def _(request):
        rd = await request.read()
        app = json.loads(rd)

        # Craft a response to be used by the Hooks
        resp = deepcopy(crontab_response)

        resp["metadata"]["name"] = app["metadata"]["name"]
        resp["spec"]["image"] = app["spec"]["image"]
        resp["spec"]["cron_spec"] = app["spec"]["cronSpec"]

        patched.add(request.match_info["name"])
        return web.json_response(resp)

    # As part the reconciliation loop, the k8s controller deletes the CronTab which
    # are not present in the manifest file anymore.
    @routes.delete("/apis/stable.example.com/v1/crontabs/{name}")
    async def _(request):
        deleted.add(request.match_info["name"])
        return web.Response(status=200)

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
        status__last_observed_manifest=[
            create_cron_resource("cron-demo-1", minute=5),
            create_cron_resource("cron-demo-2", minute=15),
            create_cron_resource("cron-demo-3", minute=35),
        ],
        spec__manifest=[
            create_cron_resource("cron-demo-2", minute=15),
            create_cron_resource("cron-demo-3", minute=35, image="cron-image:1.2"),
        ],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, deletes `cron-demo-1` and update `cron-demo-3`, and update the
        # applications in the DB accordingly.
        await controller.resource_received(app)

    assert "cron-demo-1" in deleted
    assert "cron-demo-3" in patched

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.last_applied_manifest == app.spec.manifest
    # The resource doesn't contain any list (therefore no special control dictionary is
    # present in last_observed_manifest), and no custom observer_schema is used
    # (therefore all fields present in spec.manifest are observed). In this specific
    # case, the last_observed_manifest should be equal to spec.manifest
    assert stored.status.last_observed_manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_custom_resource_migration_non_ns(aiohttp_server, config, db, loop):
    """Application was scheduled to a different cluster. The controller should
    delete objects from the old cluster and create objects on the new cluster.
    """
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd(namespaced=False)),
                content_type="application/json",
            )
        return web.Response(status=404)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if the CronTabs already exists.
    @routes.get("/apis/stable.example.com/v1/crontabs/{name}")
    async def _(request):
        return web.Response(status=404)

    # As part of the reconciliation, the k8s controller creates a new CronTab on the
    # target cluster
    @routes.post("/apis/stable.example.com/v1/crontabs")
    async def _(request):

        rd = await request.read()
        app = json.loads(rd)

        # Craft a response to be used by the Hooks
        resp = deepcopy(crontab_response)

        resp["metadata"]["name"] = app["metadata"]["name"]
        resp["spec"]["image"] = app["spec"]["image"]
        resp["spec"]["cron_spec"] = app["spec"]["cronSpec"]

        request.app["created"].add(app["metadata"]["name"])
        return web.json_response(resp, status=201)

    # As part of the migration, the k8s controller deletes the Deployment on the old
    # cluster
    @routes.delete("/apis/stable.example.com/v1/crontabs/{name}")
    async def delete_deployment(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

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

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster_A),
        status__scheduled_to=resource_ref(cluster_B),
        status__last_observed_manifest=[create_cron_resource(name="cron1", minute=10)],
        spec__manifest=[create_cron_resource(name="cron2")],
    )

    assert resource_ref(cluster_A) in app.metadata.owners
    assert resource_ref(cluster_B) in app.metadata.owners

    await db.put(cluster_A)
    await db.put(cluster_B)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, migrate the application and updates the DB accordingly.
        await controller.resource_received(app)

    assert "cron1" in kubernetes_server_A.app["deleted"]
    assert "cron2" in kubernetes_server_B.app["created"]

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.last_applied_manifest == app.spec.manifest
    # The resource doesn't contain any list (therefore no special control dictionary is
    # present in last_observed_manifest), and no custom observer_schema is used
    # (therefore all fields present in spec.manifest are observed). In this specific
    # case, the last_observed_manifest should be equal to spec.manifest
    assert stored.status.last_observed_manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.status.running_on == resource_ref(cluster_B)
    assert resource_ref(cluster_A) not in stored.metadata.owners
    assert resource_ref(cluster_B) in stored.metadata.owners


async def test_app_custom_resource_deletion_non_ns(aiohttp_server, config, db, loop):
    kubernetes_app = web.Application()
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custome resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd(namespaced=False)),
                content_type="application/json",
            )
        return web.Response(status=404)

    @routes.delete("/apis/stable.example.com/v1/crontabs/cron")
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
        status__last_observed_manifest=[create_cron_resource()],
    )
    assert resource_ref(cluster) in app.metadata.owners

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored is None


async def test_app_invalid_custom_resource_error_handling(
    aiohttp_server, config, db, loop
):
    """Test the behavior of the Controller in case of forbidden (HTTP 403) custom resource
    apis in given cluster
    """
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        # Forbid determining the custom resource api
        return web.Response(status=403)

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
        spec__manifest=[create_cron_resource()],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        await controller.queue.put(app.metadata.uid, app)
        await controller.handle_resource(run_once=True)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.state == ApplicationState.FAILED
    assert stored.status.reason.code == ReasonCode.INVALID_CUSTOM_RESOURCE


async def test_app_unknown_custom_resource_error_handling(
    aiohttp_server, config, db, loop
):
    """Test the behavior of the Controller in case of unknown custom resource
    apis for given cluster
    """
    routes = web.RouteTableDef()

    # Determine scope, version, group and plural of custom resource definition
    @routes.get("/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}")
    async def _(request):
        if request.match_info["name"] == "crontabs.stable.example.com":
            return web.Response(
                status=200,
                body=json.dumps(crontab_crd(namespaced=False)),
                content_type="application/json",
            )
        return web.Response(status=404)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server),
        # Note that cluster does not contain any custom resource
        spec__custom_resources=[],
    )

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=[create_cron_resource()],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        await controller.queue.put(app.metadata.uid, app)
        await controller.handle_resource(run_once=True)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.state == ApplicationState.FAILED
    assert stored.status.reason.code == ReasonCode.UNSUPPORTED_RESOURCE
