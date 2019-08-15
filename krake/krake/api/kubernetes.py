from datetime import datetime
from aiohttp import web

from krake.apidefs.kubernetes import kubernetes
from krake.data.kubernetes import (
    Application,
    ClusterBinding,
    ApplicationState,
    Cluster,
    ClusterState,
)
from .helpers import use_schema, load, session
from .manager import ApiManager


api = ApiManager(kubernetes)


@api.applications.binding.update
@load("app", Application)
@use_schema("body", ClusterBinding.Schema)
async def update_binding(request, body, app):
    app.status.cluster = body.cluster

    # Transition into "scheduled" state
    app.status.state = ApplicationState.SCHEDULED
    app.status.reason = None

    # TODO: Should be update modified here?
    # app.metadata.modified = datetime.now()

    await session(request).put(app)
    api.logger.info(
        "Update Kubernetes application binding %r (%s)",
        app.metadata.name,
        app.metadata.uid,
    )
    return web.json_response(app.serialize())


@api.clusters.delete
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

    cluster.metadata.deleted = datetime.now()
    cluster.status.state = ClusterState.DELETING

    # TODO: Should be update modified here?
    # cluster.metadata.modified = datetime.now()

    await session(request).put(cluster)
    logger.info(
        "Deleting Kubernetes cluster %r (%s)",
        cluster.metadata.name,
        cluster.metadata.uid,
    )

    return web.json_response(serialize(cluster))
