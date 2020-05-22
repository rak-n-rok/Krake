import logging
from aiohttp import web
from krake import utils

from krake.apidefs.kubernetes import kubernetes
from krake.data.kubernetes import Application, ClusterBinding, ApplicationComplete
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
        now = utils.now()
        app.status.scheduled = now
        app.status.kube_controller_triggered = now
        app.status.scheduled_to = body.cluster

        if body.cluster not in app.metadata.owners:
            app.metadata.owners.append(body.cluster)

        await session(request).put(app)
        logger.info(
            "Update binding of application %r (%s)", app.metadata.name, app.metadata.uid
        )
        return web.json_response(app.serialize())

    @protected(api="kubernetes", resource="applications/complete", verb="update")
    @load("app", Application)
    @use_schema("body", ApplicationComplete.Schema)
    async def update_application_complete(request, body, app):
        # If the hook is not enabled for the Application or if the token is invalid
        if app.status.token is None or app.status.token != body.token:
            raise web.HTTPUnauthorized()

        # Resource marked as deletion, to be deleted by the Garbage Collector
        app.metadata.deleted = utils.now()
        await session(request).put(app)
        logger.info(
            "Deleting of application %r (%s) by calling complete hook",
            app.metadata.name,
            app.metadata.uid,
        )
        return web.json_response(app.serialize())
