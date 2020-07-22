import asyncio
from contextlib import suppress
from copy import deepcopy

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
from krake.controller.kubernetes.kubernetes import ResourceDelta
from krake.controller.kubernetes.hooks import (
    update_last_applied_manifest_from_spec,
    update_last_applied_manifest_from_resp,
)
from krake.client import Client
from krake.test_utils import server_endpoint, serialize_k8s_object

from tests.factories.fake import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)
from . import (
    deployment_manifest,
    service_manifest,
    nginx_manifest,
    custom_deployment_observer_schema,
    custom_service_observer_schema,
    custom_observer_schema,
    deployment_response,
    service_response,
    configmap_response,
    hooks_config,
    initial_last_observed_manifest_deployment,
    initial_last_observed_manifest_service,
    initial_last_observed_manifest,
)


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
    """Test the creation of an application

    The Kubernetes Controller should create the application and update the DB.

    """

    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a Deployment named `nginx-demo` already exists.
    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        # No `nginx-demo` Deployment exist
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller creates the `nginx-demo`
    # Deployment
    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        # As a response, the k8s API provides the full Deployment object
        return web.json_response(deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # When received by the k8s controller, the application is in PENDING state and
    # scheduled to a cluster. It contains a manifest and a custom observer_schema.
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=[deployment_manifest],
        spec__observer_schema=[custom_deployment_observer_schema],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, and updates the application in the DB accordingly.
        await controller.resource_received(app, start_observer=False)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.last_observed_manifest == [
        initial_last_observed_manifest_deployment
    ]
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_update(aiohttp_server, config, db, loop):
    """Test the update of a running application

    The Kubernetes Controller should patch the application and update the DB.
    """
    routes = web.RouteTableDef()

    deleted = set()
    patched = set()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if the Deployments named `nginx-demo-1`, `nginx-demo-2`
    # and `nginx-demo-3` already exists.
    @routes.get("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        # The three Deployment already exist
        deployments = ("nginx-demo-1", "nginx-demo-2", "nginx-demo-3")
        if request.match_info["name"] in deployments:
            # Personalize the name of the Deployment in the k8s API response
            response = deepcopy(deployment_response)
            response["metadata"]["name"] = request.match_info["name"]
            return web.json_response(response)

        # The endpoint shouldn't be called for another Deployment
        assert False

    # As part of the reconciliation loop, the k8s controller patch the existing
    # Deployment which has been modified.
    @routes.patch("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        deployment_request = request.match_info["name"]
        # Personalize the response: The name should match the name of Deployment which
        # is patched, and the image of the `nginx-demo-2` Deployment is modified by the
        # patch
        response = deepcopy(deployment_response)
        response["metadata"]["name"] = request.match_info["name"]
        if deployment_request == "nginx-demo-2":
            response["spec"]["template"]["spec"]["containers"][0]["image"] = "nginx:1.6"
        patched.add(request.match_info["name"])
        return web.json_response(response)

    # As part the reconclitation loop, the k8s controller deletes the Deployment which
    # are not present in the manifest file anymore.
    @routes.delete("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        deleted.add(request.match_info["name"])
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # Craft a last_observed_manifest, reflecting the resources previsouly created via
    # Krake: 3 Deployments
    nginx_initial_last_observed_manifest_1 = deepcopy(
        initial_last_observed_manifest_deployment
    )
    nginx_initial_last_observed_manifest_1["metadata"]["name"] = "nginx-demo-1"

    nginx_initial_last_observed_manifest_2 = deepcopy(
        initial_last_observed_manifest_deployment
    )
    nginx_initial_last_observed_manifest_2["metadata"]["name"] = "nginx-demo-2"

    nginx_initial_last_observed_manifest_3 = deepcopy(
        initial_last_observed_manifest_deployment
    )
    nginx_initial_last_observed_manifest_3["metadata"]["name"] = "nginx-demo-3"

    # Craft the new manifest file of the application:
    # - nginx-demo-1 has been deleted
    # - nginx-demo-2 has been modified
    # - nginx-demo-3 has not changed
    # Also set the number of replicas to 1, as this field is observed by the custom
    # observer schema
    nginx_manifest_2 = deepcopy(deployment_manifest)
    nginx_manifest_2["metadata"]["name"] = "nginx-demo-2"
    nginx_manifest_2["spec"]["replicas"] = 1
    nginx_manifest_2["spec"]["template"]["spec"]["containers"][0]["image"] = "nginx:1.6"

    nginx_manifest_3 = deepcopy(deployment_manifest)
    nginx_manifest_3["metadata"]["name"] = "nginx-demo-3"
    nginx_manifest_3["spec"]["replicas"] = 1

    # Craft a custom observer schema matching the two resources defined in
    # spec.manifest
    nginx_observer_schema_2 = deepcopy(custom_deployment_observer_schema)
    nginx_observer_schema_2["metadata"]["name"] = "nginx-demo-2"

    nginx_observer_schema_3 = deepcopy(custom_deployment_observer_schema)
    nginx_observer_schema_3["metadata"]["name"] = "nginx-demo-3"

    # Craft the last_observed_manifest as it should be after the reconciliation loop:
    # - nginx-demo-1 is absent
    # - nginx-demo-2 container image is "nginx:1.6"
    # - nginx-demo-3 is not modified
    nginx_target_last_observed_manifest_2 = deepcopy(
        initial_last_observed_manifest_deployment
    )
    nginx_target_last_observed_manifest_2["metadata"]["name"] = "nginx-demo-2"
    nginx_target_last_observed_manifest_2["spec"]["template"]["spec"]["containers"][0][
        "image"
    ] = "nginx:1.6"

    nginx_target_last_observed_manifest_3 = deepcopy(
        initial_last_observed_manifest_deployment
    )
    nginx_target_last_observed_manifest_3["metadata"]["name"] = "nginx-demo-3"

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        status__last_observed_manifest=[
            nginx_initial_last_observed_manifest_1,
            nginx_initial_last_observed_manifest_2,
            nginx_initial_last_observed_manifest_3,
        ],
        spec__observer_schema=[nginx_observer_schema_2, nginx_observer_schema_3],
        spec__manifest=[nginx_manifest_2, nginx_manifest_3],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, and updates the application in the DB accordingly.
        await controller.resource_received(app, start_observer=False)

    assert "nginx-demo-1" in deleted
    assert "nginx-demo-2" in patched

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.last_observed_manifest == [
        nginx_target_last_observed_manifest_2,
        nginx_target_last_observed_manifest_3,
    ]
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_migration(aiohttp_server, config, db, loop):
    """Test the migration of an application

    The Application is scheduled to a different cluster. The controller should delete
    objects from the old cluster and create objects on the new cluster.

    """
    routes = web.RouteTableDef()

    # As part of the migration started by ``controller.resource_received``, the k8s
    # controller checks if the Deployment already exists
    @routes.get("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def _(request):
        # The k8s API only replies with the full Deployment resource if it's existing.
        if request.match_info["name"] in request.app["existing"]:
            # Personalize the name of the Deployment in the response with the name of
            # the Deployment which is "get"
            response = deepcopy(deployment_response)
            response["metadata"]["name"] = request.match_info["name"]
            return web.json_response(response)

        # If the resource doesn't exist, return a 404 response
        return web.Response(status=404)

    # As part of the migration, the k8s controller creates a new Deployment on the
    # target cluster
    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        body = await request.json()
        request.app["created"].add(body["metadata"]["name"])

        response = deepcopy(deployment_response)
        response["metadata"]["name"] = body["metadata"]["name"]
        return web.json_response(response)

    # As part of the migration, the k8s controller deletes a Deployment on the old
    # cluster
    @routes.delete("/apis/apps/v1/namespaces/default/deployments/{name}")
    async def delete_deployment(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

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

    # Craft a last_observed_manifest, reflecting the resources previsouly created via
    # Krake: a Deployment named "nginx-demo-1"
    nginx_initial_last_observed_manifest_old = deepcopy(
        initial_last_observed_manifest_deployment
    )
    nginx_initial_last_observed_manifest_old["metadata"]["name"] = "nginx-demo-1"

    # Craft the new manifest file of the application: a Deployment name "nginx-demo-2".
    # Also set the number of replicas to 1, as this field is observed by the custom
    # observer schema
    nginx_manifest_new = deepcopy(deployment_manifest)
    nginx_manifest_new["metadata"]["name"] = "nginx-demo-2"
    nginx_manifest_new["spec"]["replicas"] = 1

    # Craft a custom observer_schema matching the resources in spec.manifest
    nginx_observer_schema_new = deepcopy(custom_deployment_observer_schema)
    nginx_observer_schema_new["metadata"]["name"] = "nginx-demo-2"

    # Craft the last_observed_manifest as it should be after the migration
    nginx_target_last_observed_manifest = deepcopy(
        initial_last_observed_manifest_deployment
    )
    nginx_target_last_observed_manifest["metadata"]["name"] = "nginx-demo-2"

    # The application is in RUNNING state on cluster_A, and is scheduled on cluster_B.
    # The controller should trigger a migration (i.e. delete exising resources defined
    # by last_observed_manifest on cluster_A and create new resources on cluster_B)
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster_A),
        status__scheduled_to=resource_ref(cluster_B),
        status__last_observed_manifest=[nginx_initial_last_observed_manifest_old],
        spec__manifest=[nginx_manifest_new],
        spec__observer_schema=[nginx_observer_schema_new],
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

        # The resource is received by the controller, which starts the migration and
        # updates the application in the DB accordingly.
        await controller.resource_received(app, start_observer=False)

    assert "nginx-demo-1" in kubernetes_server_A.app["deleted"]
    assert "nginx-demo-2" in kubernetes_server_B.app["created"]

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.last_observed_manifest == [nginx_target_last_observed_manifest]
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.status.running_on == resource_ref(cluster_B)
    assert resource_ref(cluster_A) not in stored.metadata.owners
    assert resource_ref(cluster_B) in stored.metadata.owners


async def test_app_deletion(aiohttp_server, config, db, loop):
    """Test the deletion of an application

    The Kubernetes Controller should delete the application and updates the DB.

    """
    kubernetes_app = web.Application()
    routes = web.RouteTableDef()

    deleted = set()

    # As part of the deletion, the k8s controller deletes the Deployment, Service, and
    # ConfigMap from the k8s cluster
    @routes.delete("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        deleted.add("Deployment")
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        deleted.add("Service")
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/default/configmaps/nginx-demo")
    async def _(request):
        deleted.add("ConfigMap")
        return web.Response(status=200)

    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # The application posses the deleted timestamp, meaning it should be deleted.
    app = ApplicationFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        spec__manifest=nginx_manifest,
        spec__observer_schema=custom_observer_schema,
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=resource_ref(cluster),
        status__running_on=resource_ref(cluster),
        status__last_observed_manifest=initial_last_observed_manifest,
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

    assert "Deployment" in deleted
    assert "Service" in deleted
    assert "ConfigMap" in deleted


async def test_register_service():
    """Test the register_service hook

    """
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
    """Test the creation of a Service and the registration of its endpoint

    """
    # Setup Kubernetes API mock server
    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if the Service already exists.
    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        # Service doesn't exist yet
        return web.Response(status=404)

    # The k8s controller creates the Service
    @routes.post("/api/v1/namespaces/default/services")
    async def _(request):
        return web.json_response(service_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=[service_manifest],
        spec__observer_schema=[custom_service_observer_schema],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The application is received by the Controller, which starts the reconciliation
        # loop, created the Service and updated the DB accordingly
        await controller.resource_received(app)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    # The API server of the Kubernetes cluster listens on "127.0.0.1"
    assert stored.status.services == {"nginx-demo": "127.0.0.1:32566"}


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
    """Test the deletion of a Service and test if the endpoint is removed from the
    application status

    """
    # Setup Kubernetes API mock server
    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller deletes the Service
    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # The application is RUNNING. A Service was previously created by Krake, and is
    # present in last_observed_manifest. The Service should now be deleted, as it's not
    # present in spec.manifest.
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=[],
        status__services={"nginx-demo": "127.0.0.1:32566"},
        status__last_observed_manifest=[initial_last_observed_manifest_service],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The application is received by the Controller, which starts the reconciliation
        # loop and deletes the Service. It should also remove the endpoint from the
        # application status
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
        return web.json_response(deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=[deployment_manifest],
        spec__observer_schema=[custom_deployment_observer_schema],
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
    for resource in stored.status.last_observed_manifest:
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
    for resource in stored.status.last_observed_manifest:
        if resource["kind"] != "Deployment":
            continue

        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "env" not in container

    assert stored.status.last_observed_manifest == app.spec.manifest
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
    for resource in stored.status.last_observed_manifest:
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
        status__last_observed_manifest=[],
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
        status__last_observed_manifest=[],
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


def test_resource_delta(loop):
    """Test if the controller correctly calculates the delta between
    ``last_applied_manifest`` and ``last_observed_manifest``


    State (0):
        The application posses a last_applied_manifest which specifies a Deployment, a
        Service and a ConfigMap. The application has a custom observer_schema which
        observes only part of the resources:
        - It observes the deployment's image, initialized by the given manifest file.
        - It observes the deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
        - The ConfigMap is not observed

        The application doesn't posses a last_observed_manifest.

        This state test the addition of observed and non observed resources to
        last_applied_manifest

    State (1):
        The application posses a last_observed_manifest which matches the
        last_applied_manifest.

    State (2):
        Update a field in the last_applied_manifest, which is observed and present in
        last_observed_manifest

    State (3):
        Update a field in the last_applied_manifest, which is observed and not present
        in last_observed_manifest

    State (4):
        Update a field in the last_applied_manifest, which is not observed and present
        in last_observed_manifest

    State (5):
        Update a field in the last_applied_manifest, which is not observed and not
        present in last_observed_manifest

    State (6):
        Update a field in the last_observed_manifest, which is observed and present in
        last_applied_manifest

    State (7):
        Update a field in the last_observed_manifest, which is observed and not
        present in last_applied_manifest

    State (8):
        Update a field in the last_observed_manifest, which is not observed and
        present in last_applied_manifest

    State (9):
        Update a field in the last_observed_manifest, which is not observed and not
        present in last_applied_manifest

    State (10):
        Add additional elements to a list in last_observed_manifest

    State (11):
        Remove elements from a list in last_observed_manifest

    State (12):
        Remove ConfigMap

    """

    # State(0): Observed and non observed resources are added to last_applied_manifest
    app = ApplicationFactory(
        spec__manifest=deepcopy(nginx_manifest),
        spec__observer_schema=deepcopy(custom_observer_schema),
    )

    update_last_applied_manifest_from_spec(app)

    deployment_object = serialize_k8s_object(deployment_response, "V1Deployment")
    service_object = serialize_k8s_object(service_response, "V1Service")
    configmap_object = serialize_k8s_object(configmap_response, "V1ConfigMap")

    # The deployment and services have to be created. The ConfigMap is not observed,
    # therefore not present in the list of resources to create.
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 3
    assert app.status.last_applied_manifest[0] in new  # Deployment
    assert app.status.last_applied_manifest[1] in new  # Service
    assert app.status.last_applied_manifest[2] in new  # ConfigMap
    assert len(deleted) == 0
    assert len(modified) == 0

    # State (1): The application posses a last_observed_manifest which matches the
    # last_applied_manifest.
    update_last_applied_manifest_from_resp(app, None, None, deployment_object)
    update_last_applied_manifest_from_resp(app, None, None, service_object)
    update_last_applied_manifest_from_resp(app, None, None, configmap_object)
    initial_last_applied_manifest = deepcopy(app.status.last_applied_manifest)
    app.status.last_observed_manifest = deepcopy(initial_last_observed_manifest)

    # No changes should be detected
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 0

    # State (2): Update a field in the last_applied_manifest, which is observed and
    # present in last_observed_manifest
    app.status.last_applied_manifest[1]["spec"]["type"] = "LoadBalancer"

    # The modification of an observed field should be detected (here in the Service
    # resource)
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 1
    assert app.status.last_applied_manifest[1] in modified  # Service

    # State (3): Update a field in the last_applied_manifest, which is observed and not
    # present in last_observed_manifest
    app.status.last_observed_manifest[1]["spec"].pop("type")

    # The modification of an observed field should be detected (here in the Service
    # resource)
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 1
    assert app.status.last_applied_manifest[1] in modified  # Service

    # State (4): Update a field in the last_applied_manifest, which is not observed and
    # present in last_observed_manifest
    app.status.last_applied_manifest = deepcopy(initial_last_applied_manifest)
    app.status.last_observed_manifest = deepcopy(initial_last_observed_manifest)
    app.spec.observer_schema[0]["spec"].pop("replicas")
    app.status.last_applied_manifest[0]["spec"]["replicas"] = 2

    # The modification of an non observed field should not trigger an update of the
    # Kubernetes resource.
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 0

    # State (5): Update a field in the last_applied_manifest, which is not observed and
    # not present in last_observed_manifest
    app.status.last_observed_manifest[0]["spec"].pop("replicas")

    # The modification of an non observed field should not trigger an update of the
    # Kubernetes resource.
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 0

    # State (6): Update a field in the last_observed_manifest, which is observed and
    # present in last_applied_manifest
    app.spec.observer_schema = deepcopy(custom_observer_schema)
    app.status.last_applied_manifest = deepcopy(initial_last_applied_manifest)
    app.status.last_observed_manifest = deepcopy(initial_last_observed_manifest)

    app.status.last_observed_manifest[1]["spec"]["type"] = "LoadBalancer"

    # The modification of an observed field should be detected (here in the Service
    # resource)
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 1
    assert app.status.last_applied_manifest[1] in modified  # Service

    # State (7): Update a field in the last_observed_manifest, which is observed and not
    # present in last_applied_manifest
    app.status.last_applied_manifest[1]["spec"].pop("type")

    # The modification of an observed field should be detected (here in the Service
    # resource)
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 1
    assert app.status.last_applied_manifest[1] in modified  # Service

    # State (8): Update a field in the last_observed_manifest, which is not observed and
    # present in last_applied_manifest
    app.status.last_applied_manifest = deepcopy(initial_last_applied_manifest)
    app.status.last_observed_manifest = deepcopy(initial_last_observed_manifest)
    app.status.last_observed_manifest[1]["spec"]["ports"][0]["protocol"] = "UDP"

    # The modification of an non observed field should not trigger an update of the
    # Kubernetes resource.
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 0

    # State (9): Update a field in the last_observed_manifest, which is not observed and
    # not present in last_applied_manifest
    app.status.last_applied_manifest[1]["spec"]["ports"][0].pop("protocol")

    # The modification of an non observed field should not trigger an update of the
    # Kubernetes resource.
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 0

    # State (10): Add additional elements to a list in last_observed_manifest
    app.status.last_applied_manifest = deepcopy(initial_last_applied_manifest)
    app.status.last_observed_manifest = deepcopy(initial_last_observed_manifest)
    app.status.last_observed_manifest[1]["spec"]["ports"].insert(
        -1, {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
    )
    app.status.last_observed_manifest[1]["spec"]["ports"][-1][
        "observer_schema_list_current_length"
    ] += 1

    # Number of elements is within the authorized list length. No update should be
    # triggered
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 0

    app.status.last_observed_manifest[1]["spec"]["ports"].insert(
        -1, {"nodePort": 32568, "port": 82, "protocol": "TCP", "targetPort": 82}
    )
    app.status.last_observed_manifest[1]["spec"]["ports"][-1][
        "observer_schema_list_current_length"
    ] += 1

    # Number of elements is above the authorized list length. Service should be
    # rollbacked
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 1
    assert app.status.last_applied_manifest[1] in modified  # Service

    # State (11): Remove elements from a list in last_observed_manifest
    app.spec.observer_schema[1]["spec"]["ports"][-1][
        "observer_schema_list_min_length"
    ] = 1
    app.status.last_observed_manifest[1]["spec"][
        "ports"
    ] = app.status.last_observed_manifest[1]["spec"]["ports"][-1:]
    app.status.last_observed_manifest[1]["spec"]["ports"][-1][
        "observer_schema_list_current_length"
    ] = 0

    # Number of elements is below the authorized list length. Service should be
    # rollbacked
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 0
    assert len(modified) == 1
    assert app.status.last_applied_manifest[1] in modified  # Service

    # State (12): Remove ConfigMap
    app.status.last_applied_manifest = deepcopy(initial_last_applied_manifest)
    app.status.last_observed_manifest = deepcopy(initial_last_observed_manifest)
    app.spec.observer_schema.pop(2)
    app.spec.manifest.pop(2)
    app.status.last_applied_manifest.pop(2)

    # ConfigMap should be deleted
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 1
    assert len(modified) == 0
    assert app.status.last_observed_manifest[2] in deleted  # ConfigMap
