import json
import asyncio
from uuid import uuid4
from datetime import datetime
import logging
from functools import wraps
from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs
from marshmallow_enum import EnumField
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.config import ConfigException

from krake.data.serializable import serialize, deserialize
from krake.data.metadata import Metadata
from krake.data.kubernetes import (
    Application,
    ApplicationStatus,
    ApplicationState,
    ApplicationSpec,
    ClusterBinding,
    Cluster,
    ClusterStatus,
    ClusterState,
    ClusterSpec,
)
from ..helpers import session, json_error, protected, Heartbeat
from ..database import EventType


logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


def with_app(handler):
    """Decorator loading Kubernetes applications by dynamic URL and
    authenticated user.

    If the application could not be found the wrapped handler raises an HTTP
    404 error.

    Args:
        handler (coroutine): aiohttp request handler

    Returns:
        Returns a wrapped handler injecting the loaded Kubernetes application
        as ``app`` keyword.

    """

    @wraps(handler)
    async def wrapper(request, *args, **kwargs):
        app, rev = await session(request).get(
            Application,
            namespace=request.match_info["namespace"],
            name=request.match_info["name"],
        )
        if app is None:
            raise web.HTTPNotFound()
        return await handler(request, *args, app=app, **kwargs)

    return wrapper


def with_cluster(handler):
    """Decorator loading Kubernetes cluster by dynamic URL and
    authenticated user.

    If the cluster could not be found the wrapped handler raises an HTTP
    404 error.

    Args:
        handler (coroutine): aiohttp request handler

    Returns:
        Returns a wrapped handler injecting the loaded Kubernetes cluster
        as ``cluster`` keyword.

    """

    @wraps(handler)
    async def wrapper(request, *args, **kwargs):
        cluster, rev = await session(request).get(
            Cluster,
            namespace=request.match_info["namespace"],
            name=request.match_info["name"],
        )
        if cluster is None:
            raise web.HTTPNotFound()
        return await handler(request, *args, cluster=cluster, **kwargs)

    return wrapper


@routes.get("/namespaces/{namespace}/kubernetes/applications")
@use_kwargs({"heartbeat": fields.Integer(missing=None, locations=["query"])})
@protected
async def list_or_watch_applications(request, heartbeat):
    namespace = request.match_info["namespace"]

    if "watch" not in request.query:
        if namespace == "all":
            apps = [app async for app, _ in session(request).all(Application)]
        else:
            apps = [
                app
                async for app, _ in session(request).all(
                    Application, namespace=namespace
                )
            ]

        # Filter DELETED applications
        if "deleted" not in request.query:
            apps = (app for app in apps if app.status.state != ApplicationState.DELETED)

        return web.json_response([serialize(app) for app in apps])
    else:
        resp = web.StreamResponse(headers={"Content-Type": "application/json"})
        resp.enable_chunked_encoding()

        await resp.prepare(request)

        async with Heartbeat(resp, interval=heartbeat):
            if namespace == "all":
                watcher = session(request).watch(Application)
            else:
                watcher = session(request).watch(Application, namespace=namespace)

            async for event, app, rev in watcher:

                # Key was deleted. Stop update stream
                if event == EventType.DELETE:
                    return

                await resp.write(json.dumps(serialize(app)).encode())
                await resp.write(b"\n")


@routes.post("/namespaces/{namespace}/kubernetes/applications")
@protected
@use_kwargs(
    {"name": fields.String(required=True), "manifest": fields.String(required=True)}
)
async def create_application(request, name, manifest):
    namespace = request.match_info["namespace"]
    if namespace == "all":
        raise json_error(web.HTTPBadRequest, {"reason": "'all' namespace is read-only"})

    # Ensure that an application with the same name does not already exists
    app, _ = await session(request).get(Application, namespace=namespace, name=name)
    if app is not None:
        raise json_error(
            web.HTTPBadRequest, {"reason": f"Application {name!r} already exists"}
        )

    now = datetime.now()

    app = Application(
        metadata=Metadata(
            name=name, namespace=namespace, user=request["user"].name, uid=str(uuid4())
        ),
        spec=ApplicationSpec(manifest=manifest),
        status=ApplicationStatus(
            state=ApplicationState.PENDING, created=now, modified=now
        ),
    )
    await session(request).put(app)
    logger.info("Created Application %r", app.metadata.uid)

    return web.json_response(serialize(app))


@routes.get("/namespaces/{namespace}/kubernetes/applications/{name}")
@protected
@with_app
async def get_application(request, app):
    return web.json_response(serialize(app))


@routes.put("/namespaces/{namespace}/kubernetes/applications/{name}")
@protected
@use_kwargs({"manifest": fields.String(required=True)})
@with_app
async def update_application(request, app, manifest):
    if app.status.state in (ApplicationState.DELETING, ApplicationState.DELETED):
        raise json_error(web.HTTPBadRequest, {"reason": "Application is deleted"})

    app.spec.manifest = manifest
    app.status.state = ApplicationState.UPDATED
    app.status.reason = None
    app.status.modified = datetime.now()

    await session(request).put(app)
    logger.info(
        "Update Kubernetes application spec %r (%s)",
        app.metadata.name,
        app.metadata.uid,
    )

    return web.json_response(serialize(app))


@routes.put("/namespaces/{namespace}/kubernetes/applications/{name}/status")
@protected
@use_kwargs(
    {
        "state": EnumField(ApplicationState, required=True),
        "reason": fields.String(required=True, allow_none=True),
        "cluster": fields.String(required=True, allow_none=True),
    }
)
@with_app
async def update_application_status(request, app, state, reason, cluster):
    app.status.state = state
    app.status.reason = reason
    app.status.cluster = cluster
    app.status.modified = datetime.now()

    if app.status.state == ApplicationState.DELETED:
        await session(request).delete(app)
        logger.info(
            "Deleted Kubernetes application status %r (%s)",
            app.metadata.name,
            app.metadata.uid,
        )
    else:
        await session(request).put(app)
        logger.info(
            "Update Kubernetes application status %r to %s (%s)",
            app.metadata.name,
            app.status.state.name,
            app.metadata.uid,
        )

    return web.json_response(serialize(app.status))


@routes.put("/namespaces/{namespace}/kubernetes/applications/{name}/binding")
@protected
@use_kwargs({"cluster": fields.String(required=True)})
@with_app
async def update_application_binding(request, app, cluster):
    app.spec.cluster = cluster

    # Transition into "scheduled" state
    app.status.state = ApplicationState.SCHEDULED
    app.status.reason = None
    app.status.modified = datetime.now()

    await session(request).put(app)
    logger.info(
        "Update Kubernetes application bind %r (%s)",
        app.metadata.name,
        app.metadata.uid,
    )

    binding = ClusterBinding(cluster=cluster)
    return web.json_response(serialize(binding))


@routes.delete("/namespaces/{namespace}/kubernetes/applications/{name}")
@protected
@with_app
async def delete_application(request, app):
    if app.status.state in (ApplicationState.DELETING, ApplicationState.DELETED):
        raise web.HTTPNotModified()

    app.status.state = ApplicationState.DELETING
    app.status.reason = None
    app.status.modified = datetime.now()

    await session(request).put(app)
    logger.info(
        "Deleting Kubernetes application %r (%s)", app.metadata.name, app.metadata.uid
    )

    return web.json_response(serialize(app))


@routes.get("/namespaces/{namespace}/kubernetes/clusters")
@protected
async def list_clusters(request):
    apps = [cluster async for cluster, _ in session(request).all(Cluster)]
    return web.json_response([serialize(app) for app in apps])


@routes.post("/namespaces/{namespace}/kubernetes/clusters")
@protected
async def create_cluster(request):
    namespace = request.match_info["namespace"]
    if namespace == "all":
        raise json_error(web.HTTPBadRequest, {"reason": "'all' namespace is read-only"})

    try:
        kubeconfig = await request.json()
    except JSONDecodeError:
        raise web.UnsupportedMedia()

    if not isinstance(kubeconfig, dict):
        raise json_error(
            web.HTTPBadRequest, {"reason": "kube-config must be a JSON object"}
        )

    try:
        KubeConfigLoader(kubeconfig)
    except ConfigException as err:
        raise json_error(web.HTTPBadRequest, {"reason": str(err)})

    if len(kubeconfig["contexts"]) != 1:
        raise json_error(web.HTTPBadRequest, {"reason": f"Only one context is allowed"})

    if len(kubeconfig["users"]) != 1:
        raise json_error(web.HTTPBadRequest, {"reason": f"Only one user is allowed"})

    if len(kubeconfig["clusters"]) != 1:
        raise json_error(web.HTTPBadRequest, {"reason": f"Only one cluster is allowed"})

    now = datetime.now()
    cluster = Cluster(
        metadata=Metadata(
            name=kubeconfig["clusters"][0]["name"],
            namespace=namespace,
            user=request["user"].name,
            uid=uuid4(),
        ),
        spec=ClusterSpec(kubeconfig=kubeconfig),
        status=ClusterStatus(state=ClusterState.RUNNING, created=now, modified=now),
    )

    # Ensure that a cluster with the same name does not already exists
    existing, _ = await session(request).get(
        Cluster, namespace=namespace, name=cluster.metadata.name
    )
    if existing is not None:
        raise json_error(
            web.HTTPBadRequest,
            {"reason": f"Cluster {cluster.metadata.name!r} already exists"},
        )

    await session(request).put(cluster)
    logger.info(
        "Create Kubernetes cluster %r (%s)", cluster.metadata.name, cluster.metadata.uid
    )

    return web.json_response(serialize(cluster))


@routes.get("/namespaces/{namespace}/kubernetes/clusters/{name}")
@protected
@with_cluster
async def get_cluster(request, cluster):
    return web.json_response(serialize(cluster))


@routes.delete("/namespaces/{namespace}/kubernetes/clusters/{name}")
@protected
@with_cluster
async def delete_cluster(request, cluster):
    cluster.status.state = ClusterState.DELETING
    cluster.status.reason = None
    cluster.status.modified = datetime.now()

    await session(request).put(cluster)
    logger.info("Deleting Kubernetes cluster %r (%s)", cluster.name, cluster.uid)

    return web.json_response(serialize(cluster))
