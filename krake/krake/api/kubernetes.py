import logging
from datetime import datetime
from aiohttp import web

from krake.apidefs.kubernetes import kubernetes
from krake.data.core import Conflict, resource_ref
from krake.data.kubernetes import Application, ClusterBinding, ApplicationState, Cluster
from .auth import protected
from .helpers import use_schema, load, session
from .generator import generate_api


logger = logging.getLogger("krake.api.kubernetes")


@generate_api(kubernetes)
class KubernetesApi:
    @protected(api="kubernetes", resource="applications/binding", verb="update")
    @load("app", Application)
    @use_schema("body", ClusterBinding.Schema)
    async def update_application_binding(request, body, app):
        app.status.cluster = body.cluster

        # Transition into "scheduled" state
        app.status.state = ApplicationState.SCHEDULED
        app.status.reason = None

        # TODO: Should be update modified here?
        # app.metadata.modified = datetime.now()

        await session(request).put(app)
        logger.info(
            "Update binding of application %r (%s)", app.metadata.name, app.metadata.uid
        )
        return web.json_response(app.serialize())

    @protected(api="kubernetes", resource="clusters", verb="delete")
    @load("cluster", Cluster)
    async def delete_cluster(request, cluster):
        # Cluster is already deleting
        if cluster.metadata.deleted:
            return web.json_response(cluster.serialize())

        apps = [
            app
            async for app in session(request).all(
                Application, namespace=cluster.metadata.namespace
            )
        ]
        cluster_ref = resource_ref(cluster)
        apps = [
            resource_ref(app)
            for app in apps
            if app.status.cluster == cluster_ref and not app.metadata.deleted
        ]

        # No depending applications and no finalizers, delete application from database
        if not apps and not cluster.metadata.finalizers:
            # TODO: The deletion from database should be done via garbage
            #   collection (see #235)
            await session(request).delete(cluster)
            return web.Response(status=204)

        if apps and "cascade" not in request.query:
            # Do not delete if Applications are running on the cluster
            conflict = Conflict(source=resource_ref(cluster), conflicting=apps)
            return web.json_response(status=409, data=conflict.serialize())

        # Cluster is already in "deleting" state
        if cluster.metadata.deleted:
            return web.json_response(cluster.serialize())

        cluster.metadata.deleted = datetime.now()

        # Append cascading finializer if not already present
        if "cascading_deletion" not in cluster.metadata.finalizers:
            cluster.metadata.finalizers.append("cascading_deletion")

        # TODO: Should be update modified here?
        # cluster.metadata.modified = datetime.now()

        await session(request).put(cluster)
        logger.info(
            "Deleting Kubernetes cluster %r (%s)",
            cluster.metadata.name,
            cluster.metadata.uid,
        )

        return web.json_response(cluster.serialize())
