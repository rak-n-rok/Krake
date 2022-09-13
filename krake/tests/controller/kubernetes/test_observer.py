import asyncio
import json
import datetime
from contextlib import suppress

import pytest
from aiohttp import web, ClientConnectorError
from copy import deepcopy

from aiohttp.client_reqrep import ConnectionKey
from mock import mock

from krake.controller.kubernetes.hooks import client as k8s_client_hooks
from krake.api.app import create_app
from krake.controller.kubernetes.cluster import KubernetesClusterController
from krake.controller.kubernetes.hooks import (
    unregister_observer,
    register_observer,
    update_last_applied_manifest_from_spec,
    update_last_applied_manifest_from_resp,
    update_last_observed_manifest_from_resp,
    generate_default_observer_schema,
)
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState, ClusterState, Cluster
from krake.controller.kubernetes.application import KubernetesApplicationController
from krake.controller.kubernetes.hooks import (
    KubernetesApplicationObserver,
)
from krake.client import Client
from krake.test_utils import server_endpoint, get_first_container, serialize_k8s_object

from tests.factories.fake import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)

from tests.controller.kubernetes import (
    deployment_manifest,
    service_manifest,
    nginx_manifest,
    custom_deployment_observer_schema,
    custom_service_observer_schema,
    custom_observer_schema,
    mangled_observer_schema,
    deployment_response,
    service_response,
    secret_response,
    initial_last_observed_manifest_deployment,
    initial_last_observed_manifest_service,
    initial_last_observed_manifest,
)


async def test_reception_for_application_observer(aiohttp_server, config, db, loop):
    """Test the condition to start an Observer

    When an received application is in PENDING state, no Observer should be started.

    When an application is RUNNING, an Observer should be started.

    """
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
        controller = KubernetesApplicationController(
            server_endpoint(server), worker_count=0
        )
        # Update the client, to be used by the background tasks
        await controller.prepare(client)  # need to be called explicitly
        await controller.application_reflector.list_resource()
    # Each running Application has a corresponding observer
    assert len(controller.observers) == 1
    assert running.metadata.uid in controller.observers


async def test_observer_temporarily_unreachable_cluster(
    aiohttp_server, config, db, loop
):
    """Test the behavior of the Kubernetes Controller and Observer when an application
    is deployed in the temporarily unreachable cluster.

    If the cluster is temporarily unreachable the last known application status is
    returned from :func:`poll_resource`. The application status should not change
    as we do not know the real current state.

    """
    routes = web.RouteTableDef()
    # Cluster API is online and responds with HTTP 200 return code
    is_cluster_offline = False

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal is_cluster_offline
        if is_cluster_offline:
            return web.Response(status=503)

        return web.json_response(service_response)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal is_cluster_offline
        if is_cluster_offline:
            return web.Response(status=503)

        return web.json_response(deployment_response)

    @routes.get("/api/v1/namespaces/secondary/secrets/nginx-demo")
    async def _(request):
        nonlocal is_cluster_offline
        if is_cluster_offline:
            return web.Response(status=503)

        return web.json_response(secret_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__mangled_observer_schema=mangled_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
        status__last_applied_manifest=nginx_manifest,
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(
            server_endpoint(server), worker_count=0, time_step=-1
        )
        await controller.prepare(client)

        await register_observer(controller, app)
        observer, _ = controller.observers[app.metadata.uid]
        # Observe a resource actually in deletion.
        before = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        await observer.observe_resource()
        # Transmit cluster API to the offline state, responds with HTTP 503 return code
        is_cluster_offline = True
        await observer.observe_resource()
        after = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        # The application should not change as we do not know the real current state
        assert after == before


async def test_observer_on_poll_update(aiohttp_server, db, config, loop):
    """Test the Observer's behavior on update of a resource on the k8s cluster directly

    This test goes through the following scenario:

    State (0):
        A Deployment, a Service and a Secret are present, the Deployment has an
        nginx image with version "1.7.9". The service defines 1 port using the "TCP"
        protocol. A custom observer schema is used:
        - It observes the deployment's image, initialized by the given manifest file.
        - It observes the deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
        - The presence of the Secret is observed
    State (1):
        The Deployment image version changed to "1.6".
    State (2):
        The Deployment replicas count is changed to 2.
    State (3):
        The Service's first port's protocol is changed to "UDP"
    State (4):
        A second port is added to the Service.
    State (5):
        A third port is added to the Service.
    State (6):
        All ports are removed from the Service.
    State (7):
        The Secret is deleted

    For each state, it is tested if the Kubernetes Observer detects the update and calls
    the ``on_res_update`` method.

    """
    routes = web.RouteTableDef()

    # When the Observer observes the application, it queries the k8s API to get the
    # current state of each of the application resources
    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0 or actual_state in range(3, 8):
            # The Deployment has not been modified on the cluster
            return web.json_response(deployment_response)

        updated_deployment_response = deepcopy(deployment_response)
        if actual_state == 1:
            # State (1): The Deployment image version changed to "1.6".
            first_container = get_first_container(updated_deployment_response)
            first_container["image"] = "nginx:1.6"

        elif actual_state == 2:
            # State (2): The Deployment replicas count is changed to 2.
            updated_deployment_response["spec"]["replicas"] = 2

        return web.json_response(updated_deployment_response)

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in (0, 1, 2, 7):
            # The Service has not been modified on the cluster
            return web.json_response(service_response)

        updated_service_response = deepcopy(service_response)
        if actual_state == 3:
            # State (3): The Service's first port's protocol is changed to "UDP"
            updated_service_response["spec"]["ports"][0]["protocol"] = "UDP"

        elif actual_state == 4:
            # State (4): A second port is added to the Service.
            updated_service_response["spec"]["ports"].append(
                {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
            )

        elif actual_state == 5:
            # State (5): A third port is added to the Service.
            updated_service_response["spec"]["ports"].append(
                {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
            )
            updated_service_response["spec"]["ports"].append(
                {"nodePort": 32568, "port": 82, "protocol": "TCP", "targetPort": 82}
            )

        elif actual_state == 6:
            # State (6): All ports are removed from the Service.
            updated_service_response["spec"]["ports"] = []

        return web.json_response(updated_service_response)

    @routes.get("/api/v1/namespaces/secondary/secrets/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in range(0, 7):
            # The Secret has not been modified on the cluster
            return web.json_response(secret_response)
        elif actual_state == 7:
            # State (7): The Secret is deleted
            return web.Response(status=404)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__mangled_observer_schema=mangled_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
        status__last_applied_manifest=nginx_manifest,
    )

    calls_to_res_update = 0

    async def on_res_update(resource):
        assert resource.metadata.name == app.metadata.name

        nonlocal calls_to_res_update, actual_state
        calls_to_res_update += 1
        manifests = resource.status.last_observed_manifest

        ports_length = manifests[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]

        if actual_state == 0:
            # As no changes are noticed by the Observer, the res_update function will
            # not be called.
            assert False

        elif actual_state == 1:
            # State (1): The Deployment image version changed to "1.6"
            status_image = get_first_container(manifests[0])["image"]
            assert status_image == "nginx:1.6"
            # Three resources are observed
            assert len(manifests) == 3

        elif actual_state == 2:
            # State (2): The Deployment replicas count is changed to 2.
            assert manifests[0]["spec"]["replicas"] == 2

        elif actual_state == 3:
            # State (3): The Service's first port's protocol is changed to "UDP"
            # As this field is *not* observed, the ``on_res_update`` method shouldn't be
            # called.
            assert False

        elif actual_state == 4:
            # State (4): A second port is added to the Service.
            # Check the current length of the list of ports according to the Observer.
            assert ports_length == 2

        elif actual_state == 5:
            # State (5): A third port is added to the Service.
            # Check the current length of the list of ports according to the Observer.
            assert ports_length == 3

        elif actual_state == 6:
            # State (6): All ports are removed from the Service.
            # Check the current length of the list of ports according to the Observer.
            assert ports_length == 0

        elif actual_state == 7:
            # State (7): The Secret is deleted
            assert len(manifests) == 2

    observer = KubernetesApplicationObserver(cluster, app, on_res_update, time_step=-1)

    # Observe an unmodified resource
    # As no changes are noticed by the Observer, the res_update function will not be
    # called.
    actual_state = 0
    assert calls_to_res_update == 0

    # Modify the actual resource "externally"
    actual_state = 1
    await observer.observe_resource()
    assert calls_to_res_update == 1

    # Delete the service "externally"
    actual_state = 2
    await observer.observe_resource()
    assert calls_to_res_update == 2

    # State (3): The Service's first port's protocol is changed to "UDP"
    # As this field is *not* observed, the ``on_res_update`` method shouldn't be called
    actual_state = 3
    await observer.observe_resource()
    assert calls_to_res_update == 2

    # State (4): A second port is added to the Service.
    actual_state = 4
    await observer.observe_resource()
    assert calls_to_res_update == 3

    # State (5): A third port is added to the Service.
    actual_state = 5
    await observer.observe_resource()
    assert calls_to_res_update == 4

    # State (6): All ports are removed from the Service.
    actual_state = 6
    await observer.observe_resource()
    assert calls_to_res_update == 5

    # State (7): The Secret is deleted
    actual_state = 7
    await observer.observe_resource()
    assert calls_to_res_update == 6


def set_default_namespace(response):
    """Creates a copy of the given Kubernetes API response, where the namespaces have
    been reset to the default one.

    Args:
        response (dict): the response to modify.

    Returns:
        dict: a copy of the original response, with the namespaces updated.

    """
    copy = deepcopy(response)
    default_namespace = "default"
    original_namespace = copy["metadata"]["namespace"]

    new_self_link = copy["metadata"]["selfLink"].replace(
        original_namespace, default_namespace
    )
    copy["metadata"]["selfLink"] = new_self_link

    copy["metadata"]["namespace"] = default_namespace
    return copy


async def test_observer_on_poll_update_default_namespace(
    aiohttp_server, db, config, loop
):
    """Test the Observer's behavior on update of an actual resource which has been
    created WITHOUT any namespace, and for which the cluster's kubeconfig also did not
    specify any namespace.

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

    deployment = set_default_namespace(deployment_response)
    service = set_default_namespace(service_response)

    # Actual resource, with container image and selector changed
    updated_app = deepcopy(deployment)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"
    # Test the observation of changes on values with a CamelCase format
    updated_app["spec"]["selector"]["matchLabels"] = {"app": "foo"}

    accepted = "default"
    called_get = False
    called_post = False

    @routes.get("/api/v1/namespaces/{namespace}/services/nginx-demo")
    async def _(request):
        nonlocal called_get
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_get = True

        nonlocal actual_state
        if actual_state in (0, 1):
            return web.json_response(service)
        elif actual_state == 2:
            return web.Response(status=404)

    @routes.get("/apis/apps/v1/namespaces/{namespace}/deployments/nginx-demo")
    async def _(request):
        nonlocal called_post
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_post = True

        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(deployment)
        elif actual_state >= 1:
            return web.json_response(updated_app)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # Create a manifest with resources without any namespace.
    copy_nginx_manifest = deepcopy(nginx_manifest)
    for resource in copy_nginx_manifest:
        del resource["metadata"]["namespace"]

    # Adapt namespace in mangled observer schema and last observed manifest
    copy_mangled_observer_schema = deepcopy(mangled_observer_schema)
    for resource in copy_mangled_observer_schema:
        resource["metadata"]["namespace"] = "default"

    copy_initial_last_observed_manifest = deepcopy(initial_last_observed_manifest)
    for resource in copy_initial_last_observed_manifest:
        resource["metadata"]["namespace"] = "default"

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=copy_nginx_manifest,
        status__mangled_observer_schema=copy_mangled_observer_schema,
        status__last_observed_manifest=copy_initial_last_observed_manifest,
        status__last_applied_manifest=copy_nginx_manifest,
    )

    calls_to_res_update = 0

    async def on_res_update(resource):
        assert resource.metadata.name == app.metadata.name

        nonlocal calls_to_res_update, actual_state
        calls_to_res_update += 1

        manifests = resource.status.last_observed_manifest
        status_image = get_first_container(manifests[0])["image"]
        if actual_state == 0:
            # As no changes are noticed by the Observer, the res_update function will
            # not be called.
            assert False, "The first poll of the observer should not issue an update."
        elif actual_state == 1:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 2
        elif actual_state == 2:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 1
            assert manifests[0]["kind"] == "Deployment"

        # The spec never changes
        spec_image = get_first_container(resource.spec.manifest[0])["image"]
        assert spec_image == "nginx:1.7.9"

    observer = KubernetesApplicationObserver(cluster, app, on_res_update, time_step=-1)

    # Observe an unmodified resource
    # As no changes are noticed by the Observer, the res_update function will not be
    # called.
    actual_state = 0
    assert calls_to_res_update == 0

    # State (1): The Deployment image version changed to "1.6"
    actual_state = 1
    await observer.observe_resource()
    assert calls_to_res_update == 1

    # State (2): The Deployment replicas count is changed to 2.
    actual_state = 2
    await observer.observe_resource()
    assert calls_to_res_update == 2

    assert called_get and called_post, "GET and POST did not get call at least once."


async def test_observer_on_poll_update_cluster_default_namespace(
    aiohttp_server, db, config, loop
):
    """Test the Observer's behavior on update of an actual resource which has been
    created WITHOUT any namespace, but where a default namespace has been set in the
    Cluster's kubeconfig.

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

    deployment = set_default_namespace(deployment_response)
    service = set_default_namespace(service_response)

    # Actual resource, with container image and selector changed
    updated_app = deepcopy(deployment)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"
    # Test the observation of changes on values with a CamelCase format
    updated_app["spec"]["selector"]["matchLabels"] = {"app": "foo"}

    accepted = "another_namespace"
    called_get = False
    called_post = False

    @routes.get("/api/v1/namespaces/{namespace}/services/nginx-demo")
    async def _(request):
        nonlocal called_get
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_get = True

        nonlocal actual_state
        if actual_state in (0, 1):
            return web.json_response(service)
        elif actual_state == 2:
            return web.Response(status=404)

    @routes.get("/apis/apps/v1/namespaces/{namespace}/deployments/nginx-demo")
    async def _(request):
        nonlocal called_post
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_post = True

        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(deployment)
        elif actual_state >= 1:
            return web.json_response(updated_app)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    # Replace the default namespace in the kubeconfig file
    kubeconfig = make_kubeconfig(kubernetes_server)
    kubeconfig["contexts"][0]["context"]["namespace"] = "another_namespace"
    cluster = ClusterFactory(spec__kubeconfig=kubeconfig)

    # Create a manifest with resources without any namespace.
    copy_nginx_manifest = deepcopy(nginx_manifest)
    for resource in copy_nginx_manifest:
        del resource["metadata"]["namespace"]

    # Adapt namespace in mangled observer schema and last observed manifest
    copy_mangled_observer_schema = deepcopy(mangled_observer_schema)
    for resource in copy_mangled_observer_schema:
        resource["metadata"]["namespace"] = "another_namespace"

    copy_initial_last_observed_manifest = deepcopy(initial_last_observed_manifest)
    for resource in copy_initial_last_observed_manifest:
        resource["metadata"]["namespace"] = "another_namespace"

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=copy_nginx_manifest,
        status__last_observed_manifest=copy_initial_last_observed_manifest,
        status__mangled_observer_schema=copy_mangled_observer_schema,
        status__last_applied_manifest=copy_nginx_manifest,
    )

    calls_to_res_update = 0

    async def on_res_update(resource):
        assert resource.metadata.name == app.metadata.name

        nonlocal calls_to_res_update, actual_state
        calls_to_res_update += 1

        manifests = resource.status.last_observed_manifest
        status_image = get_first_container(manifests[0])["image"]
        if actual_state == 0:
            # As no changes are noticed by the Observer, the res_update function will
            # not be called.
            assert False, "The first poll of the observer should not issue an update."
        elif actual_state == 1:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 2
        elif actual_state == 2:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 1
            assert manifests[0]["kind"] == "Deployment"

        # The spec never changes
        spec_image = get_first_container(resource.spec.manifest[0])["image"]
        assert spec_image == "nginx:1.7.9"

    observer = KubernetesApplicationObserver(cluster, app, on_res_update, time_step=-1)

    # Observe an unmodified resource
    # As no changes are noticed by the Observer, the res_update function will not be
    # called.
    actual_state = 0
    assert calls_to_res_update == 0

    # Modify the actual resource "externally"
    actual_state = 1
    await observer.observe_resource()
    assert calls_to_res_update == 1

    # Delete the service "externally"
    actual_state = 2
    await observer.observe_resource()
    assert calls_to_res_update == 2

    assert called_get and called_post, "GET and POST did not get call at least once."


async def test_observer_on_poll_update_manifest_namespace_set(
    aiohttp_server, db, config, loop
):
    """Test the Observer's behavior on update of an actual resource which has been
    created with a defined namespace, but where a default namespace has been set in the
    Cluster's kubeconfig. The manifest file's namespace should be used.

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

    deployment = set_default_namespace(deployment_response)
    service = set_default_namespace(service_response)

    # Actual resource, with container image and selector changed
    updated_app = deepcopy(deployment)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"
    # Test the observation of changes on values with a CamelCase format
    updated_app["spec"]["selector"]["matchLabels"] = {"app": "foo"}

    accepted = "secondary"
    called_get = False
    called_post = False

    @routes.get("/api/v1/namespaces/{namespace}/services/nginx-demo")
    async def _(request):
        nonlocal called_get
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_get = True

        nonlocal actual_state
        if actual_state in (0, 1):
            return web.json_response(service)
        elif actual_state == 2:
            return web.Response(status=404)

    @routes.get("/apis/apps/v1/namespaces/{namespace}/deployments/nginx-demo")
    async def _(request):
        nonlocal called_post
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_post = True

        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(deployment)
        elif actual_state >= 1:
            return web.json_response(updated_app)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    # Replace the default namespace in the kubeconfig file
    kubeconfig = make_kubeconfig(kubernetes_server)
    kubeconfig["contexts"][0]["context"]["namespace"] = "another_namespace"
    cluster = ClusterFactory(spec__kubeconfig=kubeconfig)

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__last_observed_manifest=initial_last_observed_manifest,
        status__last_applied_manifest=nginx_manifest,
    )

    calls_to_res_update = 0

    async def on_res_update(resource):
        assert resource.metadata.name == app.metadata.name

        nonlocal calls_to_res_update, actual_state
        calls_to_res_update += 1

        manifests = resource.status.last_observed_manifest
        status_image = get_first_container(manifests[0])["image"]
        if actual_state == 0:
            # As no changes are noticed by the Observer, the res_update function will
            # not be called.
            assert False, "The first poll of the observer should not issue an update."
        elif actual_state == 1:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 2
        elif actual_state == 2:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 1
            assert manifests[0]["kind"] == "Deployment"

        # The spec never changes
        spec_image = get_first_container(resource.spec.manifest[0])["image"]
        assert spec_image == "nginx:1.7.9"

    generate_default_observer_schema(app)
    observer = KubernetesApplicationObserver(cluster, app, on_res_update, time_step=-1)

    # Observe an unmodified resource
    # As no changes are noticed by the Observer, the res_update function will not be
    # called.
    actual_state = 0
    assert calls_to_res_update == 0

    # Modify the actual resource "externally"
    actual_state = 1
    await observer.observe_resource()
    assert calls_to_res_update == 1

    # Delete the service "externally"
    actual_state = 2
    await observer.observe_resource()
    assert calls_to_res_update == 2

    assert called_get and called_post, "GET and POST did not get call at least once."


async def test_observer_on_status_update(aiohttp_server, db, config, loop):
    """Test the behavior of the ``on_status_update`` method of the Kubernetes Controller

    The status of the k8s resource changed on the cluster:
    - The container image has changed to "1.6". This field is observed.
    - The replicas count has changed to 2. This field is observed, though not
    initialized by the manifest file
    - The Service's first port's protocol has changed to "UDP". Though initialized by
    the manifest file, this field is not observed.
    - The Service's posses a second port.

    This test ensures that the Krake resource's status is updated accordingly.

    """
    routes = web.RouteTableDef()

    updated_service_response = deepcopy(service_response)
    updated_deployment_response = deepcopy(deployment_response)

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        # The Service's first port's protocol is changed to "UDP"
        updated_service_response["spec"]["ports"][0]["protocol"] = "UDP"
        # A second port is added to the Service.
        updated_service_response["spec"]["ports"].append(
            {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
        )
        return web.json_response(updated_service_response)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        first_container = get_first_container(updated_deployment_response)
        first_container["image"] = "nginx:1.6"
        updated_deployment_response["spec"]["replicas"] = 2
        return web.json_response(updated_deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__mangled_observer_schema=mangled_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
        spec__manifest=nginx_manifest,
        status__last_applied_manifest=nginx_manifest,
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(
            server_endpoint(server), worker_count=0
        )
        await controller.prepare(client)

        observer = KubernetesApplicationObserver(
            cluster, app, controller.on_status_update, time_step=-1
        )

        await observer.observe_resource()
        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )

        # The spec, the last_applied_manifest and the created timestamp didn't change
        assert updated.spec == app.spec
        assert updated.status.last_applied_manifest == app.status.last_applied_manifest
        assert updated.metadata.created == app.metadata.created

        # The last_observed_manifest has been updated for the observed fields only
        last_observed_manifest = updated.status.last_observed_manifest
        first_container = get_first_container(last_observed_manifest[0])
        assert first_container["image"] == "nginx:1.6"
        assert last_observed_manifest[0]["spec"]["replicas"] == 2
        ports_length = last_observed_manifest[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]
        assert ports_length == 2

        # Protocol of first port is not observed
        assert "protocol" not in last_observed_manifest[1]["spec"]["ports"][0]
        # Secret is not observed
        assert len(last_observed_manifest) == 2
        assert last_observed_manifest[0]["kind"] == "Deployment"
        assert last_observed_manifest[1]["kind"] == "Service"


async def test_observer_on_status_update_mangled(
    aiohttp_server, db, config, loop, hooks_config
):
    """Test the ``on_status_update`` method of the Kubernetes Controller in case of
    an Application mangled with the "complete" hook.

    State (0):
        the Application is created, the hook is added.
    State (1):
        the Kubernetes resources are not changed and the Observer is called. It should
        not trigger an update of the application
    State (2):
        the Kubernetes resources are changed and the Observer is called. It should
        trigger an update of the application

    """
    routes = web.RouteTableDef()

    actual_state = 0
    deploy_mangled_response = deepcopy(deployment_response)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):

        nonlocal deploy_mangled_response
        rd = await request.read()

        app = json.loads(rd)

        app_first_container = get_first_container(app)
        resp_first_container = get_first_container(deploy_mangled_response)
        resp_first_container["env"] = app_first_container["env"]

        return web.json_response(deploy_mangled_response)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.Response(status=404)  # needed for controller.resource_received
        if actual_state == 1:
            return web.json_response(deploy_mangled_response)
        if actual_state == 2:
            updated_deployment_response = deepcopy(deploy_mangled_response)
            first_container = get_first_container(updated_deployment_response)
            first_container["image"] = "nginx:1.6"
            return web.json_response(updated_deployment_response)

    @routes.post("/api/v1/namespaces/secondary/secrets")
    async def _(request):
        return web.json_response(secret_response)

    @routes.post("/api/v1/namespaces/secondary/services")
    async def _(request):
        return web.json_response(service_response)

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.Response(status=404)
        elif actual_state >= 1:
            return web.json_response(service_response)

    @routes.get("/api/v1/namespaces/secondary/secrets/nginx-demo")
    async def _(request):
        return web.json_response(secret_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        spec__observer_schema=custom_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
        spec__hooks=["complete"],
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    calls_to_res_update = 0

    def update_decorator(func):
        async def on_res_update(resource):
            nonlocal calls_to_res_update, actual_state
            calls_to_res_update += 1

            if actual_state == 1:
                # Ensure that the Observer is not notifying the Controller
                assert False

            await func(resource)

        return on_res_update

    async with Client(url=server_endpoint(server), loop=loop) as client:
        generate_default_observer_schema(app)
        controller = KubernetesApplicationController(
            server_endpoint(server), worker_count=0, hooks=hooks_config
        )
        controller.on_status_update = update_decorator(controller.on_status_update)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)
        # Remove from dict to prevent cancellation in
        # KubernetesApplicationController.stop_observer
        observer, _ = controller.observers.pop(app.metadata.uid)

        assert "env" in get_first_container(
            observer.resource.status.mangled_observer_schema[0]
        )

        actual_state = 1

        # The observer should not call on_res_update
        await observer.observe_resource()
        assert calls_to_res_update == 0

        actual_state = 2

        await observer.observe_resource()
        assert calls_to_res_update == 1

        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert updated.spec.manifest == app.spec.manifest
        # Check that the hook is present and observed in the stored Application
        assert "env" in get_first_container(updated.status.last_observed_manifest[0])
        assert "env" in get_first_container(updated.status.mangled_observer_schema[0])
        assert updated.metadata.created == app.metadata.created
        # Check update of observed image
        first_container = get_first_container(updated.status.last_observed_manifest[0])
        assert first_container["image"] == "nginx:1.6"


async def check_observer_does_not_update(observer, app, db):
    """Ensure that the given observer is up-to-date with the Application on the API.

    Args:
        observer (KubernetesApplicationObserver): the observer to check.
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
    """Test the connectivity between the Controller and Observer on update of a
    resource by the API.

    In this test, the resource is updated from the Krake API. The Observer should not
    take any actions.

    State (0):
        a Deployment and a Service are present with standard observer schema. The
        Deployment has an nginx image with version "1.7.9"
    State (1):
        both resources are still present, but the API changed the Deployment image
        version to "1.6".
    State (2):
        the Service is deleted by the API and removed from the observer schema. Only
        the Deployment is present, with the version "1.6"

    """
    routes = web.RouteTableDef()

    actual_state = 0

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in (0, 1):
            return web.json_response(service_response)
        elif actual_state == 2:
            return web.Response(status=404)

    updated_deployment_response = deepcopy(deployment_response)
    first_container = get_first_container(updated_deployment_response)
    first_container["image"] = "nginx:1.6"

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(deployment_response)
        elif actual_state >= 1:
            return web.json_response(updated_deployment_response)

    @routes.patch("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(deployment_response)
        elif actual_state >= 1:
            return web.json_response(updated_deployment_response)

    @routes.patch("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        assert actual_state in (0, 2)
        return web.json_response(service_response)

    @routes.delete("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        assert actual_state == 2
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
        spec__observer_schema=[
            custom_deployment_observer_schema,
            custom_service_observer_schema,
        ],
        status__last_observed_manifest=[
            initial_last_observed_manifest_deployment,
            initial_last_observed_manifest_service,
        ],
        spec__manifest=deepcopy([deployment_manifest, service_manifest]),
        metadata__finalizers=["kubernetes_resources_deletion"],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    def update_decorator(func):
        async def on_res_update(resource):
            # As the update on resources is performed by the API, the Observer should
            # never see a difference on the actual resource, and thus, the current
            # function should never be called
            assert False

        return on_res_update

    async def mock():
        # When a resource is updated, the task corresponding to the observer is stopped
        # automatically. This mock is used as a fake task to cancel
        await asyncio.sleep(1)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(
            server_endpoint(server), worker_count=0
        )
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

        actual_state = 1
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

        actual_state = 2

        # Modify the manifest and the observer_schema of the Application
        after_1.spec.manifest = after_1.spec.manifest[:1]
        after_1.spec.observer_schema = after_1.spec.observer_schema[:1]
        after_1.status.state = ApplicationState.RUNNING
        await db.put(after_1)

        # Update the actual resource
        await controller.resource_received(after_1, start_observer=False)
        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Status should not be updated by observer
        await check_observer_does_not_update(obs, app, db)


async def test_observer_on_delete(aiohttp_server, config, db, loop):
    """Test the behavior of the Kubernetes Controller and Observer when an application
    is being deleted.

    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        return web.json_response(service_response)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.json_response(deployment_response)

    @routes.get("/api/v1/namespaces/secondary/secrets/nginx-demo")
    async def _(request):
        return web.json_response(secret_response)

    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/secondary/secrets/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        metadata__deleted=fake.date_time(),
        status__state=ApplicationState.RUNNING,
        status__mangled_observer_schema=mangled_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        metadata__finalizers=["kubernetes_resources_deletion"],
        status__last_applied_manifest=nginx_manifest,
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(
            server_endpoint(server), worker_count=0, time_step=100
        )
        await controller.prepare(client)

        # Start the observer, which will not observe due to time step
        await register_observer(controller, app)
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


@pytest.mark.slow
async def test_observer_creation_deletion(aiohttp_server, config, db, loop):
    """Test the creation and cleanup of the observers when Applications are received by
    the reflector.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(_):
        return web.json_response(service_response)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(_):
        return web.json_response(deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    scheduled_apps = [
        ApplicationFactory(
            status__state=ApplicationState.RUNNING,
            status__mangled_observer_schema=mangled_observer_schema,
            status__last_observed_manifest=initial_last_observed_manifest,
            status__running_on=resource_ref(cluster),
            spec__manifest=nginx_manifest,
            metadata__finalizers=["kubernetes_resources_deletion"],
        )
        for _ in range(2)
    ]
    await db.put(cluster)
    for scheduled in scheduled_apps:
        await db.put(scheduled)

    server = await aiohttp_server(create_app(config))

    controller = KubernetesApplicationController(
        server_endpoint(server), worker_count=0, time_step=1
    )

    run_task = None
    try:
        run_task = loop.create_task(controller.run())

        # Wait for the observers to poll their resource.
        await asyncio.sleep(3)

        assert len(controller.observers) == 2
    finally:
        # Trigger the cleanup
        if run_task is not None:
            run_task.cancel()
            with suppress(asyncio.CancelledError):
                await run_task

    assert len(controller.observers) == 0


def test_update_last_applied_manifest_from_spec():
    """Test the ``update_last_applied_manifest_from_spec`` function.

    An application containing a Deployment is created. The default observer schema is
    used.

    State (0):
        `last_applied_manifest` is empty. It should be initialized to spec.manifest

    State (1):
        The Deployment's manifest file specifies a value for the previously unset
        `revisionHistoryLimit` and `progressDeadlineSeconds`. Only the first one is
        observed.

    State (2):
        The Deployment's manifest file specifies a new value for the previously set
        `revisionHistoryLimit` and `progressDeadlineSeconds`.

    State (3):
        The Deployment's manifest doesn't specify the previously set
        `revisionHistoryLimit` and `progressDeadlineSeconds`.
    """

    app = ApplicationFactory(spec__manifest=deepcopy([deployment_manifest]))

    # State (0): last_applied_manifest` is empty. It should be initialized to
    # spec.manifest
    generate_default_observer_schema(app)
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest == app.spec.manifest

    # State (1): The Deployment's manifest file specifies a value for the previously
    # unset `revisionHistoryLimit` and `progressDeadlineSeconds`. Only the first one is
    # observed.
    app.status.mangled_observer_schema[0]["spec"]["revisionHistoryLimit"] = None
    app.spec.manifest[0]["spec"]["revisionHistoryLimit"] = 20
    app.spec.manifest[0]["spec"]["progressDeadlineSeconds"] = 300

    # Both values should be initialized
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest[0]["spec"]["revisionHistoryLimit"] == 20
    assert app.status.last_applied_manifest[0]["spec"]["progressDeadlineSeconds"] == 300

    # State (1): The Deployment's manifest file specifies a value for the previously
    # unset `revisionHistoryLimit` and `progressDeadlineSeconds`. Only the first one is
    # observed.
    app.status.mangled_observer_schema[0]["spec"]["revisionHistoryLimit"] = None
    app.spec.manifest[0]["spec"]["revisionHistoryLimit"] = 20
    app.spec.manifest[0]["spec"]["progressDeadlineSeconds"] = 300

    # Both values should be initialized
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest[0]["spec"]["revisionHistoryLimit"] == 20
    assert app.status.last_applied_manifest[0]["spec"]["progressDeadlineSeconds"] == 300

    # State (2): The Deployment's manifest file specifies a new value for previously
    # set `revisionHistoryLimit` and `progressDeadlineSeconds`.
    app.spec.manifest[0]["spec"]["revisionHistoryLimit"] = 40
    app.spec.manifest[0]["spec"]["progressDeadlineSeconds"] = 600

    # Both values should be updated
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest[0]["spec"]["revisionHistoryLimit"] == 40
    assert app.status.last_applied_manifest[0]["spec"]["progressDeadlineSeconds"] == 600

    # State (3): The Deployment's manifest doesn't specify previously set
    # `revisionHistoryLimit` and `progressDeadlineSeconds`.
    app.spec.manifest[0]["spec"].pop("revisionHistoryLimit")
    app.spec.manifest[0]["spec"].pop("progressDeadlineSeconds")

    # Only the observed field should be kept.
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest[0]["spec"]["revisionHistoryLimit"] == 40
    assert "progressDeadlineSeconds" not in app.status.last_applied_manifest[0]["spec"]


def test_update_last_applied_manifest_from_spec_multiple_types():
    """Test the ``update_last_applied_manifest_from_spec`` function.

    An application containing a Deployment is created. The default observer schema is
    used. Multiple types are tested for the ``last_applied_manifest``.

    State (0):
        `last_applied_manifest` is empty. It should be initialized to spec.manifest

    State (1):
        The manifest is extended with a list in list structure.

    State (2):
        The manifest is extended with a dict in list structure.

    State (3):
        The manifest is extended with a list in dict structure.

    State (4):
        The manifest is extended with a dict in dict structure.
    """

    app = ApplicationFactory(spec__manifest=deepcopy([deployment_manifest]))

    # State (0): last_applied_manifest` is empty. It should be initialized to
    # spec.manifest
    generate_default_observer_schema(app)
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest == app.spec.manifest

    # State (1): The manifest is extended with a list in list structure.
    app.spec.manifest[0]["spec"]["containers"] = [["List in List"]]

    # Both values should be initialized
    update_last_applied_manifest_from_spec(app)
    assert (
        app.status.last_applied_manifest[0]["spec"]["containers"][0][0]
        == "List in List"
    )

    # State (2): The manifest is extended with a dict in list structure.
    app.spec.manifest[0]["spec"]["containers"] = [{"dict": "Dict in List"}]

    # Both values should be initialized
    update_last_applied_manifest_from_spec(app)
    assert (
        app.status.last_applied_manifest[0]["spec"]["containers"][0]["dict"]
        == "Dict in List"
    )

    # State (3): The manifest is extended with a list in dict structure.
    app.spec.manifest[0]["spec"]["containers"] = {"dict": ["List in Dict"]}

    # Both values should be initialized
    update_last_applied_manifest_from_spec(app)
    assert (
        app.status.last_applied_manifest[0]["spec"]["containers"]["dict"][0]
        == "List in Dict"
    )

    # State (4): The manifest is extended with a dict in dict structure.
    app.spec.manifest[0]["spec"]["containers"] = {"dict": {"dict": "Dict in Dict"}}

    # Both values should be initialized
    update_last_applied_manifest_from_spec(app)
    assert (
        app.status.last_applied_manifest[0]["spec"]["containers"]["dict"]["dict"]
        == "Dict in Dict"
    )


async def test_update_last_applied_manifest_from_resp(loop):
    """Test the ``update_last_applied_manifest_from_resp`` function.

    This function is called to update ``status.last_applied_manifest`` from a
    Kubernetes response. Only observed fields which are not yet initialized should be
    created by this function.

    State (0):
        A Deployment and a Service are present, the Deployment has an nginx image with
        version "1.7.9". The Service defines 1 port using the "TCP" protocol. A custom
        observer schema is used:
        - It observes the Deployment's image, initialized by the given manifest file.
        - It observes the Deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
    State (1):
        The Deployment image version changed to "1.6".
    State (2):
        The Deployment replicas count is changed to 2.
    State (3):
        The Service's first port's protocol is changed to "UDP"
    State (4):
        A second port is added to the Service.
    State (5):
        A third port is added to the Service.
    State (6):
        All ports are removed from the Service.

    """

    cluster = ClusterFactory()

    # Create an application using a custom observer schema
    # The last_applied_manifest is initialized with the `spec.manifest` as in the
    # normal workflow (taking aside mangling)
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=[deployment_manifest, service_manifest],
        spec__observer_schema=[
            custom_deployment_observer_schema,
            custom_service_observer_schema,
        ],
        status__last_applied_manifest=[deployment_manifest, service_manifest],
    )

    generate_default_observer_schema(app)

    # Create k8s objects from the k8s response
    copy_deployment_response = deepcopy(deployment_response)
    copy_service_response = deepcopy(service_response)

    deployment_object = await serialize_k8s_object(
        copy_deployment_response, "V1Deployment"
    )
    service_object = await serialize_k8s_object(copy_service_response, "V1Service")

    # State 0: Standard response from the k8s cluster
    original_replicas_count = copy_deployment_response["spec"]["replicas"]

    # `spec.replicas` is not initialized in `nginx-manifest` but is present in the
    # `observer_schema`. It is initialized in the first call to the function.
    update_last_applied_manifest_from_resp(app, deployment_object)
    assert (
        app.status.last_applied_manifest[0]["spec"]["replicas"]
        == original_replicas_count
    )

    # State (1): Change the Deployment's image in the k8s response
    first_container_resp = get_first_container(copy_deployment_response)
    first_container_resp["image"] = "nginx:1.6"
    deployment_object = await serialize_k8s_object(
        copy_deployment_response, "V1Deployment"
    )

    first_container_manifest = get_first_container(nginx_manifest[0])

    # As this field is initialized in `nginx-manifest`, its value is not updated.
    update_last_applied_manifest_from_resp(app, deployment_object)
    first_container_app = get_first_container(app.status.last_applied_manifest[0])
    assert first_container_app["image"] == first_container_manifest["image"]

    # State (2): Change the Deployment's replicas count to 2
    deployment_object.spec.replicas = 2

    # The field is observed and has already been initialized. No new update to
    # `last_applied_manifest` should occur from a Kubernetes response.
    update_last_applied_manifest_from_resp(app, deployment_object)
    assert (
        app.status.last_applied_manifest[0]["spec"]["replicas"]
        == original_replicas_count
    )

    # State (3): Change the Service's first port's protocol to "UDP"
    service_object.spec.ports[0].protocol = "UDP"

    # The field is not observed and is initialized by `nginx-manifest`. No update should
    # occur
    update_last_applied_manifest_from_resp(app, service_object)
    assert (
        app.status.last_applied_manifest[1]["spec"]["ports"][0]["protocol"]
        == nginx_manifest[1]["spec"]["ports"][0]["protocol"]
    )

    # State (4): A second port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
    )
    service_object = await serialize_k8s_object(copy_service_response, "V1Service")

    # Only the first port is observed: No update should occur
    update_last_applied_manifest_from_resp(app, service_object)
    assert len(app.status.last_applied_manifest[1]["spec"]["ports"]) == 1

    # State (5): A third port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32568, "port": 82, "protocol": "TCP", "targetPort": 82}
    )
    service_object = await serialize_k8s_object(copy_service_response, "V1Service")

    # Only the first port is observed: No update should occur
    update_last_applied_manifest_from_resp(app, service_object)
    assert len(app.status.last_applied_manifest[1]["spec"]["ports"]) == 1

    # State (6): All ports are removed from the Service.
    copy_service_response["spec"]["ports"] = []
    service_object = await serialize_k8s_object(copy_service_response, "V1Service")

    # The first port is observed and initialized by `nginx_manifest`. No update should
    # occur
    update_last_applied_manifest_from_resp(app, service_object)
    assert len(app.status.last_applied_manifest[1]["spec"]["ports"]) == 1


async def test_update_last_observed_manifest_from_resp(loop):
    """Test the ``update_last_observed_manifest_from_resp`` function.

    This function is called to update ``status.last_observed_manifest`` from a
    Kubernetes response. Observed fields only are present and updated.

    State (0):
        A Deployment and a Service are present, the Deployment has an nginx image with
        version "1.7.9". The service defines 1 port using the "TCP" protocol. A custom
        observer schema is used:
        - It observes the Deployment's image, initialized by the given manifest file.
        - It observes the Deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
    State (1):
        The Deployment image version changed to "1.6".
    State (2):
        The Deployment replicas count is changed to 2.
    State (3):
        The Service's first port's protocol is changed to "UDP"
    State (4):
        A second port is added to the Service.
    State (5):
        A third port is added to the Service.
    State (6):
        All ports are removed from the Service.

    """
    cluster = ClusterFactory()

    # Create an application using a custom observer schema
    # The `last_observed_manifest` is left empty, as is the normal workflow, and is
    # initialized by the first call to `update_last_observed_manifest_from_resp`
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        spec__observer_schema=custom_observer_schema,
    )

    generate_default_observer_schema(app)

    # Create k8s object from the k8s response
    copy_deployment_response = deepcopy(deployment_response)
    copy_service_response = deepcopy(service_response)

    deployment_object = await serialize_k8s_object(
        copy_deployment_response, "V1Deployment"
    )
    service_object = await serialize_k8s_object(copy_service_response, "V1Service")

    # State 0: Standard response from the k8s cluster, while last_observed_manifest is
    # empty

    # Update the Deployment observed manifest from the standard response.
    update_last_observed_manifest_from_resp(app, deployment_object)
    assert app.status.last_observed_manifest[0] == initial_last_observed_manifest[0]

    # Update the Service observed manifest from the standard response.
    update_last_observed_manifest_from_resp(app, service_object)
    assert app.status.last_observed_manifest[1] == initial_last_observed_manifest[1]

    # State (1): Change the Deployment's image in the k8s response
    first_container_resp = get_first_container(copy_deployment_response)
    first_container_resp["image"] = "nginx:1.6"
    deployment_object = await serialize_k8s_object(
        copy_deployment_response, "V1Deployment"
    )
    # This field is observed, therefore it should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, deployment_object)
    first_container_app = get_first_container(app.status.last_observed_manifest[0])
    assert first_container_app["image"] == first_container_resp["image"]

    # State (2): Change the Deployment's replicas count to 2
    deployment_object.spec.replicas = 2

    # This field is observed, therefore it should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, deployment_object)
    assert (
        app.status.last_observed_manifest[0]["spec"]["replicas"]
        == deployment_object.spec.replicas
    )

    # State (3): Change the Service's first port's protocol to "UDP"
    service_object.spec.ports[0].protocol = "UDP"

    # The field is not observed, therefore it shouldn't be present in
    # `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, service_object)
    assert "protocol" not in app.status.last_observed_manifest[1]["spec"]["ports"][0]

    # State (4): A second port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
    )
    service_object = await serialize_k8s_object(copy_service_response, "V1Service")

    # The length of the list should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, service_object)
    assert (
        app.status.last_observed_manifest[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]
        == 2
    )

    # State (5): A third port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32568, "port": 82, "protocol": "TCP", "targetPort": 82}
    )
    service_object = await serialize_k8s_object(copy_service_response, "V1Service")

    # The length of the list should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, service_object)
    assert (
        app.status.last_observed_manifest[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]
        == 3
    )

    # State (6): All ports are removed from the Service.
    service_object.spec.ports = []

    # The length of the list should be updated in `last_observed_manifest`
    # Also, the first port should not be present in `last_observed_manifest` anymore.
    # The list of ports only contains the special control dictionary
    update_last_observed_manifest_from_resp(app, service_object)
    assert (
        app.status.last_observed_manifest[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]
        == 0
    )
    assert len(app.status.last_observed_manifest[1]["spec"]["ports"]) == 1


async def test_reception_for_cluster_observers(aiohttp_server, config, loop):
    """Test the condition to start an Observer

    When a received cluster is in CONNECTING state, an Observer should be started.

    """

    # set the number of clusters to be created
    cluster_count = 3
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop):
        controller = KubernetesClusterController(
            server_endpoint(server), worker_count=0
        )
        for i in range(cluster_count):
            cluster = ClusterFactory()
            # Just before an observer is created, the iterator should be equal to the
            # current iteration number.
            assert len(controller.observers) == i
            # The method resource_received handles the cluster and calls corountines.
            # If the cluster is in CONNECTING state an observer will be created.
            assert cluster.status.state == ClusterState.CONNECTING
            await controller.resource_received(cluster)  # needs to be called explicitly
            # The length of the observer list in the controller should now match i+1.
            assert len(controller.observers) == i + 1
            # Also the uid of the cluster should be located in the observer list.
            assert cluster.metadata.uid in controller.observers

    # Each running Cluster has a corresponding observer. The length should sum up to
    # cluster_count.
    assert len(controller.observers) == cluster_count


async def test_create_kubernetes_cluster_observer(aiohttp_server, config, loop, db):
    """Test the creation of a KubernetesClusterObserver.

    When an observer is created, it should be updated with the cluster's status.

    """
    cluster = ClusterFactory()
    await db.put(cluster)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server), worker_count=0, time_step=-1
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # the initial state of the observer should be CONNECTING
        assert observer.resource.status.state == ClusterState.CONNECTING
        # After the observe_resource method is called, the observer
        # should set the cluster's polled status.
        await observer.observe_resource()
        # since there is no real connection to the cluster, the state should be OFFLINE
        assert observer.resource.status.state == ClusterState.OFFLINE

        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # the clusters status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


@pytest.mark.parametrize(
    "ready,pressure",
    [
        (True, False),
        (False, False),
        ("Unknown", False),
    ],
)
@pytest.mark.asyncio
async def test_create_kubernetes_cluster_observer_ready(
    aiohttp_server, config, ready, pressure, db, loop
):
    """Test the cluster status change based on the `Ready` condition.

    A Kubernetes cluster node condition could be in one of the following states:
    - `True` if the node is healthy and ready to accept pods
    - `False` if the node is not healthy and is not accepting pods
    - `Unknown` if the node controller has not heard from
        the node in the last node-monitor-grace-period (default is 40 seconds)

    Test keeps all pressures to `False`. It means the cluster node is in potential
    not-ready state for other reasons (not because of pressure).

    """

    routes = web.RouteTableDef()

    @routes.get("/api/v1/nodes")
    async def _(request):
        response = {
            "items": [
                {
                    "status": {
                        "conditions": [
                            {
                                "status": pressure,
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": ready,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
            ]
        }

        return web.Response(
            body=json.dumps(response), status=200, content_type="application/json"
        )

    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be CONNECTING
        assert observer.resource.status.state == ClusterState.CONNECTING
        # After the observe_resource method is called, the observer
        # should set the cluster's polled status.
        await observer.observe_resource()

        if ready is True:
            # The state should be ONLINE as the cluster node is `Ready`
            # and not under *Pressure
            assert observer.resource.status.state == ClusterState.ONLINE
        else:
            # The state should be NOTREADY as the cluster node is not `Ready`
            # and not under *Pressure
            assert observer.resource.status.state == ClusterState.NOTREADY

        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


@pytest.mark.parametrize(
    "ready,pressure",
    [
        (True, False),
    ],
)
async def test_create_kubernetes_cluster_observer_ready_with_internally_offline_status(
    aiohttp_server, config, ready, pressure, db, loop
):
    """Test the cluster status change based on the `Ready` condition if the ClusterState
    is OFFLINE internally.

    A Kubernetes cluster node condition could be in one of the following states:
    - `True` if the node is healthy and ready to accept pods
    - `False` if the node is not healthy and is not accepting pods
    - `Unknown` if the node controller has not heard from
        the node in the last node-monitor-grace-period (default is 40 seconds)

    Test keeps all pressures to `False`.

    """

    routes = web.RouteTableDef()

    @routes.get("/api/v1/nodes")
    async def _(request):
        response = {
            "items": [
                {
                    "status": {
                        "conditions": [
                            {
                                "status": pressure,
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": ready,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
            ]
        }

        return web.Response(
            body=json.dumps(response), status=200, content_type="application/json"
        )

    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server),
        status__state=ClusterState.OFFLINE,  # Set the initial state to OFFLINE
    )
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be OFFLINE
        assert observer.resource.status.state == ClusterState.OFFLINE

        await observer.observe_resource()

        # The state should be CONNECTING, as the cluster state is transiting
        # from OFFLINE to ONLINE
        assert observer.resource.status.state == ClusterState.CONNECTING

        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state

        # On the next observe_resource should change to cluster state to ONLINE
        await observer.observe_resource()

        assert observer.resource.status.state == ClusterState.ONLINE

        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


@pytest.mark.parametrize(
    "ready,pressure",
    [
        (True, False),
    ],
)
async def test_create_kubernetes_cluster_observer_failing_metrics(
    aiohttp_server, config, ready, pressure, db, loop
):
    """Test the cluster status based on the state internal state 'FAILING_METRICS'.

    A Kubernetes cluster node condition could be in one of the following states:
    - `True` if the node is healthy and ready to accept pods
    - `False` if the node is not healthy and is not accepting pods
    - `Unknown` if the node controller has not heard from
        the node in the last node-monitor-grace-period (default is 40 seconds)

    Test keeps all pressures to `False`.

    """

    routes = web.RouteTableDef()

    @routes.get("/api/v1/nodes")
    async def _(request):
        response = {
            "items": [
                {
                    "status": {
                        "conditions": [
                            {
                                "status": pressure,
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": ready,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
            ]
        }

        return web.Response(
            body=json.dumps(response), status=200, content_type="application/json"
        )

    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(
        spec__kubeconfig=make_kubeconfig(kubernetes_server),
        # Set the initial state to FAILING_METRICS
        status__state=ClusterState.FAILING_METRICS,
    )
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be FAILING_METRICS
        assert observer.resource.status.state == ClusterState.FAILING_METRICS
        # After the observe_resource method is called, the observer
        # should set the cluster's polled status.
        await observer.observe_resource()
        # The observer cluster status should be the same as the
        # ClusterState after the poll
        assert observer.resource.status.state == ClusterState.FAILING_METRICS
        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


@pytest.mark.parametrize(
    "ready,pressure",
    [
        (False, "MemoryPressure"),
        (False, "DiskPressure"),
        (False, "PIDPressure"),
        (True, "MemoryPressure"),
        (True, "DiskPressure"),
        (True, "PIDPressure"),
    ],
)
async def test_create_kubernetes_cluster_observer_pressure(
    aiohttp_server, config, ready, pressure, db, loop
):
    """Test the cluster status change based on the various pressure conditions.

    A Kubernetes cluster node may be under [Memory|Disk|PID]Pressure.
    In that case, the Ready condition of the cluster node should be `False`
    and our algorithm should prioritize [Memory|Disk|PID]Pressure
    condition before the `Ready` condition and set the UNHEALTHY cluster state.

    This unit test also checks the unexpected state when the `Ready` condition
    is `True` and the k8s cluster node is under some pressure.
    Also in that case, the UNHEALTHY cluster state should be set.

    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/nodes")
    async def _(request):
        response = {
            "items": [
                {
                    "status": {
                        "conditions": [
                            {
                                "status": pressure == "MemoryPressure",
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure == "DiskPressure",
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure == "PIDPressure",
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": ready,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
            ]
        }

        return web.Response(
            body=json.dumps(response), status=200, content_type="application/json"
        )

    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be CONNECTING
        assert observer.resource.status.state == ClusterState.CONNECTING
        # After the observe_resource method is called, the observer
        # should set the cluster's polled status.
        await observer.observe_resource()
        # The state should be UNHEALTHY as the cluster node is
        # under [Memory|Disk|PID]Pressure
        assert observer.resource.status.state == ClusterState.UNHEALTHY
        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


@pytest.mark.parametrize(
    "ready,pressure",
    [
        (True, False),
        (False, False),
        ("Unknown", False),
    ],
)
async def test_create_kubernetes_cluster_observer_ready_two_nodes(
    aiohttp_server, config, ready, pressure, db, loop
):
    """Test the cluster status change based on the `Ready` condition.

    A Kubernetes cluster node condition could be in one of the following states:
    - `True` if the node is healthy and ready to accept pods
    - `False` if the node is not healthy and is not accepting pods
    - `Unknown` if the node controller has not heard from
        the node in the last node-monitor-grace-period (default is 40 seconds)

    Test keeps all pressures to `False`. It means the cluster node is in potential
    not-ready state for other reasons (not because of pressure).

    Test simulates two node k8s cluster. The first one is healthy the second one not.

    """

    routes = web.RouteTableDef()

    @routes.get("/api/v1/nodes")
    async def _(request):
        response = {
            "items": [
                {
                    "status": {
                        "conditions": [
                            {
                                "status": False,
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": False,
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": False,
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": True,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
                {
                    "status": {
                        "conditions": [
                            {
                                "status": pressure,
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure,
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": ready,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
            ]
        }

        return web.Response(
            body=json.dumps(response), status=200, content_type="application/json"
        )

    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be CONNECTING
        assert observer.resource.status.state == ClusterState.CONNECTING
        # After the observe_resource method is called, the observer
        # should set the cluster's polled status.
        await observer.observe_resource()

        if ready is True:
            # The state should be ONLINE as the cluster node is `Ready`
            # and not under *Pressure
            assert observer.resource.status.state == ClusterState.ONLINE
        else:
            # The state should be NOTREADY as the cluster node is not `Ready`
            # and not under *Pressure
            assert observer.resource.status.state == ClusterState.NOTREADY
        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


@pytest.mark.parametrize(
    "ready,pressure",
    [
        (False, "MemoryPressure"),
        (False, "DiskPressure"),
        (False, "PIDPressure"),
        (True, "MemoryPressure"),
        (True, "DiskPressure"),
        (True, "PIDPressure"),
    ],
)
async def test_create_kubernetes_cluster_observer_pressure_two_nodes(
    aiohttp_server, config, ready, pressure, db, loop
):
    """Test the cluster status change based on the various pressure conditions.

    A Kubernetes cluster node may be under [Memory|Disk|PID]Pressure.
    In that case, the Ready condition of the cluster node should be `False`
    and our algorithm should prioritize [Memory|Disk|PID]Pressure
    condition before the `Ready` condition and set the UNHEALTHY cluster state.

    This unit test also checks the unexpected state when the `Ready` condition
    is `True` and the k8s cluster node is under some pressure.
    Also in that case, the UNHEALTHY cluster state should be set.

    Test simulates two node k8s cluster. The first one is healthy the second one not.

    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/nodes")
    async def _(request):
        response = {
            "items": [
                {
                    "status": {
                        "conditions": [
                            {
                                "status": False,
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": False,
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": False,
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": True,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
                {
                    "status": {
                        "conditions": [
                            {
                                "status": pressure == "MemoryPressure",
                                "type": "MemoryPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure == "DiskPressure",
                                "type": "DiskPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": pressure == "PIDPressure",
                                "type": "PIDPressure",
                                "message": "",
                                "reason": "",
                            },
                            {
                                "status": ready,
                                "type": "Ready",
                                "message": "",
                                "reason": "",
                            },
                        ]
                    }
                },
            ]
        }

        return web.Response(
            body=json.dumps(response), status=200, content_type="application/json"
        )

    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be CONNECTING
        assert observer.resource.status.state == ClusterState.CONNECTING
        # After the observe_resource method is called, the observer
        # should set the cluster's polled status.
        await observer.observe_resource()
        # The state should be UNHEALTHY as the cluster node is
        # under [Memory|Disk|PID]Pressure
        assert observer.resource.status.state == ClusterState.UNHEALTHY
        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


async def test_create_kubernetes_cluster_observer_offline(
    aiohttp_server,
    config,
    db,
    loop,
):
    """Test the cluster status change when the cluster API is offline.

    A Kubernetes cluster API could be unreachable for any reason.
    If the cluster API is offline the kubernetes client raises the
    :class:`aiohttp.ClientConnectorError`.
    In that case, the OFFLINE cluster state should be set.

    """
    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be CONNECTING
        assert observer.resource.status.state == ClusterState.CONNECTING

        connection_key = ConnectionKey(
            host="127.0.0.1",
            port=8000,
            is_ssl=False,
            ssl=None,
            proxy=None,
            proxy_auth=None,
            proxy_headers_hash=None,
        )
        with mock.patch.object(
            k8s_client_hooks.CoreV1Api,
            "list_node",
            side_effect=ClientConnectorError(connection_key, OSError()),
        ):
            await observer.observe_resource()
        # The state should be OFFLINE as the cluster API is unreachable
        assert observer.resource.status.state == ClusterState.OFFLINE
        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


@pytest.mark.parametrize(
    "reason",
    [
        404,  # Not Found
        408,  # Request Timeout
        503,  # Service Unavailable
        504,  # Gateway Timeout
    ],
)
async def test_create_kubernetes_cluster_observer_offline_non2xx_response(
    aiohttp_server, config, reason, db, loop
):
    """Test the cluster status change when the cluster API responds with non 2xx HTTP code.

    A Kubernetes cluster API could respond with non 2xx HTTP code
    for any reason. If the cluster API responds with non 2xx
    the kubernetes client raises the :class:`ApiException`.
    In that case, the OFFLINE cluster state should be set.

    Note regarding 503 Service Unavailable:
        The current cluster status is fetched by :func:`poll_resource`
        from its API. If the cluster API is shutting down the API
        server responds with a 503 (service unavailable, apiserver
        is shutting down) HTTP response.

    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/nodes")
    async def _(request):
        return web.Response(status=reason)

    # Create K8s cluster API
    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    # Create cluster to register
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    await db.put(cluster)

    # Create Krake API
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server),
            worker_count=0,
        )
        await controller.prepare(client)
        await register_observer(controller, cluster)
        observer, _ = controller.observers[cluster.metadata.uid]

        # The initial state of the observer should be CONNECTING
        assert observer.resource.status.state == ClusterState.CONNECTING
        # After the observe_resource method is called, the observer
        # should set the cluster's polled status.
        await observer.observe_resource()

        # The state should be OFFLINE as the cluster API responds
        # with non 2xx HTTP code.
        assert observer.resource.status.state == ClusterState.OFFLINE
        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        # The cluster's status should be updated by the kubernetes controller
        assert observer.resource.status.state == stored.status.state


async def test_kubernetes_cluster_observer_on_cluster_update(
    aiohttp_server, db, loop, config
):
    """Test the behavior of the Kubernetes Controller and Observer when a cluster
    is being updated.

    """
    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server), worker_count=0
        )
        cluster = ClusterFactory()
        await db.put(cluster)
        await controller.prepare(client)
        await controller.resource_received(cluster)
        # change the clusters status
        cluster.status.state = ClusterState.NOTREADY
        # now the cluster in the observer and the actual cluster are not equal
        assert controller.observers[cluster.metadata.uid][0].resource != cluster
        # by calling the resource_received method, the observer is unregistered and
        # registered again, therefore the cluster in the observer should be updated
        await controller.resource_received(cluster)
        assert controller.observers[cluster.metadata.uid][0].resource == cluster

        controller.observers[cluster.metadata.uid][
            0
        ].resource.status.state = ClusterState.ONLINE
        assert controller.observers[cluster.metadata.uid][0].resource != cluster
        cluster = await controller.on_status_update(
            controller.observers[cluster.metadata.uid][0].resource
        )
        assert controller.observers[cluster.metadata.uid][0].resource == cluster


async def test_kubernetes_cluster_observer_on_cluster_delete(aiohttp_server, config):
    """Test the behavior of the Kubernetes Controller and Observer when a cluster
    is being deleted.

    """
    server = await aiohttp_server(create_app(config))
    controller = KubernetesClusterController(server_endpoint(server), worker_count=0)
    cluster = ClusterFactory()

    await controller.resource_received(cluster)
    # when a datetime is set in cluster.medata.deleted the cluster should be deleted
    # with calling the resource_received method
    cluster.metadata.deleted = datetime.datetime.now()
    await controller.resource_received(cluster)
    assert controller.observers == {}


async def test_register_kubernetes_cluster_observer(aiohttp_server, config):
    """Test the registration of a KubernetesClusterObserver."""
    server = await aiohttp_server(create_app(config))
    controller = KubernetesClusterController(server_endpoint(server), worker_count=0)

    cluster = ClusterFactory()

    await controller.resource_received(cluster)
    # the observer dict should not be empty
    assert controller.observers != {}


async def test_unregister_kubernetes_cluster_observer(aiohttp_server, config):
    """Test the unregistration of a KubernetesClusterObserver."""
    server = await aiohttp_server(create_app(config))
    controller = KubernetesClusterController(server_endpoint(server), worker_count=0)

    cluster = ClusterFactory()

    await controller.resource_received(cluster)
    await unregister_observer(controller, cluster)
    # the observer dict should be empty
    assert controller.observers == {}
