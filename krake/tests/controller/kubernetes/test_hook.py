import os.path
import ssl
import tempfile
from copy import deepcopy

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer as Server
from krake.data.config import TlsClientConfiguration, TlsServerConfiguration

from krake.api.app import create_app
from krake.controller import create_ssl_context
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState, ApplicationComplete
from krake.controller.kubernetes import KubernetesController
from krake.client import Client
from krake.test_utils import server_endpoint

from tests.factories.kubernetes import ApplicationFactory, ClusterFactory, make_kubeconfig
from tests.controller.kubernetes import nginx_manifest, hooks_config


async def test_complete_hook(aiohttp_server, config, db, loop):
    """Verify that the Controller mangled the received Application to add elements of
    the "complete" hook if it had been enabled.

    Conditions:
     * TLS:  disabled
     * RBAC: disabled
     * extras: only check the content of k8s resources generated by the "complete" hook.

    Expectations:
        Environment variables are added to the Deployment in the manifest file of the
        deployed Application.

    """
    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # We only consider the first resource in the manifest file, that is a Deployment.
    # This Deployment should be modified by the "complete" hook with ENV vars.
    deployment_manifest = deepcopy(nginx_manifest[0])

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=[deployment_manifest],
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

    # TLS is disabled, so no additional resource has been generated
    assert len(stored.status.manifest) == 1
    for resource in stored.status.manifest:

        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "KRAKE_TOKEN" in [env["name"] for env in container["env"]]
            assert "KRAKE_COMPLETE_URL" in [env["name"] for env in container["env"]]

    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_complete_hook_disable_by_user(aiohttp_server, config, db, loop):
    """Verify that the Controller did not mangle the received Application to add
    elements of the "complete" hook if it had not been enabled.

    Conditions:
     * TLS:  disabled
     * RBAC: disabled
     * extras: complete hook not set by the user

    Expectations:
        No resource is added in the app's manifest.

    """
    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # We only consider the first resource in the manifest file, that is a Deployment.
    # This Deployment should be modified by the "complete" hook with ENV vars.
    deployment_manifest = deepcopy(nginx_manifest[0])

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=[deployment_manifest],
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

    assert len(stored.status.manifest) == 1
    for resource in stored.status.manifest:
        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "env" not in container

    assert stored.status.manifest == app.spec.manifest
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_complete_hook_tls(aiohttp_server, config, pki, db, loop):
    """Verify that the Controller mangled the received Application to add elements of
    the "complete" hook if it had been enabled when the communication with TLS was
    enabled.

    Conditions:
     * TLS:  enabled
     * RBAC: disabled
     * extras: only check the content of k8s resources generated by the "complete" hook.

    Expectations:
        A ConfigMap is added in the manifest file, as well as its mounting point in the
        Deployment of the ConfigMap.

    """
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

    @routes.get("/api/v1/namespaces/secondary/configmaps/ca.pem")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/api/v1/namespaces/secondary/configmaps")
    async def _(request):
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # We only consider the first resource in the manifest file, that is a Deployment.
    # This Deployment should be modified by the "complete" hook with ENV vars.
    deployment_manifest = deepcopy(nginx_manifest[0])

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=[deployment_manifest],
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

    assert len(stored.status.manifest) == 2
    for resource in stored.status.manifest:
        # Ensure all resources (provided and generated) are created in the same
        # namespace.
        assert resource["metadata"]["namespace"] == "secondary"

        if resource["kind"] != "Deployment":
            assert resource["kind"] == "ConfigMap"
            continue

        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "volumeMounts" in container
            assert "KRAKE_TOKEN" in [env["name"] for env in container["env"]]
            assert "KRAKE_COMPLETE_URL" in [env["name"] for env in container["env"]]

    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


async def test_complete_hook_default_namespace(aiohttp_server, config, db, loop):
    """Verify that the Controller mangled the received Application to add elements of
    the "complete" hook if it had been enabled, even if the resources have been created
    without any namespace.

    Conditions:
     * TLS:  disabled
     * RBAC: disabled
     * extras: no Kubernetes namespace is specified in the manifest file provided to
       create the Application. Check the content of k8s resources generated by the
       "complete" hook.

    Expectations:
        The Kubernetes resources are created, and they do not have any namespace added
        to them.

    """
    deployment_created = False

    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):
        nonlocal deployment_created
        deployment_created = True
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # We only consider the first resource in the manifest file, that is a Deployment.
    # This Deployment should be modified by the "complete" hook with ENV vars.
    deployment_manifest = deepcopy(nginx_manifest[0])
    # Create a manifest with resources without any namespace.
    del deployment_manifest["metadata"]["namespace"]

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=[deployment_manifest],
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

    assert deployment_created

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert len(stored.status.manifest) == 1  # one resource in the spec manifest

    for resource in stored.status.manifest:
        for container in resource["spec"]["template"]["spec"]["containers"]:
            assert "KRAKE_TOKEN" in [env["name"] for env in container["env"]]
            assert "KRAKE_COMPLETE_URL" in [env["name"] for env in container["env"]]

    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


def get_hook_environment_value(application):
    """From an Application that has been mangled with the "complete" hook, get the value
    of the token and the URL that were added to it.

    Args:
        application (Application): the Application augmented with the elements of the
            "complete" hook.

    Returns:
        (str, str): a tuple of two elements: the token generated by the "complete" hook
            and the URL of the Krake API, as inserted by the hook.

    """
    deployment = application.status.manifest[0]

    token = None
    url = None
    for container in deployment["spec"]["template"]["spec"]["containers"]:
        for env in container["env"]:
            if env["name"] == "KRAKE_TOKEN":
                token = env["value"]
            if env["name"] == "KRAKE_COMPLETE_URL":
                url = env["value"]

    if token is None or url is None:
        raise ValueError("The token and the url must be in the environment")

    return token, url


async def test_complete_hook_sending(aiohttp_server, config, db, loop):
    """Send a hook using ONLY the information present in the environment of the
    Deployment, without TLS enabled.

    Conditions:
     * TLS:  disabled
     * RBAC: disabled
     * extras: send a request to the "complete" hook endpoint.

    Expectations:
        The information present on the DEPLOYED Kubernetes resources are enough to use
        the "complete" hook endpoint, and the request sent to this endpoint led to the
        deletion of the Application on the API.

    """
    routes = web.RouteTableDef()

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    spec_manifest = nginx_manifest[:1]

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=spec_manifest,
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

    token, url = get_hook_environment_value(stored)

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        complete = ApplicationComplete(token=token)
        resp = await client.session.put(url, json=complete.serialize())
        assert resp.status == 200

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.metadata.deleted is not None


async def test_complete_hook_sending_tls(aiohttp_server, config, pki, db, loop):
    """Send a hook using ONLY the information present in the environment of the
    Deployment, with TLS enabled.

    Conditions:
     * TLS:  enabled
     * RBAC: disabled
     * extras: send a request to the "complete" hook endpoint.

    Expectations:
        The information present on the DEPLOYED Kubernetes resources are enough to use
        the "complete" hook endpoint, and the request sent to this endpoint led to the
        deletion of the Application on the API.

    """
    routes = web.RouteTableDef()

    server_cert = pki.gencert("api-server")
    config.tls = TlsServerConfiguration(
        enabled=True, client_ca=pki.ca.cert, cert=server_cert.cert, key=server_cert.key
    )

    client_cert = pki.gencert("client")
    client_tls = TlsClientConfiguration(
        enabled=True,
        client_ca=pki.ca.cert,
        client_cert=client_cert.cert,
        client_key=client_cert.key,
    )
    ssl_context = create_ssl_context(client_tls)

    @routes.get("/api/v1/namespaces/secondary/configmaps/ca.pem")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/api/v1/namespaces/secondary/configmaps")
    async def _(request):
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    spec_manifest = nginx_manifest[:1]

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=spec_manifest,
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
    assert stored.metadata.deleted is None

    token, url = get_hook_environment_value(stored)

    # Attempt to send a request to the hook endpoint without a certificate. Should fail.
    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        complete = ApplicationComplete(token=token)
        # `ClientSSLError` encompasses both `ClientConnectorCertificateError` and
        # `ClientConnectorSSLError`. With Python 3.6, a `ClientConnectorSSLError` is
        # raised, while with 3.7 an update of the ssl module makes aiohttp raise a
        # `ClientConnectorCertificateError`.
        with pytest.raises(aiohttp.ClientSSLError):
            await client.session.put(url, json=complete.serialize())

    # Attempt to send a request to the hook endpoint with a certificate. Should succeed.
    configmap = stored.status.manifest[1]
    certificate = configmap["data"]["ca.pem"]

    with tempfile.TemporaryDirectory() as tmpdirname:
        cert_path = os.path.join(tmpdirname, "ca.pem")

        with open(cert_path, "w") as f:
            f.write(certificate)

        hook_ssl_context = ssl.create_default_context(cafile=cert_path)

    async with Client(
        url=server_endpoint(api_server), loop=loop, ssl_context=hook_ssl_context
    ) as client:
        complete = ApplicationComplete(token=token)
        resp = await client.session.put(url, json=complete.serialize())
        assert resp.status == 200

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.metadata.deleted is not None


async def test_complete_hook_reschedule(
    aiohttp_server, config, pki, db, loop, hooks_config
):
    """Attempt to reschedule an Application augmented with the "complete" hook. Enable
    TLS to use the "full-featured" hook (with the ConfigMap containing a certificate).

    Conditions:
     * TLS:  enabled
     * RBAC: disabled
     * extras: give the Application a second time to the Kubernetes controller, to
       trigger it to handle the Application as if it was rescheduled. Have TLS enabled
       to generate a ConfigMap on the Application.

    Expectations:
        The rescheduling should occur without any interference of the resources
        generated by the "complete" hook and without any change applied to these
        resources.

    """
    routes = web.RouteTableDef()

    server_cert = pki.gencert("api-server")
    config.tls = TlsServerConfiguration(
        enabled=True, client_ca=pki.ca.cert, cert=server_cert.cert, key=server_cert.key
    )

    client_cert = pki.gencert("client")
    client_tls = TlsClientConfiguration(
        enabled=True,
        client_ca=pki.ca.cert,
        client_cert=client_cert.cert,
        client_key=client_cert.key,
    )
    ssl_context = create_ssl_context(client_tls)

    @routes.get("/api/v1/namespaces/secondary/configmaps/ca.pem")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/api/v1/namespaces/secondary/configmaps")
    async def _(request):
        return web.Response(status=200)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=404)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)
    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # We only consider the first resource in the manifest file, that is a Deployment.
    # This Deployment should be modified by the "complete" hook with ENV vars.
    deployment_manifest = deepcopy(nginx_manifest[0])

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__hooks=["complete"],
        spec__manifest=[deployment_manifest],
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
        # Observer started here in order to be stopped afterwards,
        # otherwise get an exception from the Controller trying to stop a non-existing
        # Observer.
        await controller.resource_received(app, start_observer=True)

        stored = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored.status.state == ApplicationState.RUNNING
        assert stored.status.manifest is not None

        previous_manifest = stored.status.manifest

        # Do a rescheduling --> start the reconciliation loop
        await controller.resource_received(stored, start_observer=False)

        stored = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored.status.state == ApplicationState.RUNNING
        assert stored.status.manifest is not None

    # Ensure that the rescheduling kept the resources created by the "complete"
    # hook.
    assert stored.status.manifest == previous_manifest
