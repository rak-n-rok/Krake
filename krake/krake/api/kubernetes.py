import dataclasses
import json
import logging
from aiohttp import web
from uuid import uuid4
from webargs.aiohttpparser import use_kwargs

from krake import utils
from krake.api.auth import protected
from krake.api.database import EventType
from krake.api.helpers import (
    load,
    session,
    Heartbeat,
    use_schema,
    HttpReason,
    HttpReasonCode,
    make_create_request_schema,
    json_error,
    ListQuery,
)
from krake.data.core import WatchEvent, WatchEventType, ListMetadata
from krake.data.kubernetes import Application, ApplicationList, Cluster, ClusterList

logger = logging.getLogger(__name__)


class KubernetesApi(object):
    """Contains all handlers for the resources of the "kubernetes" API.
    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    @routes.route("POST", "/kubernetes/namespaces/{namespace}/applications")
    @protected(api="kubernetes", resource="applications", verb="create")
    @use_schema("body", schema=make_create_request_schema(Application))
    async def create_application(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            message = (
                f"Application {body.metadata.name!r} already "
                f"exists in namespace {namespace!r}"
            )
            reason = HttpReason(
                reason=message, code=HttpReasonCode.RESOURCE_ALREADY_EXISTS
            )
            raise json_error(web.HTTPConflict, reason.serialize())

        now = utils.now()

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
            "Created %s %r (%s)", "Application", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route("DELETE", "/kubernetes/namespaces/{namespace}/applications/{name}")
    @protected(api="kubernetes", resource="applications", verb="delete")
    @load("entity", Application)
    async def delete_application(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)",
            "Application",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/kubernetes/applications")
    @routes.route("GET", "/kubernetes/namespaces/{namespace}/applications")
    @protected(api="kubernetes", resource="applications", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_applications(request, heartbeat, watch, **query):
        resource_class = Application

        # If the ListAll operation
        namespace = request.match_info.get("namespace", None)

        # Return the list of resources
        if not watch:
            if namespace is None:
                objs = [obj async for obj in session(request).all(resource_class)]
            else:
                objs = [
                    obj
                    async for obj in session(request).all(
                        resource_class, namespace=namespace
                    )
                ]

            body = ApplicationList(metadata=ListMetadata(), items=objs)
            return web.json_response(body.serialize())

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
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

    @routes.route("GET", "/kubernetes/namespaces/{namespace}/applications/{name}")
    @protected(api="kubernetes", resource="applications", verb="get")
    @load("entity", Application)
    async def read_application(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/applications/{name}")
    @protected(api="kubernetes", resource="applications", verb="update")
    @use_schema("body", schema=Application.Schema)
    @load("entity", Application)
    async def update_application(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                raise json_error(
                    web.HTTPConflict,
                    {
                        "metadata": {
                            "finalizers": [
                                "Finalizers can only be removed if "
                                "deletion is in progress."
                            ]
                        }
                    },
                )

        # FIXME: if a user updates an immutable field, (such as the created timestamp),
        #  the request is accepted and the API returns 200. The `modified` timestamp
        #  will also still be updated, even though no change from the request on
        #  immutable fields will be applied.
        #  Changes to immutable fields should be rejected, see Krake issue #410
        if body == entity:
            raise json_error(web.HTTPBadRequest, "The body contained no update.")

        entity.update(body)
        entity.metadata.modified = utils.now()

        # Resource is in "deletion in progress" state and all finalizers have
        # been removed. Delete the resource from database.
        if entity.metadata.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)",
                "Application",
                entity.metadata.name,
                entity.metadata.uid,
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)",
                "Application",
                entity.metadata.name,
                entity.metadata.uid,
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/binding"
    )
    @protected(api="kubernetes", resource="applications/binding", verb="update")
    @use_schema("body", ClusterBinding.Schema)
    @load("entity", Application)
    async def update_application_binding(request, body, entity):
        source = getattr(body, "binding")
        dest = getattr(entity, "binding")

        dest.update(source)

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            "Binding",
            "Application",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/complete"
    )
    @protected(api="kubernetes", resource="applications/complete", verb="update")
    @use_schema("body", ApplicationComplete.Schema)
    @load("entity", Application)
    async def update_application_complete(request, body, entity):
        source = getattr(body, "complete")
        dest = getattr(entity, "complete")

        dest.update(source)

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            "Complete",
            "Application",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/status"
    )
    @protected(api="kubernetes", resource="applications/status", verb="update")
    @use_schema("body", Application.Schema)
    @load("entity", Application)
    async def update_application_status(request, body, entity):
        source = getattr(body, "status")
        dest = getattr(entity, "status")

        dest.update(source)

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            "Status",
            "Application",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("POST", "/kubernetes/namespaces/{namespace}/clusters")
    @protected(api="kubernetes", resource="clusters", verb="create")
    @use_schema("body", schema=make_create_request_schema(Cluster))
    async def create_cluster(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            message = (
                f"Cluster {body.metadata.name!r} already "
                f"exists in namespace {namespace!r}"
            )
            reason = HttpReason(
                reason=message, code=HttpReasonCode.RESOURCE_ALREADY_EXISTS
            )
            raise json_error(web.HTTPConflict, reason.serialize())

        now = utils.now()

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
            "Created %s %r (%s)", "Cluster", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route("DELETE", "/kubernetes/namespaces/{namespace}/clusters/{name}")
    @protected(api="kubernetes", resource="clusters", verb="delete")
    @load("entity", Cluster)
    async def delete_cluster(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "Cluster", entity.metadata.name, entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/kubernetes/clusters")
    @routes.route("GET", "/kubernetes/namespaces/{namespace}/clusters")
    @protected(api="kubernetes", resource="clusters", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_clusters(request, heartbeat, watch, **query):
        resource_class = Cluster

        # If the ListAll operation
        namespace = request.match_info.get("namespace", None)

        # Return the list of resources
        if not watch:
            if namespace is None:
                objs = [obj async for obj in session(request).all(resource_class)]
            else:
                objs = [
                    obj
                    async for obj in session(request).all(
                        resource_class, namespace=namespace
                    )
                ]

            body = ClusterList(metadata=ListMetadata(), items=objs)
            return web.json_response(body.serialize())

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
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

    @routes.route("GET", "/kubernetes/namespaces/{namespace}/clusters/{name}")
    @protected(api="kubernetes", resource="clusters", verb="get")
    @load("entity", Cluster)
    async def read_cluster(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/clusters/{name}")
    @protected(api="kubernetes", resource="clusters", verb="update")
    @use_schema("body", schema=Cluster.Schema)
    @load("entity", Cluster)
    async def update_cluster(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                raise json_error(
                    web.HTTPConflict,
                    {
                        "metadata": {
                            "finalizers": [
                                "Finalizers can only be removed if "
                                "deletion is in progress."
                            ]
                        }
                    },
                )

        # FIXME: if a user updates an immutable field, (such as the created timestamp),
        #  the request is accepted and the API returns 200. The `modified` timestamp
        #  will also still be updated, even though no change from the request on
        #  immutable fields will be applied.
        #  Changes to immutable fields should be rejected, see Krake issue #410
        if body == entity:
            raise json_error(web.HTTPBadRequest, "The body contained no update.")

        entity.update(body)
        entity.metadata.modified = utils.now()

        # Resource is in "deletion in progress" state and all finalizers have
        # been removed. Delete the resource from database.
        if entity.metadata.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)",
                "Cluster",
                entity.metadata.name,
                entity.metadata.uid,
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)",
                "Cluster",
                entity.metadata.name,
                entity.metadata.uid,
            )

        return web.json_response(entity.serialize())

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/clusters/{name}/status")
    @protected(api="kubernetes", resource="clusters/status", verb="update")
    @use_schema("body", Cluster.Schema)
    @load("entity", Cluster)
    async def update_cluster_status(request, body, entity):
        source = getattr(body, "status")
        dest = getattr(entity, "status")

        dest.update(source)

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            "Status",
            "Cluster",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

