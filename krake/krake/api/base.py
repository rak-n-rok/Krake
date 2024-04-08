"""Basic abstractions for handling resources in http methods."""
import logging
import dataclasses
import json

from typing import AsyncGenerator, Type
from uuid import uuid4
from aiohttp import web

from krake import utils
from krake.api.helpers import (
    session,
    HttpProblem,
    HttpProblemTitle,
    HttpProblemError,
    Heartbeat,
)
from krake.api.database import TransactionError, EventType
from krake.data.core import ListMetadata, WatchEvent, WatchEventType, ApiObject


logger = logging.getLogger(__name__)


async def update_property_async(
    prop: str, request: web.Request, body: ApiObject, entity: ApiObject
) -> web.json_response:
    """Update a property of a resource.

    Args:
        request: the http request
        body: the requested state
        entity: the resource

    Raises:
        HttpProblemError: if request is a bad request

    Returns:
        web.json_response: the updated resource
    """
    source = getattr(body, prop)
    dest = getattr(entity, prop)

    try:
        dest.update(source)
    except ValueError as e:
        problem = HttpProblem(detail=str(e), title=HttpProblemTitle.UPDATE_ERROR)
        raise HttpProblemError(web.HTTPBadRequest, problem)

    await session(request).put(entity)
    logger.info(
        "Update %s of %s %r (%s)",
        prop,
        entity.kind,
        entity.metadata.name,
        entity.metadata.uid,
    )

    return web.json_response(entity.serialize())


async def watch_resource_async(
    request: web.Request,
    heartbeat: float,
    watcher: AsyncGenerator,
    resource_class: ApiObject,
):
    """Create update stream for a resource class.

    Args:
        request: the http request
        heartbeat: the update interval
        watcher: async generator
        resource_class: the type of resource to watch
    """
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    resp.enable_chunked_encoding()

    await resp.prepare(request)

    async with Heartbeat(resp, interval=heartbeat):
        async for event, obj, rev in watcher:
            # Key was deleted. Stop update stream
            if event == EventType.PUT:
                if rev.created == rev.modified:
                    event_type = WatchEventType.ADDED
                else:
                    event_type = WatchEventType.MODIFIED
            else:
                event_type = WatchEventType.DELETED
                obj = await session(request).get_by_key(
                    resource_class, key=rev.key, revision=rev.modified - 1
                )

            watch_event = WatchEvent(type=event_type, object=obj.serialize())

            await resp.write(json.dumps(watch_event.serialize()).encode())
            await resp.write(b"\n")


async def list_resources_async(
    resource_class: ApiObject,
    list_class: ApiObject,
    request: web.Request,
    namespace: str,
) -> web.json_response:
    """List all entities of a resource class.

    Args:
        resource_class: a type of resource
        list_class: a type of list to create
        request: the http request

    Returns:
        json response containing a list of all entities in resource_class
    """
    if namespace is None:
        objs = [obj async for obj in session(request).all(resource_class)]
    else:
        objs = [
            obj
            async for obj in session(request).all(resource_class, namespace=namespace)
        ]
    body = list_class(metadata=ListMetadata(), items=objs)
    return web.json_response(body.serialize())


async def list_or_watch_resources_async(
    resource_class: Type,
    list_class: Type,
    request: web.Request,
    heartbeat: int,
    watch: bool,
) -> web.Response:
    """List or watch all entities of a resource class.

    Args:
        resource_class (Type): a type of resource
        list_class (Type): a type of list to create
        request (web.Request): the http request
        heartbeat (int): the update interval
        watch (bool): flag that specifies wether the resources should be
            watched instead of listed

    Returns:
        json response containing a list of all entities in resource_class
    """
    namespace = request.match_info.get("namespace", None)

    # Return the list of resources
    if not watch:
        return await list_resources_async(
            resource_class, list_class, request, namespace
        )

    kwargs = {}
    if namespace is not None:
        kwargs["namespace"] = namespace

    # Watching resources
    async with session(request).watch(resource_class, **kwargs) as watcher:
        await watch_resource_async(request, heartbeat, watcher, resource_class)


async def update_resource_async(
    request: web.Request, entity: ApiObject, body: ApiObject
) -> web.Response:
    """Update an entity.

    Args:
        request: the http request
        entity: the stored resource state
        body: the requested resource state

    Raises:
        HttpProblemError: if
          - finalizers were removed after deletion
          - the request contained no update
          - the entity could not be written to database

    Returns:
        json response containing the deleted resource
    """
    # Once a resource is in the "deletion in progress" state, finalizers
    # can only be removed.
    if entity.metadata.deleted:
        if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
            problem = HttpProblem(
                detail="Finalizers can only be removed"
                " if a deletion is in progress.",
                title=HttpProblemTitle.UPDATE_ERROR,
            )
            raise HttpProblemError(web.HTTPConflict, problem)

    if body == entity:
        problem = HttpProblem(
            detail="The body contained no update.", title=HttpProblemTitle.UPDATE_ERROR
        )
        raise HttpProblemError(web.HTTPBadRequest, problem)

    try:
        entity.update(body)
    except ValueError as e:
        problem = HttpProblem(detail=str(e), title=HttpProblemTitle.UPDATE_ERROR)
        raise HttpProblemError(web.HTTPBadRequest, problem)

    entity.metadata.modified = utils.now()

    # Resource is in "deletion in progress" state and all finalizers have
    # been removed. Delete the resource from database.
    if entity.metadata.deleted and not entity.metadata.finalizers:
        await session(request).delete(entity)
        logger.info(
            "Delete %s %r (%s)", entity.kind, entity.metadata.name, entity.metadata.uid
        )
    else:
        await session(request).put(entity)
        logger.info(
            "Update %s %r (%s)", entity.kind, entity.metadata.name, entity.metadata.uid
        )

    return web.json_response(entity.serialize())


async def delete_resource_async(
    request: ApiObject, entity: ApiObject, force: bool = False
) -> web.Response:
    """Delete an entity.

    Args:
        request(ApiObject): The http request
        entity(ApiObject): The entity to delete
        force(bool): Flag to specify wether the resource should be force deleted
            (optional). default=False

    Returns:
        json response containing the deleted resource
    """
    if force:
        await session(request).delete(entity)
        logger.info(
            "Force deleting %s %r (%s)",
            f"{type(entity)}",  # TODO check this
            entity.metadata.name,
            entity.metadata.uid,
        )
        entity.metadata.deleted = utils.now()
        return web.json_response(entity.serialize())

    # Resource is already deleting
    if entity.metadata.deleted:
        return web.json_response(entity.serialize())

    # TODO: Should be update "modified" here?
    # Resource marked as deletion, to be deleted by the Garbage Collector
    entity.metadata.deleted = utils.now()
    entity.metadata.finalizers.append("cascade_deletion")

    await session(request).put(entity)
    logger.info(
        "Deleting %s %r (%s)", entity.kind, entity.metadata.name, entity.metadata.uid
    )

    return web.json_response(entity.serialize())


def initialize_subresource_fields(body: ApiObject) -> ApiObject:
    """Initialize subresource fields of resource.

    Args:
        body: defines the resource

    Returns:
        body: the resource after subresource initialization
    """
    for field in dataclasses.fields(body):
        if field.metadata.get("subresource", False):
            value = field.type()
            setattr(body, field.name, value)
    return body


async def must_create_resource_async(
    request: web.Request, body: ApiObject, namespace: str
) -> web.Response:
    """Create the resource defined by body or raises if it already exists.

    Args:
        request: the http request
        body: defines the resource to create
        namespace: str or None if global resource

    Returns:
        json response containing the created resource

    Raises:
        HttpProblemError: if the requested resource is already defined
    """
    now = utils.now()

    body.metadata.uid = str(uuid4())
    body.metadata.created = now
    body.metadata.modified = now

    if namespace:
        body.metadata.namespace = namespace

    try:
        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)", body.kind, body.metadata.name, body.metadata.uid
        )
    except TransactionError:
        message = f"""
            {body.kind} {body.metadata.name!r} already exists
            {"in namespace " + namespace + "." if namespace else "."}
        """
        problem = HttpProblem(
            detail=message, title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
        )
        raise HttpProblemError(web.HTTPConflict, problem)

    return web.json_response(body.serialize())
