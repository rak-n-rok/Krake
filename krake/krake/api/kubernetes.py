import logging
from aiohttp import web

from krake.apidefs.kubernetes import kubernetes
from krake.data.kubernetes import Application, ClusterBinding, ApplicationState
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
        app.metadata.owners.append(body.cluster)

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
