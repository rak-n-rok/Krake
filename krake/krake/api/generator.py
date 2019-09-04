"""This module provides a decorator for generating default REST API handlers
for a given API definition (see :mod:`krake.apidefs`).
"""
import logging
import dataclasses
import json
from functools import partial
from datetime import datetime
from uuid import uuid4
from aiohttp import web
from webargs.aiohttpparser import use_kwargs

from krake.data.serializable import readonly_fields
from krake.data.core import WatchEvent, WatchEventType, ListMetadata
from ..utils import camel_to_snake_case, get_field
from .helpers import load, session, Heartbeat, use_schema
from .auth import protected
from .database import EventType


def generate_api(apidef):
    """Decorator function for generating standard API handlers.

    The decorator generates default aiohttp handlers based on the operations
    and subresources of the passed API definition. All default methods can be
    overwritten by defining methods with the same name. The methods will not
    be used as methods but as "static" functions. Hence, there is no ``self``
    argument.

    The methods will generated for every resource in the API definition and
    will be named according to the following schema:

    +-----------+-------------------------------+
    | Operation | Method                        |
    +===========+===============================+
    | Create    | create_{snake cased singular} |
    +-----------+-------------------------------+
    | List      | list_{snake cased plural}     |
    +-----------+-------------------------------+
    | ListAll   | list_all_{snake cased plural} |
    +-----------+-------------------------------+
    | Read      | read_{snake cased singular}   |
    +-----------+-------------------------------+
    | Update    | update_{snake cased singular} |
    +-----------+-------------------------------+
    | Delete    | delete_{snake cased singular} |
    +-----------+-------------------------------+

    Examples:
        .. code:: python

            from aiohttp import web

            from krake.apidefs.book import book
            from krake.data.book import Book
            from krake.api.generator import generate_api
            from krake.api.auth import protected
            from krake.api.helpers import load

            @generate_api(book)
            class BookApi:

                # Custom implementation
                @protected(api="book", resource="books", verb="get")
                @load("book", Book)
                def read_book(request, book):
                    return web.json_response(book.serialize())

        The API objects are used together with a client:

        .. code:: python

            from krake.client import Client

            with Client(url="http://localhost:8080") as client:
                book_api = BookApi(client)

    Args:
        apidef (krake.apidefs.ApiDef): API definition

    Returns:
        callable: Decorator generating default API handlers

    """

    def decorator(cls):
        if not hasattr(cls, "logger"):
            cls.logger = logging.getLogger(f"krake.api.{apidef.name}")

        if not hasattr(cls, "routes"):
            cls.routes = web.RouteTableDef()

        for resource in apidef.resources:
            _create_resource_handlers(cls, resource, cls.routes, cls.logger)

            for subresource in resource.subresources:
                _create_subresource_handlers(cls, subresource, cls.routes, cls.logger)

        return cls

    return decorator


def make_request_schema(cls, include=set()):
    """Create a :class:`marshmallow.Schema` excluding subresources.

    Args:
        cls (type): Data class with ``Schema`` attribute
        include (set, optional): Set of subresource attributes that
            should not be excluded.

    Returns:
        marshmallow.Schema: Schema instance with excluded subresources

    """
    exclude = readonly_fields(cls) | set(
        field.name
        for field in dataclasses.fields(cls)
        if field.metadata.get("subresource", False) and field.name not in include
    )

    return cls.Schema(exclude=exclude)


def copy_fields(source, destination):
    """Copy data class fields that are not marked as _subresource_, _readonly_
    or _immutable_ from the source object to the destination object.

    The function works recursive for nested data class attributes. If the
    nested target attribute is None, the attribute will be directly copied
    from the source object.

    Args:
        source: Data class instance from which attributes will be copied
        destination: Object to which attributes are copied

    """
    for field in dataclasses.fields(source):
        if (
            not field.metadata.get("subresource", False)
            and not field.metadata.get("readonly", False)
            and not field.metadata.get("immutable", False)
        ):
            value = getattr(source, field.name)

            if dataclasses.is_dataclass(value):
                # Source value is None, just set it directly
                if value is None:
                    setattr(destination, field.name, None)
                # Destination attribute is None, copy the whole attribute
                # FIXME: What about subresource/readonly/immutable
                elif getattr(destination, field.name) is None:
                    setattr(destination, field.name, value)
                # Update field by field
                else:
                    copy_fields(value, getattr(destination, field.name))
            else:
                setattr(destination, field.name, value)


def _generate_operation_func_name(operation):
    # Generate resource name based on the grammatical number
    if operation.number == "singular":
        resource_name = camel_to_snake_case(operation.resource.singular)
    else:
        resource_name = camel_to_snake_case(operation.resource.plural)

    opname = camel_to_snake_case(operation.name)

    if operation.subresource:
        subname = camel_to_snake_case(operation.subresource.name)
        return f"{opname}_{resource_name}_{subname}"

    return f"{opname}_{resource_name}"


def _create_resource_handlers(cls, resource, routes, logger):
    makers = {
        "Create": _make_create_handler,
        "List": _make_list_handler,
        "ListAll": partial(_make_list_handler, all=True),
        "Read": _make_read_handler,
        "Update": _make_update_handler,
        "Delete": _make_delete_handler,
    }

    for operation in resource.operations:
        func_name = _generate_operation_func_name(operation)

        handler = getattr(cls, func_name, None)
        if not handler:
            try:
                maker = makers[operation.name]
            except KeyError:
                raise NotImplementedError(
                    f"Generator for operation {operation.name!r} not implemented"
                )
            handler = maker(operation, logger)
            setattr(cls, func_name, handler)

        routes.route(operation.method, operation.path)(handler)


def _create_subresource_handlers(cls, subresource, routes, logger):
    makers = {"Update": _make_update_subresource_handler}

    for operation in subresource.operations:
        func_name = _generate_operation_func_name(operation)
        handler = getattr(cls, func_name, None)
        if not handler:
            try:
                maker = makers[operation.name]
            except KeyError:
                raise NotImplementedError(
                    f"Generator for subresource {operation.name!r} not implemented"
                )
            handler = maker(operation, logger)
            setattr(cls, func_name, handler)

        routes.route(operation.method, operation.path)(handler)


def _make_list_handler(operation, logger, all=False):
    # FIXME: Ugly assumptions ahead!
    entity_class, = get_field(operation.response, "items").type.__args__

    assert "heartbeat" in operation.query, "'heartbeat' query parameter is required"
    assert "watch" in operation.query, "'watch' query parameter is required"

    @protected(
        api=operation.resource.api,
        resource=operation.resource.plural.lower(),
        verb="list",
    )
    @use_kwargs(operation.query, locations=("query",))
    async def list_or_watch(request, heartbeat, watch, **query):
        if not all:
            namespace = request.match_info.get("namespace")
        else:
            namespace = None

        # Return the list of resources
        if not watch:
            if namespace is None:
                objs = [obj async for obj, _ in session(request).all(entity_class)]
            else:
                objs = [
                    obj
                    async for obj, _ in session(request).all(
                        entity_class, namespace=namespace
                    )
                ]

            body = operation.response(metadata=ListMetadata(), items=objs)
            return web.json_response(body.serialize())

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(entity_class, **kwargs) as watcher:
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
                        obj, _ = await session(request).get_by_key(
                            entity_class, key=rev.key, revision=rev.modified - 1
                        )

                    watch_event = WatchEvent(type=event_type, object=obj.serialize())

                    await resp.write(json.dumps(watch_event.serialize()).encode())
                    await resp.write(b"\n")

    return list_or_watch


def _make_read_handler(operation, logger):
    assert hasattr(operation.response, "__etcd_key__")

    @protected(
        api=operation.resource.api,
        resource=operation.resource.plural.lower(),
        verb="get",
    )
    @load("entity", operation.response)
    async def read(request, entity):
        return web.json_response(entity.serialize())

    return read


def _make_create_handler(operation, logger):
    assert hasattr(operation.body, "__etcd_key__")

    @protected(
        api=operation.resource.api,
        resource=operation.resource.plural.lower(),
        verb="create",
    )
    @use_schema("body", make_request_schema(operation.body))
    async def create(request, body):
        namespace = request.match_info.get("namespace")

        kwargs = {"name": body.metadata.name}
        if namespace:
            kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing, _ = await session(request).get(body.__class__, **kwargs)
        if existing is not None:
            if namespace:
                reason = (
                    f"{operation.resource.singular} {body.metadata.name!r} already "
                    f"exists in namespace {namespace!r}"
                )
            else:
                reason = (
                    f"{operation.resource.singular} {body.metadata.name!r} "
                    "already exists"
                )
            raise web.HTTPConflict(
                text=json.dumps({"reason": reason}), content_type="application/json"
            )

        now = datetime.now()

        body.metadata.namespace = namespace
        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        if (
            "cleanup" not in body.metadata.finalizers
            and hasattr(body, "cleanup")
            and body.cleanup
        ):
            # The created resource needs a Controller action to be cleaned
            body.metadata.finalizers.append("cleanup")

        # Initialize subresource fields
        for field in dataclasses.fields(body):
            if field.metadata.get("subresource", False):
                value = field.type()
                setattr(body, field.name, value)

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)",
            operation.resource.singular,
            body.metadata.name,
            body.metadata.uid,
        )

        return web.json_response(body.serialize())

    return create


def _make_update_handler(operation, logger):
    assert hasattr(operation.response, "__etcd_key__")

    @protected(
        api=operation.resource.api,
        resource=operation.resource.plural.lower(),
        verb="update",
    )
    @use_schema("body", make_request_schema(operation.body))
    @load("entity", operation.response)
    async def update(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                raise web.HTTPUnprocessableEntity(
                    body=json.dumps(
                        {
                            "metadata": {
                                "finalizers": [
                                    "Finalizers can only be removed if "
                                    "deletion is in progress."
                                ]
                            }
                        }
                    ),
                    content_type="application/json",
                )

        copy_fields(body, entity)

        entity.metadata.modified = datetime.now()

        await session(request).put(entity)
        logger.info(
            "Update %s %r (%s)",
            operation.resource.singular,
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    return update


def _make_delete_handler(operation, logger):
    assert hasattr(operation.response, "__etcd_key__")

    @protected(
        api=operation.resource.api,
        resource=operation.resource.plural.lower(),
        verb="delete",
    )
    @load("entity", operation.response)
    async def delete(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = datetime.now()

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)",
            operation.resource.singular,
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    return delete


def _make_update_subresource_handler(operation, logger):
    assert hasattr(operation.response, "__etcd_key__")

    resource_name = (
        f"{operation.subresource.resource.plural.lower()}/"
        f"{operation.subresource.name.lower()}"
    )
    attr_name = camel_to_snake_case(operation.subresource.name)

    @protected(
        api=operation.subresource.resource.api, resource=resource_name, verb="update"
    )
    @use_schema("body", make_request_schema(operation.body, include={attr_name}))
    @load("entity", operation.response)
    async def update_subresource(request, body, entity):
        source = getattr(body, attr_name)
        dest = getattr(entity, attr_name)

        copy_fields(source, dest)

        # TODO: Should we update "metadata.modified" here?
        # entity.metadata.modified = datetime.now()

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            operation.subresource.name,
            operation.subresource.resource.singular,
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    return update_subresource
