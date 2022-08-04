import asyncio
from contextlib import suppress
from copy import deepcopy
from typing import NamedTuple

import pytest
import pytz
from aiohttp import web

from krake.api.app import create_app
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes.application import (
    KubernetesApplicationController,
)
from krake.client import Client
from krake.test_utils import server_endpoint
from tests.factories import fake

from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)

from tests.controller.kubernetes import (
    deployment_manifest,
    service_manifest,
    secret_manifest,
    job_manifest,
    pv_manifest,
    cluster_role_manifest,
    deployment_response,
    service_response,
    secret_response,
    job_response,
    pv_response,
    cluster_role_response,
    initial_last_observed_manifest_deployment,
    initial_last_observed_manifest_service,
    initial_last_observed_manifest_secret,
    initial_last_observed_manifest_job,
    initial_last_observed_manifest_pv,
    initial_last_observed_manifest_cluster_role,
)


class Routes(NamedTuple):
    get: str
    post: str
    patch: str
    delete: str


class Deployment(NamedTuple):
    routes: Routes = Routes(
        get="/apis/apps/v1/namespaces/{namespace}/deployments/{name}",
        post="/apis/apps/v1/namespaces/{namespace}/deployments",
        patch="/apis/apps/v1/namespaces/{namespace}/deployments/{name}",
        delete="/apis/apps/v1/namespaces/{namespace}/deployments/{name}",
    )
    response: dict = deployment_response
    manifest: dict = deployment_manifest
    manifest_last_observed: dict = initial_last_observed_manifest_deployment


class Service(NamedTuple):
    routes: Routes = Routes(
        get="/api/v1/namespaces/{namespace}/services/{name}",
        post="/api/v1/namespaces/{namespace}/services",
        patch="/api/v1/namespaces/{namespace}/services/{name}",
        delete="/api/v1/namespaces/{namespace}/services/{name}",
    )
    response: dict = service_response
    manifest: dict = service_manifest
    manifest_last_observed: dict = initial_last_observed_manifest_service


class Secret(NamedTuple):
    routes: Routes = Routes(
        get="/api/v1/namespaces/{namespace}/secrets/{name}",
        post="/api/v1/namespaces/{namespace}/secrets",
        patch="/api/v1/namespaces/{namespace}/secrets/{name}",
        delete="/api/v1/namespaces/{namespace}/secrets/{name}",
    )
    response: dict = secret_response
    manifest: dict = secret_manifest
    manifest_last_observed: dict = initial_last_observed_manifest_secret


class Job(NamedTuple):
    routes: Routes = Routes(
        get="/apis/batch/v1/namespaces/{namespace}/jobs/{name}",
        post="/apis/batch/v1/namespaces/{namespace}/jobs",
        patch="/apis/batch/v1/namespaces/{namespace}/jobs/{name}",
        delete="/apis/batch/v1/namespaces/{namespace}/jobs/{name}",
    )
    response: dict = job_response
    manifest: dict = job_manifest
    manifest_last_observed: dict = initial_last_observed_manifest_job


class PersistentVolume(NamedTuple):
    routes: Routes = Routes(
        get="/api/v1/persistentvolumes/{name}",
        post="/api/v1/persistentvolumes",
        patch="/api/v1/persistentvolumes/{name}",
        delete="/api/v1/persistentvolumes/{name}",
    )
    response: dict = pv_response
    manifest: dict = pv_manifest
    manifest_last_observed: dict = initial_last_observed_manifest_pv


class ClusterRole(NamedTuple):
    routes: Routes = Routes(
        get="/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}",
        post="/apis/rbac.authorization.k8s.io/v1/clusterroles",
        patch="/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}",
        delete="/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}",
    )
    response: dict = cluster_role_response
    manifest: dict = cluster_role_manifest
    manifest_last_observed: dict = initial_last_observed_manifest_cluster_role


@pytest.mark.parametrize(
    "resources",
    [Deployment(), Service(), Secret(), Job(), PersistentVolume(), ClusterRole()],
)
async def test_resource_creation(aiohttp_server, config, db, loop, resources):
    """Test the creation of a resource

    The Kubernetes Controller should create the resource encapsulated as a Krake
    application and update the DB.

    """

    routes = web.RouteTableDef()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a resource already exists.
    @routes.get(resources.routes.get)
    async def _(request):
        assert resources.manifest["metadata"]["name"] == request.match_info["name"]
        assert resources.manifest["metadata"].get(
            "namespace"
        ) == request.match_info.get("namespace")

        return web.Response(status=404)

    # As part of the reconciliation loop, the k8s controller creates the resource.
    @routes.post(resources.routes.post)
    async def _(request):
        body = await request.json()
        assert resources.manifest["metadata"]["name"] == body["metadata"]["name"]
        assert resources.manifest["metadata"].get("namespace") == body["metadata"].get(
            "namespace"
        )

        return web.json_response(resources.response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # When received by the k8s controller, the application is in PENDING state and
    # scheduled to a cluster. It contains a resource manifest.
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__scheduled_to=resource_ref(cluster),
        status__is_scheduled=False,
        spec__manifest=[resources.manifest],
    )
    await db.put(cluster)
    await db.put(app)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(api_server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, and updates the application in the DB accordingly.
        await controller.resource_received(app, start_observer=False)

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


@pytest.mark.parametrize(
    "resources",
    [Deployment(), Service(), Secret(), Job(), PersistentVolume(), ClusterRole()],
)
async def test_resource_deletion(aiohttp_server, config, db, loop, resources):
    """Test the deletion of a resource

    The Kubernetes Controller should delete the resource encapsulated as a Krake
    application and update the DB.

    """
    kubernetes_app = web.Application()
    routes = web.RouteTableDef()
    deleted = set()

    # As part of the deletion, the k8s controller deletes the resource
    # from the k8s cluster.
    @routes.delete(resources.routes.delete)
    async def _(request):
        assert resources.manifest["metadata"]["name"] == request.match_info["name"]
        assert resources.manifest["metadata"].get(
            "namespace"
        ) == request.match_info.get("namespace")

        deleted.add(resources.manifest["metadata"]["name"])
        return web.Response(status=200)

    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # The application possesses the deleted timestamp, meaning it should be deleted.
    app = ApplicationFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        spec__manifest=[resources.manifest],
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=resource_ref(cluster),
        status__running_on=resource_ref(cluster),
        status__last_observed_manifest=[resources.manifest_last_observed],
        metadata__finalizers=["kubernetes_resources_deletion"],
    )
    assert resource_ref(cluster) in app.metadata.owners

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        reflector_task = loop.create_task(controller.application_reflector())

        await controller.handle_resource(run_once=True)
        # During deletion, the Application is updated, thus re-enqueued
        assert controller.queue.size() == 1

        # The re-enqueued Application is ignored, as not present on the
        # database anymore.
        await controller.handle_resource(run_once=True)
        assert controller.queue.size() == 0

        reflector_task.cancel()

        with suppress(asyncio.CancelledError):
            await reflector_task

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored is None
    assert deleted == {resources.manifest["metadata"]["name"]}


@pytest.mark.parametrize(
    "resources",
    [Deployment(), Service(), Secret(), Job(), PersistentVolume(), ClusterRole()],
)
async def test_resource_update(aiohttp_server, config, db, loop, resources):
    """Test the update of a running resource

    The Kubernetes Controller should patch the resource encapsulated as a Krake
    application and update the DB.

    """
    routes = web.RouteTableDef()
    expected_labels = {"patched": "true"}
    patched = set()

    # As part of the reconciliation loop started by ``controller.resource_received``,
    # the k8s controller checks if a resource already exists.
    @routes.get(resources.routes.get)
    async def _(request):
        assert resources.manifest["metadata"]["name"] == request.match_info["name"]
        assert resources.manifest["metadata"].get(
            "namespace"
        ) == request.match_info.get("namespace")

        return web.json_response(resources.manifest)

    # As part of the reconciliation loop, the k8s controller patch the existing
    # resource which has been modified.
    @routes.patch(resources.routes.patch)
    async def _(request):
        body = await request.json()
        assert resources.manifest["metadata"]["name"] == request.match_info["name"]
        assert resources.manifest["metadata"].get(
            "namespace"
        ) == request.match_info.get("namespace")

        # Apply resource labels from request
        response = deepcopy(resources.manifest)
        response["metadata"]["labels"] = body["metadata"]["labels"]

        patched.add(response["metadata"]["name"])
        return web.json_response(response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    # Update resource manifest with labels
    manifest = deepcopy(resources.manifest)
    manifest["metadata"]["labels"] = expected_labels

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        status__last_observed_manifest=[
            resources.manifest_last_observed,
        ],
        spec__manifest=[manifest],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesApplicationController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        # The resource is received by the controller, which starts the reconciliation
        # loop, and updates the application in the DB accordingly.
        await controller.resource_received(app, start_observer=False)

    assert patched == {resources.manifest["metadata"]["name"]}

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )

    assert (
        stored.status.last_observed_manifest[0]["metadata"]["labels"] == expected_labels
    )
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.metadata.finalizers[-1] == "kubernetes_resources_deletion"


@pytest.mark.parametrize(
    "resources",
    [Deployment(), Service(), Secret(), Job(), PersistentVolume(), ClusterRole()],
)
async def test_resource_migration(aiohttp_server, config, db, loop, resources):
    """Test the migration of a resource

    The Application is scheduled to a different cluster. The controller should delete
    resources from the old cluster and create resources on the new cluster.

    """
    routes = web.RouteTableDef()

    # As part of the migration started by ``controller.resource_received``, the k8s
    # controller checks if the resource already exists
    @routes.get(resources.routes.get)
    async def _(request):
        assert resources.manifest["metadata"]["name"] == request.match_info["name"]
        assert resources.manifest["metadata"].get(
            "namespace"
        ) == request.match_info.get("namespace")

        # The k8s API only replies with the resource if it is existing.
        if request.match_info["name"] in request.app["existing"]:
            return web.json_response(resources.manifest)

        # If the resource doesn't exist, return a 404 response
        return web.Response(status=404)

    # As part of the migration, the k8s controller creates a new resource on the
    # target cluster
    @routes.post(resources.routes.post)
    async def _(request):
        body = await request.json()
        assert resources.manifest["metadata"]["name"] == body["metadata"]["name"]
        assert resources.manifest["metadata"].get("namespace") == body["metadata"].get(
            "namespace"
        )

        request.app["created"].add(body["metadata"]["name"])
        return web.json_response(resources.response)

    # As part of the migration, the k8s controller deletes a resource on the old
    # cluster
    @routes.delete(resources.routes.delete)
    async def delete_deployment(request):
        request.app["deleted"].add(request.match_info["name"])
        return web.Response(status=200)

    async def make_kubernetes_api(existing=()):
        app = web.Application()
        app["created"] = set()
        app["deleted"] = set()
        app["existing"] = set(existing)  # Set of existing resource

        app.add_routes(routes)

        return await aiohttp_server(app)

    kubernetes_server_A = await make_kubernetes_api(
        {resources.manifest["metadata"]["name"]}
    )
    kubernetes_server_B = await make_kubernetes_api()

    cluster_A = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server_A))
    cluster_B = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server_B))

    # The application is in RUNNING state on cluster_A, and is scheduled on cluster_B.
    # The controller should trigger a migration (i.e. delete existing resource defined
    # by last_observed_manifest on cluster_A and create new resource on cluster_B)
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=True,
        status__running_on=resource_ref(cluster_A),
        status__scheduled_to=resource_ref(cluster_B),
        status__last_observed_manifest=[resources.manifest_last_observed],
        spec__manifest=[resources.manifest],
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

        # The resource is received by the controller, which starts the migration and
        # updates the application in the DB accordingly.
        await controller.resource_received(app, start_observer=False)

    assert kubernetes_server_A.app["deleted"] == {
        resources.manifest["metadata"]["name"]
    }
    assert kubernetes_server_B.app["created"] == {
        resources.manifest["metadata"]["name"]
    }

    stored = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert stored.status.state == ApplicationState.RUNNING
    assert stored.status.running_on == resource_ref(cluster_B)
    assert resource_ref(cluster_A) not in stored.metadata.owners
    assert resource_ref(cluster_B) in stored.metadata.owners
