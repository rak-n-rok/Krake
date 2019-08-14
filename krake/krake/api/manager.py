import logging
import dataclasses
import json
from datetime import datetime
from uuid import uuid4
from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs

from krake.data.serializable import readonly_fields
from krake.data.core import WatchEvent, WatchEventType, ListMetadata
from ..utils import camel_to_snake_case
from .helpers import load, session, Heartbeat, use_schema
from .auth import protected
from .database import EventType


class ApiManager(object):
    def __init__(self, api):
        self.api = api
        self.logger = logging.getLogger(f"krake.api.{self.api.name}")
        self.resource_managers = [
            ResourceManager(self.api, resource, self.logger)
            for resource in self.api.resources
        ]
        for manager in self.resource_managers:
            setattr(self, camel_to_snake_case(manager.resource.plural), manager)

    @property
    def routes(self):
        for manager in self.resource_managers:
            yield from manager.routes


class BaseManager(object):
    def __init__(self):
        self._routes = {}

    def create(self, handler):
        assert hasattr(
            self.resource, "Create"
        ), "No 'Create' operation defined for this resource"
        return self.register_route(self.resource.Create, "create", handler)

    def read(self, handler):
        assert hasattr(
            self.resource, "Read"
        ), "No 'Read' operation defined for this resource"
        return self.register_route(self.resource.Read, "get", handler)

    def list(self, handler):
        assert hasattr(
            self.resource, "List"
        ), "No 'List' operation defined for this resource"
        return self.register_route(self.resource.List, "list", handler)

    def list_all(self, handler):
        assert hasattr(
            self.resource, "ListAll"
        ), "No 'ListAll' operation defined for this resource"
        return self.register_route(self.resource.ListAll, "list_all", handler)

    def update(self, handler):
        assert hasattr(
            self.resource, "Update"
        ), "No 'Update' operation defined for this resource"
        return self.register_route(self.resource.Update, "update", handler)

    def delete(self, handler):
        assert hasattr(
            self.resource, "Delete"
        ), "No 'Delete' operation defined for this resource"
        return self.register_route(self.resource.Delete, "delete", handler)

    def register_route(self, operation, verb, handler):
        raise NotImplementedError()


class ResourceManager(BaseManager):
    def __init__(self, api, resource, logger):
        super().__init__()
        self.api = api
        self.resource = resource
        self.logger = logger
        self.subresource_managers = []

        if hasattr(self.resource, "List"):
            handler = make_list_handler(self.resource, self.resource.List, self.logger)
            self.list(handler)
        if hasattr(self.resource, "ListAll"):
            handler = make_list_handler(
                self.resource, self.resource.ListAll, self.logger, all=True
            )
            self.list_all(handler)
        if hasattr(self.resource, "Read"):
            handler = make_read_handler(self.resource, self.resource.Read, self.logger)
            self.read(handler)
        if hasattr(self.resource, "Update"):
            handler = make_update_handler(
                self.resource, self.resource.Update, self.logger
            )
            self.update(handler)
        if hasattr(self.resource, "Create"):
            handler = make_create_handler(
                self.resource, self.resource.Create, self.logger
            )
            self.create(handler)
        if hasattr(self.resource, "Delete"):
            handler = make_delete_handler(
                self.resource, self.resource.Delete, self.logger
            )
            self.delete(handler)

        submanagers = {"Status": StatusSubresourceManager}

        self.subresource_managers = {
            name: submanagers.get(name, GenericSubresourceManager)(
                self.api, self.resource, sub, self.logger
            )
            for name, sub in self.resource.subresources.items()
        }
        for name, manager in self.subresource_managers.items():
            setattr(self, name.lower(), manager)

    def register_route(self, operation, verb, handler):
        protect = protected(
            api=self.api.name, resource=self.resource.plural.lower(), verb=verb
        )
        handler = protect(handler)
        self._routes[operation.method, operation.path] = web.RouteDef(
            method=operation.method, path=operation.path, handler=handler, kwargs={}
        )
        return handler

    @property
    def routes(self):
        yield from self._routes.values()
        for submanager in self.subresource_managers.values():
            yield from submanager.routes


class GenericSubresourceManager(BaseManager):
    def __init__(self, api, parent, resource, logger):
        super().__init__()
        self.api = api
        self.parent = parent
        self.resource = resource
        self.logger = logger

    @property
    def routes(self):
        yield from self._routes.values()

    def register_route(self, operation, verb, handler):
        resource_name = f"{self.parent.plural.lower()}/{self.resource.__name__.lower()}"
        protect = protected(api=self.api.name, resource=resource_name, verb=verb)
        handler = protect(handler)
        self._routes[operation.method, operation.path] = web.RouteDef(
            method=operation.method, path=operation.path, handler=handler, kwargs={}
        )
        return handler


class StatusSubresourceManager(GenericSubresourceManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        handler = make_update_status_handler(
            self.parent, self.resource, self.resource.Update, self.logger
        )
        self.update(handler)


def make_list_handler(resource, operation, logger, all=False):
    # FIXME: Ugly assumptions ahead!
    entity_class, = get_field(operation.response, "items").type.__args__

    @use_kwargs({"heartbeat": fields.Integer(missing=None, locations=["query"])})
    async def list_or_watch(request, heartbeat):
        if not all:
            namespace = request.match_info.get("namespace")
        else:
            namespace = None

        if "watch" not in request.query:
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


def make_read_handler(resource, operation, logger):
    assert hasattr(operation.response, "__etcd_key__")

    @load("entity", operation.response)
    async def read(request, entity):
        return web.json_response(entity.serialize())

    return read


def make_create_handler(resource, operation, logger):
    assert hasattr(operation.body, "__etcd_key__")

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
                    f"{resource.singular} {body.metadata.name!r} already "
                    f"exists in namespace {namespace!r}"
                )
            else:
                reason = f"{resource.singular} {body.metadata.name!r} already exists"
            raise web.HTTPConflict(
                text=json.dumps({"reason": reason}), content_type="application/json"
            )

        now = datetime.now()

        body.metadata.namespace = namespace
        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        # Initialize subresource fields
        for field in dataclasses.fields(body):
            if field.metadata.get("subresource", False):
                value = field.type()
                setattr(body, field.name, value)

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)",
            resource.singular,
            body.metadata.name,
            body.metadata.uid,
        )

        return web.json_response(body.serialize())

    return create


def make_update_handler(resource, operation, logger):
    assert hasattr(operation.response, "__etcd_key__")

    @use_schema("body", make_request_schema(operation.body))
    @load("entity", operation.response)
    async def update(request, body, entity):
        copy_fields(body, entity)

        entity.metadata.modified = datetime.now()

        await session(request).put(entity)
        logger.info(
            "Update %s %r (%s)",
            resource.singular,
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    return update


def make_delete_handler(resource, operation, logger):
    assert hasattr(operation.response, "__etcd_key__")

    @load("entity", operation.response)
    async def delete(request, entity):
        if entity.metadata.deleted:
            raise web.HTTPConflict(
                text=json.dumps({"reason": "Resource already deleting"}),
                content_type="application/json",
            )

        # No finializers registered. Delete resource immediately
        if not entity.metadata.finializers:
            await session(request).delete(entity)
            logger.info(
                "Deleted %s %r (%s)",
                resource.singular,
                entity.metadata.name,
                entity.metadata.uid,
            )
            return web.Response(status=204)

        # TODO: Should be update "modified" here?
        entity.metadata.deleted = datetime.now()

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)",
            resource.singular,
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    return delete


def make_update_status_handler(resource, subresource, operation, logger):
    subname = f"{resource.plural.lower()}/{subresource.__name__.lower()}"

    @use_schema("body", make_request_schema(operation.body, subresources={"status"}))
    @load("entity", operation.response)
    async def update_status(request, body, entity):
        # TODO: Update "metadata.modified" here?
        entity.status = body.status

        await session(request).put(entity)
        logger.info(
            "Update %s %r (%s)", subname, entity.metadata.name, entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    return update_status


def get_field(cls, name):
    for f in dataclasses.fields(cls):
        if f.name == name:
            return f

    raise AttributeError(f"{cls} does not have field {name!r}")


def copy_fields(source, destination):
    for field in dataclasses.fields(source):
        if (
            not field.metadata.get("subresource", False)
            and not field.metadata.get("readonly", False)
            and not field.metadata.get("immutable", False)
        ):
            value = getattr(source, field.name)

            if dataclasses.is_dataclass(value):
                copy_fields(value, getattr(destination, field.name))
            else:
                setattr(destination, field.name, value)


def make_request_schema(cls, subresources=set()):
    exclude = readonly_fields(cls) | set(
        field.name
        for field in dataclasses.fields(cls)
        if field.metadata.get("subresource", False) and field.name not in subresources
    )

    return cls.Schema(exclude=exclude, strict=True)


def _find_excluded_fields(cls, exclude, subresources, prefix=None):
    for field in dataclasses.fields(cls):
        if field.metadata.get("readonly", False) or (
            field.name not in subresources and field.metadata.get("subresource", False)
        ):
            if prefix is None:
                name = field.name
            else:
                name = f"{prefix}.{field.name}"
            exclude.add(name)
        elif dataclasses.is_dataclass(field.type):
            if prefix is None:
                nested = field.name
            else:
                nested = f"{prefix}.{field.name}"
            _find_excluded_fields(field.type, exclude, subresources, nested)
    return exclude


def _make_schema(resource):
    schema = {}

    for f in dataclasses.fields(resource.definition):
        if f.name not in resource.subresources:
            schema[f.name] = fields.Nested(make_request_schema(f.type), required=True)

    return schema
