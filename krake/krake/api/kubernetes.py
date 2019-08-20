"""This module comprises request handlers forming the HTTP REST API for
Kubernetes resources.
"""
import json
from uuid import uuid4
from datetime import datetime
import logging
from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs
from marshmallow_enum import EnumField
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.config import ConfigException

from krake.data.serializable import serialize
from krake.data.core import NamespacedMetadata, ClientMetadata, Conflict, resource_ref
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
from .helpers import session, json_error, Heartbeat, load
from .auth import protected
from .database import EventType


logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.get("/kubernetes/namespaces/{namespace}/applications")
@protected(api="kubernetes", resource="applications", verb="list")
@use_kwargs({"heartbeat": fields.Integer(missing=None, locations=["query"])})
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

    kwargs = {}
    if namespace != "all":
        kwargs["namespace"] = namespace

    async with session(request).watch(Application, **kwargs) as watcher:
        resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        resp.enable_chunked_encoding()

        await resp.prepare(request)

        async with Heartbeat(resp, interval=heartbeat):
            async for event, app, rev in watcher:

                # Key was deleted. Stop update stream
                if event == EventType.DELETE:
                    return

                await resp.write(json.dumps(serialize(app)).encode())
                await resp.write(b"\n")


@routes.post("/kubernetes/namespaces/{namespace}/applications")
@protected(api="kubernetes", resource="applications", verb="create")
@use_kwargs(
    {
        "metadata": fields.Nested(ClientMetadata.Schema, required=True),
        "spec": fields.Nested(ApplicationSpec.Schema, required=True),
    }
)
async def create_application(request, metadata, spec):
    namespace = request.match_info["namespace"]
    if namespace == "all":
        raise json_error(web.HTTPBadRequest, {"reason": "'all' namespace is read-only"})

    # Ensure that an application with the same name does not already exists
    app, _ = await session(request).get(
        Application, namespace=namespace, name=metadata.name
    )
    if app is not None:
        raise json_error(
            web.HTTPBadRequest,
            {"reason": f"Application {metadata.name!r} already exists"},
        )

    now = datetime.now()

    app = Application(
        metadata=NamespacedMetadata(
            name=metadata.name,
            namespace=namespace,
            user=request["user"],
            uid=str(uuid4()),
        ),
        spec=spec,
        status=ApplicationStatus(
            state=ApplicationState.PENDING, created=now, modified=now
        ),
    )
    await session(request).put(app)
    logger.info("Created Application %r", app.metadata.uid)

    return web.json_response(serialize(app))


@routes.get("/kubernetes/namespaces/{namespace}/applications/{name}")
@protected(api="kubernetes", resource="applications", verb="get")
@load("app", Application)
async def get_application(request, app):
    return web.json_response(serialize(app))


@routes.put("/kubernetes/namespaces/{namespace}/applications/{name}")
@protected(api="kubernetes", resource="applications", verb="update")
@use_kwargs({"spec": fields.Nested(ApplicationSpec.Schema, required=True)})
@load("app", Application)
async def update_application(request, app, spec):
    if app.status.state in (ApplicationState.DELETING, ApplicationState.DELETED):
        raise json_error(web.HTTPBadRequest, {"reason": "Application is deleted"})

    app.spec = spec
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


@routes.put("/kubernetes/namespaces/{namespace}/applications/{name}/status")
@protected(api="kubernetes", resource="applications/status", verb="update")
@use_kwargs(
    {
        "state": EnumField(ApplicationState, required=True),
        "reason": fields.String(required=True, allow_none=True),
        "cluster": fields.String(required=True, allow_none=True),
        "services": fields.Dict(required=True, allow_none=True),
    }
)
@load("app", Application)
async def update_application_status(request, app, state, reason, cluster, services):
    app.status.state = state
    app.status.reason = reason
    app.status.cluster = cluster
    app.status.services = services
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


@routes.put("/kubernetes/namespaces/{namespace}/applications/{name}/binding")
@protected(api="kubernetes", resource="applications/binding", verb="update")
@use_kwargs({"cluster": fields.String(required=True)})
@load("app", Application)
async def update_application_binding(request, app, cluster):
    app.status.cluster = cluster

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


@routes.delete("/kubernetes/namespaces/{namespace}/applications/{name}")
@protected(api="kubernetes", resource="applications", verb="delete")
@load("app", Application)
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


@routes.get("/kubernetes/namespaces/{namespace}/clusters")
@protected(api="kubernetes", resource="clusters", verb="list")
@use_kwargs({"heartbeat": fields.Integer(missing=None, locations=["query"])})
async def list_or_watch_clusters(request, heartbeat):
    namespace = request.match_info["namespace"]

    if "watch" not in request.query:
        if namespace == "all":
            clusters = [cluster async for cluster, _ in session(request).all(Cluster)]
        else:
            clusters = [
                cluster
                async for cluster, _ in session(request).all(
                    Cluster, namespace=namespace
                )
            ]

        # Filter DELETED clusters
        clusters = (
            cluster
            for cluster in clusters
            if cluster.status.state != ClusterState.DELETED
        )

        return web.json_response([serialize(cluster) for cluster in clusters])

    kwargs = {}
    if namespace != "all":
        kwargs["namespace"] = namespace

    async with session(request).watch(Cluster, **kwargs) as watcher:
        resp = web.StreamResponse(headers={"Content-Type": "cluster/x-ndjson"})
        resp.enable_chunked_encoding()

        await resp.prepare(request)

        async with Heartbeat(resp, interval=heartbeat):
            async for event, cluster, rev in watcher:

                # Key was deleted. Stop update stream
                if event == EventType.DELETE:
                    return

                await resp.write(json.dumps(serialize(cluster)).encode())
                await resp.write(b"\n")


@routes.post("/kubernetes/namespaces/{namespace}/clusters")
@protected(api="kubernetes", resource="clusters", verb="create")
@use_kwargs(
    {
        "metadata": fields.Nested(ClientMetadata.Schema, required=True),
        "spec": fields.Nested(ClusterSpec.Schema, request=True),
    }
)
async def create_cluster(request, metadata, spec):
    namespace = request.match_info["namespace"]
    if namespace == "all":
        raise json_error(web.HTTPBadRequest, {"reason": "'all' namespace is read-only"})

    try:
        KubeConfigLoader(spec.kubeconfig)
    except ConfigException as err:
        raise json_error(web.HTTPBadRequest, {"reason": str(err)})

    if len(spec.kubeconfig["contexts"]) != 1:
        raise json_error(web.HTTPBadRequest, {"reason": f"Only one context is allowed"})

    if len(spec.kubeconfig["users"]) != 1:
        raise json_error(web.HTTPBadRequest, {"reason": f"Only one user is allowed"})

    if len(spec.kubeconfig["clusters"]) != 1:
        raise json_error(web.HTTPBadRequest, {"reason": f"Only one cluster is allowed"})

    now = datetime.now()
    cluster = Cluster(
        metadata=NamespacedMetadata(
            name=metadata.name, namespace=namespace, user=request["user"], uid=uuid4()
        ),
        spec=spec,
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


@routes.get("/kubernetes/namespaces/{namespace}/clusters/{name}")
@protected(api="kubernetes", resource="clusters", verb="get")
@load("cluster", Cluster)
async def get_cluster(request, cluster):
    return web.json_response(serialize(cluster))


@routes.put("/kubernetes/namespaces/{namespace}/clusters/{name}/status")
@protected(api="kubernetes", resource="cluster/status", verb="update")
@use_kwargs(
    {
        "state": EnumField(ClusterState, required=True),
        "reason": fields.String(required=True, allow_none=True),
    }
)
@load("cluster", Cluster)
async def update_cluster_status(request, cluster, state, reason):
    cluster.status.state = state
    cluster.status.reason = reason
    cluster.status.modified = datetime.now()

    if cluster.status.state == ClusterState.DELETED:
        await session(request).delete(cluster)
        logger.info(
            "Deleted Kubernetes cluster status %r (%s)",
            cluster.metadata.name,
            cluster.metadata.uid,
        )
    else:
        raise web.HTTPNotModified()

    return web.json_response(serialize(cluster.status))


@routes.delete("/kubernetes/namespaces/{namespace}/clusters/{name}")
@protected(api="kubernetes", resource="clusters", verb="delete")
@load("cluster", Cluster)
async def delete_cluster(request, cluster):
    if cluster.status.state in (ClusterState.DELETING, ClusterState.DELETED):
        raise web.HTTPNotModified()

    if "cascade" not in request.query:
        apps = [
            app
            async for app, _ in session(request).all(
                Application, namespace=cluster.metadata.namespace
            )
        ]
        cluster_ref = (
            f"/kubernetes/namespaces/{cluster.metadata.namespace}"
            f"/clusters/{cluster.metadata.name}"
        )
        accepted_states = (
            ApplicationState.RUNNING,
            ApplicationState.UPDATED,
            ApplicationState.SCHEDULED,
        )

        apps = [
            resource_ref(app)
            for app in apps
            if app.status.cluster == cluster_ref and app.status.state in accepted_states
        ]
        # Do not delete if Applications are running on the cluster
        if len(apps) > 0:
            conflict = Conflict(source=resource_ref(cluster), conflicting=apps)
            return web.json_response(status=409, data=serialize(conflict))

    cluster.status.state = ClusterState.DELETING
    cluster.status.reason = None
    cluster.status.modified = datetime.now()

    await session(request).put(cluster)
    logger.info(
        "Deleting Kubernetes cluster %r (%s)",
        cluster.metadata.name,
        cluster.metadata.uid,
    )

    return web.json_response(serialize(cluster))
