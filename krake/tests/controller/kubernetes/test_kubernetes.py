import asyncio
import logging
import multiprocessing
import time
from contextlib import suppress
from copy import deepcopy

import mock
import pytest
from aiohttp import web, ClientConnectorError
from asyncio.subprocess import PIPE, STDOUT
import pytz

from krake import utils
from krake.controller.kubernetes.client import InvalidManifestError
from kubernetes_asyncio.client import (
    V1Status,
    V1Service,
    V1ServiceSpec,
    V1ServicePort,
    ApiException,
)

from krake.api.app import create_app
from krake.data.core import resource_ref, ReasonCode
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes.__main__ import main
from krake.controller.kubernetes import (
    KubernetesController,
    register_service,
    unregister_service,
    KubernetesClient,
)
from krake.controller.kubernetes.kubernetes import ResourceDelta
from krake.controller.kubernetes.hooks import (
    update_last_applied_manifest_from_spec,
    update_last_applied_manifest_from_resp,
    generate_default_observer_schema,
)
from krake.client import Client
from krake.test_utils import server_endpoint, with_timeout, serialize_k8s_object

from tests.factories.fake import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)

from tests.controller.kubernetes import (
    deployment_manifest,
    service_manifest,
    secret_manifest,
    nginx_manifest,
    custom_deployment_observer_schema,
    custom_service_observer_schema,
    custom_observer_schema,
    deployment_response,
    service_response,
    secret_response,
    initial_last_observed_manifest_deployment,
    initial_last_observed_manifest_service,
    initial_last_observed_manifest,
)


@pytest.mark.parametrize(
    "base", ["1.2.3.4", "1.2.3.4:8888", "1.2.3.4/path/to", "1.2.3.4:8888/path/to"]
)
async def test_api_endpoint(hooks_config, client_ssl_context, caplog, base):
    """Test the verification of the provided external endpoint in the Kubernetes
    controller.
    """
    # No endpoint provided
    hooks_config.complete.external_endpoint = None
    controller = KubernetesController("http://krake.api", hooks=hooks_config)
    assert controller.hooks.complete.external_endpoint is None

    # Simple behavior
    hooks_config.complete.external_endpoint = f"http://{base}"
    controller = KubernetesController("http://krake.api", hooks=hooks_config)
    assert controller.hooks.complete.external_endpoint == f"http://{base}"

    # Setting the scheme as https when TLS is disabled will result in a warning
    hooks_config.complete.external_endpoint = f"https://{base}"
    controller = KubernetesController("http://krake.api", hooks=hooks_config)
    assert controller.hooks.complete.external_endpoint == f"http://{base}"
    record = next(iter(caplog.records))
    assert record.levelname == "WARNING"
    assert len(list(caplog.records)) == 1
    caplog.clear()

    # TLS enabled

    ssl_context = client_ssl_context("client")

    # Simple behavior
    hooks_config.complete.external_endpoint = f"https://{base}"
    controller = KubernetesController(
        "https://krake.api", hooks=hooks_config, ssl_context=ssl_context
    )
    assert controller.hooks.complete.external_endpoint == f"https://{base}"

    # Setting the scheme as https when TLS is enabled will result in a warning
    hooks_config.complete.external_endpoint = f"http://{base}"
    controller = KubernetesController(
        "https://krake.api", hooks=hooks_config, ssl_context=ssl_context
    )
    assert controller.hooks.complete.external_endpoint == f"https://{base}"
    record = next(iter(caplog.records))
    assert record.levelname == "WARNING"
    assert len(list(caplog.records)) == 1


@with_timeout(3)
async def test_main_help(loop):
    """Verify that the help for the Kubernetes Controller is displayed, and contains the
    elements added by the argparse formatters (default value and expected types of the
    parameters).
    """
    command = "python -m krake.controller.kubernetes -h"
    # The loop parameter is mandatory otherwise the test fails if started with others.
    process = await asyncio.create_subprocess_exec(
        *command.split(" "), stdout=PIPE, stderr=STDOUT, loop=loop
    )
    stdout, _ = await process.communicate()
    output = stdout.decode()

    to_check = [
        "Kubernetes application controller",
        "usage:",
        "optional arguments:",
        "default:",  # Present if the default value of the arguments are displayed
        "str",  # Present if the type of the arguments are displayed
        "int",
    ]

    for expression in to_check:
        assert expression in output


@pytest.mark.slow
def test_main(kube_config, log_to_file_config):
    """Test the main function of the Kubernetes Controller, and verify that it starts,
    display the right output and stops without issue.
    """
    log_config, file_path = log_to_file_config()

    kube_config.api_endpoint = "http://my-krake-api:1234"
    kube_config.log = log_config

    def wrapper(configuration):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        main(configuration)

    # Start the process and let it time to initialize
    process = multiprocessing.Process(target=wrapper, args=(kube_config,))
    process.start()
    time.sleep(2)

    # Stop and wait for the process to finish
    process.terminate()
    process.join()

    assert not process.is_alive()
    assert process.exitcode == 0

    # Verify the output of the process
    with open(file_path, "r") as f:
        output = f.read()

    assert "Controller started" in output
    assert "Received signal, exiting..." in output
    assert "Controller stopped" in output

    # Verify that all "ERROR" lines in the output are only errors that logs the lack of
    # connectivity to the API.
    attempted_connectivity = False
    for line in output.split("\n"):
        if "ERROR" in output:
            message = (
                f"In line {line!r}, an error occurred which was different from the"
                f" error from connecting to the API."
            )
            assert "Cannot connect to host my-krake-api:1234" in output, message
            attempted_connectivity = True

    assert attempted_connectivity


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

    assert pending.status.kube_controller_triggered is None
    assert waiting.status.kube_controller_triggered < waiting.metadata.modified
    assert scheduled.status.kube_controller_triggered >= scheduled.metadata.modified
    assert failed.status.kube_controller_triggered >= failed.metadata.modified

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
    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        # No `nginx-demo` Deployment exist
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller creates the `nginx-demo`
    # Deployment
    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
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


async def test_app_creation_default_namespace(aiohttp_server, config, db, loop):
    """This test ensures that NOT specifying a namespace for a resource or the
    kubeconfig file creates it in the "default" namespace.
    """
    accepted = "default"
    called_get = False
    called_post = False

    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a Deployment named `nginx-demo` already exists.
    @routes.get("/apis/apps/v1/namespaces/{namespace}/deployments/nginx-demo")
    async def _(request):
        nonlocal called_get
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_get = True

        # No `nginx-demo` Deployment exist
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller creates the `nginx-demo`
    # Deployment
    @routes.post("/apis/apps/v1/namespaces/{namespace}/deployments")
    async def _(request):
        nonlocal called_post
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_post = True

        # As a response, the k8s API provides the full Deployment object
        copy_deployment_response = deepcopy(deployment_response)
        copy_deployment_response["metadata"]["namespace"] = received
        return web.json_response(copy_deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    copy_deployment_manifest = deepcopy(deployment_manifest)
    del copy_deployment_manifest["metadata"]["namespace"]

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=[copy_deployment_manifest],
        spec__observer_schema=[custom_deployment_observer_schema],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)
        await controller.resource_received(app, start_observer=False)

    assert called_get and called_post

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    copy_initial_last_observed_manifest_deployment = deepcopy(
        initial_last_observed_manifest_deployment
    )
    copy_initial_last_observed_manifest_deployment["metadata"]["namespace"] = "default"
    assert stored.status.last_observed_manifest == [
        copy_initial_last_observed_manifest_deployment
    ]
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_creation_cluster_default_namespace(aiohttp_server, config, db, loop):
    """If a default namespace is set in the kubeconfig, and no namespace is set in the
    manifest file, the default cluster of the kubeconfig file should be used.
    """
    accepted = "another_namespace"
    called_get = False
    called_post = False

    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a Deployment named `nginx-demo` already exists.
    @routes.get("/apis/apps/v1/namespaces/{namespace}/deployments/nginx-demo")
    async def _(request):
        nonlocal called_get
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_get = True
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller creates the `nginx-demo`
    # Deployment
    @routes.post("/apis/apps/v1/namespaces/{namespace}/deployments")
    async def _(request):
        nonlocal called_post
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_post = True

        # As a response, the k8s API provides the full Deployment object
        copy_deployment_response = deepcopy(deployment_response)
        copy_deployment_response["metadata"]["namespace"] = received
        return web.json_response(copy_deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    # Replace the default namespace in the kubeconfig file
    kubeconfig = make_kubeconfig(kubernetes_server)
    kubeconfig["contexts"][0]["context"]["namespace"] = "another_namespace"
    cluster = ClusterFactory(spec__kubeconfig=kubeconfig)

    copy_deployment_manifest = deepcopy(deployment_manifest)
    del copy_deployment_manifest["metadata"]["namespace"]

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=[copy_deployment_manifest],
        spec__observer_schema=[custom_deployment_observer_schema],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)

    assert called_get and called_post

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    copy_initial_last_observed_manifest_deployment = deepcopy(
        initial_last_observed_manifest_deployment
    )
    copy_initial_last_observed_manifest_deployment["metadata"][
        "namespace"
    ] = "another_namespace"
    assert stored.status.last_observed_manifest == [
        copy_initial_last_observed_manifest_deployment
    ]
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_creation_manifest_namespace_set(aiohttp_server, config, db, loop):
    """If a default namespace is set in the kubeconfig, and a namespace IS set in the
    manifest file, the namespace in the manifest file should be used.
    """
    accepted = "secondary"
    called_get = False
    called_post = False

    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a Deployment named `nginx-demo` already exists.
    @routes.get("/apis/apps/v1/namespaces/{namespace}/deployments/nginx-demo")
    async def _(request):
        nonlocal called_get
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_get = True
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller creates the `nginx-demo`
    # Deployment
    @routes.post("/apis/apps/v1/namespaces/{namespace}/deployments")
    async def _(request):
        nonlocal called_post
        received = request.match_info["namespace"]
        assert (
            received == accepted
        ), f"The namespace {received} must not be used by the client."
        called_post = True

        # As a response, the k8s API provides the full Deployment object
        copy_deployment_response = deepcopy(deployment_response)
        copy_deployment_response["metadata"]["namespace"] = received
        return web.json_response(copy_deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    # Replace the default namespace in the kubeconfig file
    kubeconfig = make_kubeconfig(kubernetes_server)
    kubeconfig["contexts"][0]["context"]["namespace"] = "another_namespace"
    cluster = ClusterFactory(spec__kubeconfig=kubeconfig)

    copy_deployment_manifest = deepcopy(deployment_manifest)

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=[copy_deployment_manifest],
        spec__observer_schema=[custom_deployment_observer_schema],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)
        await controller.resource_received(app, start_observer=False)

    assert called_get and called_post

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    copy_initial_last_observed_manifest_deployment = deepcopy(
        initial_last_observed_manifest_deployment
    )
    copy_initial_last_observed_manifest_deployment["metadata"][
        "namespace"
    ] = "secondary"
    assert stored.status.last_observed_manifest == [
        copy_initial_last_observed_manifest_deployment
    ]
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_app_observer_schema_generation(aiohttp_server, config, db, loop):
    """Test the automatic generation of the observer_schema

    We create an application with a Deployment and a Secret. We specify a custom
    observer_schema for the Deployment. As part of the reconciliation loop, the
    controller should automatically generate the default observer schema for the
    Secret

    """
    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a Deployment and a Service named `nginx-demo` already
    # exist.
    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        # No `nginx-demo` Deployment exist
        return web.Response(status=404)

    @routes.get("/api/v1/namespaces/secondary/secrets/nginx-demo")
    async def _(request):
        # No `nginx-demo` Service exist
        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller creates the `nginx-demo`
    # Deployment and Service
    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        # As a response, the k8s API provides the full Deployment object
        return web.json_response(deployment_response)

    @routes.post("/api/v1/namespaces/secondary/secrets")
    async def _(request):
        # As a response, the k8s API provides the full Secret object
        return web.json_response(secret_response)

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
        spec__manifest=[deployment_manifest, secret_manifest],
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

    assert stored.status.mangled_observer_schema[0]["kind"] == "Deployment"
    assert stored.status.mangled_observer_schema[1]["kind"] == "Secret"

    assert stored.status.last_observed_manifest[0]["kind"] == "Deployment"
    assert stored.status.last_observed_manifest[1]["kind"] == "Secret"


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
    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/{name}")
    async def _(request):
        # The three Deployments already exist
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
    @routes.patch("/apis/apps/v1/namespaces/secondary/deployments/{name}")
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

    # As part the reconciliation loop, the k8s controller deletes the Deployment which
    # are not present in the manifest file anymore.
    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/{name}")
    async def _(request):
        deleted.add(request.match_info["name"])
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # Craft a last_observed_manifest, reflecting the resources previously created via
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

    assert deleted == {"nginx-demo-1"}
    assert patched == {"nginx-demo-2"}

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
    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/{name}")
    async def _(request):
        # The k8s API only replies with the full Deployment resource if it is existing.
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
    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        body = await request.json()
        request.app["created"].add(body["metadata"]["name"])
        response = deepcopy(deployment_response)
        response["metadata"]["name"] = body["metadata"]["name"]
        return web.json_response(response)

    # As part of the migration, the k8s controller deletes a Deployment on the old
    # cluster
    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/{name}")
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

    # Craft a last_observed_manifest, reflecting the resources previously created via
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
    # The controller should trigger a migration (i.e. delete existing resources defined
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

    assert kubernetes_server_A.app["deleted"] == {"nginx-demo-1"}
    assert kubernetes_server_B.app["created"] == {"nginx-demo-2"}

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.last_observed_manifest == [nginx_target_last_observed_manifest]
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

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        body = await request.json()
        request.app["created"].add(body["metadata"]["name"])
        return web.json_response(deployment_response)

    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/{name}")
    async def _(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/{name}")
    async def _(request):
        if request.match_info["name"] in request.app["existing"]:
            return web.json_response(deployment_response)
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
        spec__observer_schema=[custom_deployment_observer_schema],
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
    """Test the deletion of an application

    The Kubernetes Controller should delete the application and updates the DB.

    """
    kubernetes_app = web.Application()
    routes = web.RouteTableDef()
    deleted = set()

    # As part of the deletion, the k8s controller deletes the Deployment, Service, and
    # Secret from the k8s cluster
    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        deleted.add("Deployment")
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        deleted.add("Service")
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/secondary/secrets/nginx-demo")
    async def _(request):
        deleted.add("Secret")
        return web.Response(status=200)

    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # The application possesses the deleted timestamp, meaning it should be deleted.
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

    assert len(deleted) == 3
    assert "Deployment" in deleted
    assert "Service" in deleted
    assert "Secret" in deleted


async def test_app_management_no_error_logs(aiohttp_server, config, db, loop, caplog):
    """Ensure that the Kubernetes Controller does not log any error during the lifecycle
    of an Application. Three phases of the lifecycle are simulated:

        1. Deployment on a cluster;
        2. Observation of the resource's state on the cluster;
        3. Deletion of the resources.

    After all these steps, the logs are read to verify that the controller finished its
    job successfully and no error was logged (there could be cases where components log
    errors, without disrupting the controller's workflow).
    """
    # The asyncio logger needs to be enabled as it is disabled by default.
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.disabled = False

    copy_deployment_manifest = deepcopy(nginx_manifest[0])
    actual_state = 0

    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 2:
            return web.json_response(copy_deployment_manifest)
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.json_response(deployment_response)

    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
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
        spec__manifest=[copy_deployment_manifest],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        # The time step prevents the observer from running in parallel, it should only
        # observe when requested in the test.
        controller = KubernetesController(
            server_endpoint(api_server), worker_count=0, time_step=1000
        )
        await controller.prepare(client)

        # 1. Deploy the resource
        actual_state = 1
        await controller.resource_received(app)

        # 2. Observe the resource
        actual_state = 2
        observer, task = controller.observers[app.metadata.uid]
        await observer.observe_resource()

        # 3. Delete the resource
        actual_state = 3

        stored = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        stored.metadata.deleted = utils.now()
        stored.metadata.finalizers = ["kubernetes_resources_deletion"]

        await controller.resource_received(stored)

    for record in caplog.records:
        assert record.levelname != "ERROR"


async def test_session_closed(aiohttp_server, config, db, loop):
    """Ensure that the Kubernetes client session is closed after the reconciliation
    workflow was executed.
    """
    import krake.controller.kubernetes.client

    original__aexit__ = krake.controller.kubernetes.client.KubernetesClient.__aexit__

    called = False

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        nonlocal called
        called = True

        await original__aexit__(self, exc_type, exc_val, exc_tb)
        assert self.api_client.rest_client.pool_manager.closed

    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
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
        spec__manifest=nginx_manifest[:1],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        with mock.patch.object(
            krake.controller.kubernetes.client.KubernetesClient, "__aexit__", __aexit__
        ):
            await controller.resource_received(app, start_observer=False)

    assert called


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
    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        # Service doesn't exist yet
        return web.Response(status=404)

    # The k8s controller creates the Service
    @routes.post("/api/v1/namespaces/secondary/services")
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
    app = ApplicationFactory(status__services={"nginx": "127.0.0.1:1234"})
    await unregister_service(app, resource)
    assert app.status.services == {}


async def test_unregister_service_without_previous_service():
    resource = {"kind": "Service", "metadata": {"name": "nginx"}}
    app = ApplicationFactory(status__services={})
    await unregister_service(app, resource)
    assert app.status.services == {}


async def test_service_unregistration(aiohttp_server, config, db, loop):
    """Test the deletion of a Service and test if the endpoint is removed from the
    application status

    """
    # Setup Kubernetes API mock server
    routes = web.RouteTableDef()

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.json_response(deployment_response)

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller deletes the Service
    @routes.delete("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # The application is RUNNING. A Service was previously created by Krake, and is
    # present in last_observed_manifest. The Service should now be deleted, as it is not
    # present in spec.manifest.
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=[deployment_manifest],
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


async def test_kubernetes_controller_unsupported_error_handling(
    aiohttp_server, config, db, loop
):
    """Test the behavior of the Controller in case of an error due to an unsupported
    resource.
    """
    failed_manifest = deepcopy(nginx_manifest)
    for resource in failed_manifest:
        resource["kind"] = "Unsupported"

    cluster = ClusterFactory(spec__custom_resources=[])
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(cluster),
        status__last_observed_manifest=[],
        spec__manifest=failed_manifest,
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
    assert stored.status.reason.code == ReasonCode.UNSUPPORTED_KIND


async def test_kubernetes_api_error_handling(aiohttp_server, config, db, loop):
    """Test the behavior of the Controller in case of a Kubernetes error."""
    # Create an actual "kubernetes cluster" with no route, so it responds wrongly
    # to the requests of the Controller.
    kubernetes_app = web.Application()
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(cluster),
        status__last_observed_manifest=[],
        spec__manifest=[deployment_manifest],
        spec__observer_schema=[custom_deployment_observer_schema],
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


async def test_client_app_kind_error_handling(aiohttp_server, config, db, loop):
    """Test the error handling in the KubernetesClient when attempting to create a
    resource if the kind of a resource is removed from a manifest file.
    """
    copy_deployment_manifest = deepcopy(nginx_manifest[:1])
    del copy_deployment_manifest[0]["kind"]

    cluster = ClusterFactory()

    kube = KubernetesClient(cluster.spec.kubeconfig, [])

    with pytest.raises(InvalidManifestError, match="kind"):
        await kube.apply(copy_deployment_manifest[0])


async def test_client_app_name_error_handling(aiohttp_server, config, db, loop):
    """Test the error handling in the KubernetesClient when attempting to create a
    resource if the name of the resource is removed from a manifest file.
    """
    copy_deployment_manifest = deepcopy(nginx_manifest[:1])
    del copy_deployment_manifest[0]["metadata"]["name"]

    cluster = ClusterFactory()

    kube = KubernetesClient(cluster.spec.kubeconfig, [])
    with pytest.raises(InvalidManifestError, match="metadata.name"):
        await kube.apply(copy_deployment_manifest[0])


async def test_client_app_namespace_handling(aiohttp_server, config, db, loop):
    """Test if the manifest files are handled by the client whether they have a
    namespace or not.
    """
    # With namespace
    copy_deployment_manifest = deepcopy(nginx_manifest[:1])
    assert copy_deployment_manifest[0]["metadata"]["namespace"]

    cluster = ClusterFactory()

    # If the manifest is accepted, the client attempts to connect to a non-existent
    # cluster using the mock kubeconfig file generated, cannot, and thus raises an error
    with suppress(ClientConnectorError):
        async with KubernetesClient(cluster.spec.kubeconfig, []) as kube:
            await kube.apply(copy_deployment_manifest[0])

    # Without namespace
    del copy_deployment_manifest[0]["metadata"]["namespace"]

    with suppress(ClientConnectorError):
        async with KubernetesClient(cluster.spec.kubeconfig, []) as kube:
            await kube.apply(copy_deployment_manifest[0])


async def test_client_app_apply_not_404_error_handling(
    aiohttp_server, config, db, loop
):
    """For the apply() method of the KubernetesClient, test the handling of response
    with an error which is not a 404.
    """
    copy_deployment_manifest = deepcopy(nginx_manifest[:1])

    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=403)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    async with KubernetesClient(cluster.spec.kubeconfig, []) as kube:
        with pytest.raises(ApiException):
            await kube.apply(copy_deployment_manifest[0])


async def test_client_app_delete_error_handling(
    aiohttp_server, config, db, loop, caplog
):
    """For the delete() method of the KubernetesClient, test the handling of response
    with a 404 error and with an error with another status.
    There are three states:

        0. initialisation
        1. when deleting a resource from the cluster, a 403 is sent. The Kubernetes
            client does not know how to handle it, and raises an exception.
        2. when deleting a resource from the cluster, a 404 is sent. The Kubernetes
            client must handle it as if the resource was already deleted.
    """
    caplog.set_level(logging.DEBUG)
    current_state = 0

    copy_deployment_manifest = deepcopy(nginx_manifest[:1])

    routes = web.RouteTableDef()

    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal current_state
        if current_state == 1:
            return web.Response(status=403)
        elif current_state == 2:
            return web.Response(status=404)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    async with KubernetesClient(cluster.spec.kubeconfig, []) as kube:
        # State (1): Return a 403
        current_state = 1

        with pytest.raises(ApiException):
            await kube.delete(copy_deployment_manifest[0])

        # State (2): Return a 404
        current_state = 2
        resp = await kube.delete(copy_deployment_manifest[0])
        assert resp is None

    already_deleted = 0
    for record in caplog.records:
        if (
            record.levelname == "DEBUG"
            and record.message == "Deployment already deleted"
        ):
            already_deleted += 1

    # The logs for the resource already deleted must only appear once, in the state (2)
    assert already_deleted == 1


def test_resource_delta(loop):
    """Test if the controller correctly calculates the delta between
    ``last_applied_manifest`` and ``last_observed_manifest``


    State (0):
        The application possesses a last_applied_manifest which specifies a Deployment,
        a Service and a Secret. The application has a custom observer_schema which
        observes only part of the resources:
        - It observes the deployment's image, initialized by the given manifest file.
        - It observes the deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
        - The Secret is not observed

        The application does not possess a last_observed_manifest.

        This state tests the addition of observed and non observed resources to
        last_applied_manifest

    State (1):
        The application possesses a last_observed_manifest which matches the
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
        Update the namespace field in the last_observed_manifest, which is observed and present in
        last_applied_manifest

    State (11):
        Add additional elements to a list in last_observed_manifest

    State (12):
        Remove elements from a list in last_observed_manifest

    State (13):
        Remove Secret

    """

    # State(0): Observed and non observed resources are added to last_applied_manifest
    app = ApplicationFactory(
        spec__manifest=deepcopy(nginx_manifest),
        spec__observer_schema=deepcopy(custom_observer_schema),
    )

    generate_default_observer_schema(app)
    initial_mangled_observer_schema = deepcopy(app.status.mangled_observer_schema)
    update_last_applied_manifest_from_spec(app)

    deployment_object = await serialize_k8s_object(deployment_response, "V1Deployment")
    service_object = await serialize_k8s_object(service_response, "V1Service")
    secret_object = await serialize_k8s_object(secret_response, "V1Secret")

    # The Deployment and Service and Secret have to be created.
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 3
    assert app.status.last_applied_manifest[0] in new  # Deployment
    assert app.status.last_applied_manifest[1] in new  # Service
    assert app.status.last_applied_manifest[2] in new  # Secret
    assert len(deleted) == 0
    assert len(modified) == 0

    # State (1): The application possesses a last_observed_manifest which matches the
    # last_applied_manifest.
    update_last_applied_manifest_from_resp(app, deployment_object)
    update_last_applied_manifest_from_resp(app, service_object)
    update_last_applied_manifest_from_resp(app, secret_object)
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
    app.status.mangled_observer_schema[0]["spec"].pop("replicas")
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
    app.status.mangled_observer_schema = deepcopy(initial_mangled_observer_schema)
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


    # State (10): Update the namespace field in the last_observed_manifest, which is observed and
    # present in last_applied_manifest

    app.status.last_observed_manifest[1]["metadata"]["namespace"] = "Secondary"

    # The modification of the namespace field should create a new resource in the changed namespace
    # and delete the old resource out of the old namespace. This leads to a new and a deleted element
    # in their respective lists
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 1
    assert len(deleted) == 1
    assert len(modified) == 0

    # State (11): Add additional elements to a list in last_observed_manifest
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

    # State (12): Remove elements from a list in last_observed_manifest
    app.status.mangled_observer_schema[1]["spec"]["ports"][-1][
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

    # State (13): Remove Secret
    app.status.last_applied_manifest = deepcopy(initial_last_applied_manifest)
    app.status.last_observed_manifest = deepcopy(initial_last_observed_manifest)
    app.status.mangled_observer_schema.pop(2)
    app.spec.manifest.pop(2)
    app.status.last_applied_manifest.pop(2)

    # Secret should be deleted
    new, deleted, modified = ResourceDelta.calculate(app)
    assert len(new) == 0
    assert len(deleted) == 1
    assert len(modified) == 0
    assert app.status.last_observed_manifest[2] in deleted  # Secret
