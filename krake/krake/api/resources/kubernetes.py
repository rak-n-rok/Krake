import json
from uuid import uuid4
from datetime import datetime
import logging
from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs
from marshmallow_enum import EnumField


from krake.data.serializable import serialize, deserialize
from krake.data.kubernetes import (
    Application,
    ApplicationStatus,
    ApplicationState,
    Cluster,
)
from ..helpers import session, with_resource, json_error
from ..database import EventType


logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.get("/kubernetes/applications")
async def list_applications(request):
    apps = [app async for app, _ in session(request).all(Application)]
    return web.json_response([serialize(app) for app in apps])


@routes.post("/kubernetes/applications")
@use_kwargs({"manifest": fields.String(required=True)})
async def create_application(request, manifest):
    app_id = str(uuid4())
    # TODO: Load from authentication
    user_id = str(uuid4())

    now = datetime.now()

    status = ApplicationStatus(
        state=ApplicationState.PENDING, created=now, modified=now
    )
    app = Application(id=app_id, user_id=user_id, manifest=manifest, status=status)
    await session(request).put(app)
    logger.info("Created Application %r", app.id)

    return web.json_response(serialize(app))


@routes.put("/kubernetes/applications/{id}")
@use_kwargs({"manifest": fields.String(required=True)})
@with_resource("app", Application)
async def update_application(request, app, manifest):
    if app.status.state == ApplicationState.DELETED:
        raise json_error(web.HTTPBadRequest, {"reason": "Application is deleted"})

    app.manifest = manifest
    app.status.state = ApplicationState.UPDATED
    app.status.reason = None
    app.status.modified = datetime.now()

    await session(request).put(app)
    logger.info("Updated Application %r", app.id)

    return web.json_response(serialize(app))


@routes.put("/kubernetes/applications/{id}/status")
@use_kwargs(
    {
        "state": EnumField(ApplicationState, required=True),
        "reason": fields.String(default=None, allow_none=True),
        "cluster": fields.String(default=None, allow_none=True),
    }
)
@with_resource("app", Application)
async def update_application_status(request, app, state, reason, cluster):
    if app.status.state == ApplicationState.DELETED:
        raise json_error(web.HTTPBadRequest, {"reason": "Application is deleted"})

    # Explicitly copy state changes
    app.status.state = state
    app.status.reason = reason
    app.status.cluster = cluster
    app.status.modified = datetime.now()

    await session(request).put(app)
    logger.info("Updated Application status %r", app.id)

    return web.json_response(serialize(app.status))


@routes.delete("/kubernetes/applications/{id}")
@with_resource("app", Application)
async def delete_application(request, app):
    if app.status.state == ApplicationState.DELETED:
        raise web.HTTPNotModified()

    app.status.state = ApplicationState.DELETED
    app.status.reason = None
    app.status.modified = datetime.now()

    await session(request).put(app)
    logger.info("Deleted Application %r", app.id)

    return web.json_response(serialize(app))


@routes.get("/kubernetes/applications/watch")
async def watch_applications(request):
    resp = web.StreamResponse(headers={"Content-Type": "application/json"})
    resp.enable_chunked_encoding()

    await resp.prepare(request)

    async for event, app, rev in session(request).watch(Application):

        # Key was deleted. Stop update stream
        if event == EventType.DELETE:
            return

        await resp.write(json.dumps(serialize(app)).encode())
        await resp.write(b"\n")


@routes.get("/kubernetes/clusters")
async def list_clusteres(request):
    apps = [cluster async for cluster, _ in session(request).all(Cluster)]
    return web.json_response([serialize(app) for app in apps])
