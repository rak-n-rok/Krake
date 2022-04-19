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
    HttpProblem,
    HttpProblemTitle,
    make_create_request_schema,
    HttpProblemError,
    ListQuery,
)
from krake.data.core import WatchEvent, WatchEventType, ListMetadata
from krake.data.core import (
    GlobalMetric,
    GlobalMetricList,
    GlobalMetricsProvider,
    GlobalMetricsProviderList,
    Metric,
    MetricList,
    MetricsProvider,
    MetricsProviderList,
    Role,
    RoleBinding,
    RoleBindingList,
    RoleList
)

logger = logging.getLogger(__name__)


class CoreApi(object):
    """Contains all handlers for the resources of the "core" API.
    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    @routes.route(
        "POST", "/core/globalmetrics"
    )
    @protected(
        api="core", resource="globalmetrics", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(GlobalMetric)
    )
    async def create_global_metric(request, body):
        kwargs = {"name": body.metadata.name}

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=f"GlobalMetric {body.metadata.name!r} already exists",
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)", "GlobalMetric", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route(
        "DELETE", "/core/globalmetrics/{name}"
    )
    @protected(
        api="core", resource="globalmetrics", verb="delete"
    )
    @load("entity", GlobalMetric)
    async def delete_global_metric(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "GlobalMetric", entity.metadata.name,
            entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "GET", "/core/globalmetrics"
    )
    @protected(
        api="core", resource="globalmetrics", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_metrics(request, heartbeat, watch, **query):
        resource_class = GlobalMetric

        # Return the list of resources
        if not watch:
            objs = [obj async for obj in session(request).all(resource_class)]

            body = GlobalMetricList(
                metadata=ListMetadata(), items=objs
            )
            return web.json_response(body.serialize())

        # Watching resources
        kwargs = {}

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

    @routes.route(
        "GET", "/core/globalmetrics/{name}"
    )
    @protected(
        api="core", resource="globalmetrics", verb="get"
    )
    @load("entity", GlobalMetric)
    async def read_global_metric(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/globalmetrics/{name}"
    )
    @protected(
        api="core", resource="globalmetrics", verb="update"
    )
    @use_schema(
        "body", schema=GlobalMetric.Schema
    )
    @load("entity", GlobalMetric)
    async def update_global_metric(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                           " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR
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
                "Delete %s %r (%s)", "GlobalMetric", entity.metadata.name,
                entity.metadata.uid
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)", "GlobalMetric", entity.metadata.name,
                entity.metadata.uid
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "POST", "/core/globalmetricsproviders"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(GlobalMetricsProvider)
    )
    async def create_global_metrics_provider(request, body):
        kwargs = {"name": body.metadata.name}

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=f"GlobalMetricsProvider {body.metadata.name!r} already exists",
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)", "GlobalMetricsProvider", body.metadata.name,
            body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route(
        "DELETE", "/core/globalmetricsproviders/{name}"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="delete"
    )
    @load("entity", GlobalMetricsProvider)
    async def delete_global_metrics_provider(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "GlobalMetricsProvider", entity.metadata.name,
            entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "GET", "/core/globalmetricsproviders"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_metrics_providers(request, heartbeat, watch,
                                                     **query):
        resource_class = GlobalMetricsProvider

        # Return the list of resources
        if not watch:
            objs = [obj async for obj in session(request).all(resource_class)]

            body = GlobalMetricsProviderList(
                metadata=ListMetadata(), items=objs
            )
            return web.json_response(body.serialize())

        # Watching resources
        kwargs = {}

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

    @routes.route(
        "GET", "/core/globalmetricsproviders/{name}"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="get"
    )
    @load("entity", GlobalMetricsProvider)
    async def read_global_metrics_provider(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/globalmetricsproviders/{name}"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="update"
    )
    @use_schema(
        "body", schema=GlobalMetricsProvider.Schema
    )
    @load("entity", GlobalMetricsProvider)
    async def update_global_metrics_provider(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                           " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR
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
                "Delete %s %r (%s)", "GlobalMetricsProvider", entity.metadata.name,
                entity.metadata.uid
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)", "GlobalMetricsProvider", entity.metadata.name,
                entity.metadata.uid
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "POST", "/core/roles"
    )
    @protected(
        api="core", resource="roles", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(Role)
    )
    async def create_role(request, body):
        kwargs = {"name": body.metadata.name}

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=f"Role {body.metadata.name!r} already exists",
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)", "Role", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route(
        "DELETE", "/core/roles/{name}"
    )
    @protected(
        api="core", resource="roles", verb="delete"
    )
    @load("entity", Role)
    async def delete_role(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "Role", entity.metadata.name, entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "GET", "/core/roles"
    )
    @protected(
        api="core", resource="roles", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_roles(request, heartbeat, watch, **query):
        resource_class = Role

        # Return the list of resources
        if not watch:
            objs = [obj async for obj in session(request).all(resource_class)]

            body = RoleList(
                metadata=ListMetadata(), items=objs
            )
            return web.json_response(body.serialize())

        # Watching resources
        kwargs = {}

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

    @routes.route(
        "GET", "/core/roles/{name}"
    )
    @protected(
        api="core", resource="roles", verb="get"
    )
    @load("entity", Role)
    async def read_role(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/roles/{name}"
    )
    @protected(
        api="core", resource="roles", verb="update"
    )
    @use_schema(
        "body", schema=Role.Schema
    )
    @load("entity", Role)
    async def update_role(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                           " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR
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
                "Delete %s %r (%s)", "Role", entity.metadata.name, entity.metadata.uid
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)", "Role", entity.metadata.name, entity.metadata.uid
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "POST", "/core/rolebindings"
    )
    @protected(
        api="core", resource="rolebindings", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(RoleBinding)
    )
    async def create_role_binding(request, body):
        kwargs = {"name": body.metadata.name}

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=f"RoleBinding {body.metadata.name!r} already exists",
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)", "RoleBinding", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route(
        "DELETE", "/core/rolebindings/{name}"
    )
    @protected(
        api="core", resource="rolebindings", verb="delete"
    )
    @load("entity", RoleBinding)
    async def delete_role_binding(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "RoleBinding", entity.metadata.name,
            entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "GET", "/core/rolebindings"
    )
    @protected(
        api="core", resource="rolebindings", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_role_bindings(request, heartbeat, watch, **query):
        resource_class = RoleBinding

        # Return the list of resources
        if not watch:
            objs = [obj async for obj in session(request).all(resource_class)]

            body = RoleBindingList(
                metadata=ListMetadata(), items=objs
            )
            return web.json_response(body.serialize())

        # Watching resources
        kwargs = {}

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

    @routes.route(
        "GET", "/core/rolebindings/{name}"
    )
    @protected(
        api="core", resource="rolebindings", verb="get"
    )
    @load("entity", RoleBinding)
    async def read_role_binding(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/rolebindings/{name}"
    )
    @protected(
        api="core", resource="rolebindings", verb="update"
    )
    @use_schema(
        "body", schema=RoleBinding.Schema
    )
    @load("entity", RoleBinding)
    async def update_role_binding(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                           " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR
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
                "Delete %s %r (%s)", "RoleBinding", entity.metadata.name,
                entity.metadata.uid
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)", "RoleBinding", entity.metadata.name,
                entity.metadata.uid
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "POST", "/core/namespaces/{namespace}/metrics"
    )
    @protected(
        api="core", resource="metrics", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(Metric)
    )
    async def create_metric(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            message = (
                f"Metric {body.metadata.name!r} already "
                f"exists in namespace {namespace!r}"
            )
            problem = HttpProblem(
                detail=message, title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.namespace = namespace
        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)", "Metric", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route(
        "DELETE", "/core/namespaces/{namespace}/metrics/{name}"
    )
    @protected(
        api="core", resource="metrics", verb="delete"
    )
    @load("entity", Metric)
    async def delete_metric(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "Metric", entity.metadata.name, entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "GET", "/core/metrics"
    )
    @routes.route(
        "GET", "/core/namespaces/{namespace}/metrics"
    )
    @protected(
        api="core", resource="metrics", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_metrics(request, heartbeat, watch, **query):
        resource_class = Metric

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

            body = MetricList(
                metadata=ListMetadata(), items=objs
            )
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

    @routes.route(
        "GET", "/core/namespaces/{namespace}/metrics/{name}"
    )
    @protected(
        api="core", resource="metrics", verb="get"
    )
    @load("entity", Metric)
    async def read_metric(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/namespaces/{namespace}/metrics/{name}"
    )
    @protected(
        api="core", resource="metrics", verb="update"
    )
    @use_schema(
        "body", schema=Metric.Schema
    )
    @load("entity", Metric)
    async def update_metric(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                           " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR
            )
            raise HttpProblemError(web.HTTPBadRequest, problem)

        try:
            entity.update(body)
        except ValueError as e:
            problem = HttpProblem(
                detail=str(e), title=HttpProblemTitle.UPDATE_ERROR
            )
            raise HttpProblemError(web.HTTPBadRequest, problem)

        entity.metadata.modified = utils.now()

        # Resource is in "deletion in progress" state and all finalizers have
        # been removed. Delete the resource from database.
        if entity.metadata.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)", "Metric", entity.metadata.name, entity.metadata.uid
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)", "Metric", entity.metadata.name, entity.metadata.uid
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "POST", "/core/namespaces/{namespace}/metricsproviders"
    )
    @protected(
        api="core", resource="metricsproviders", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(MetricsProvider)
    )
    async def create_metrics_provider(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            message = (
                f"MetricsProvider {body.metadata.name!r} already "
                f"exists in namespace {namespace!r}"
            )
            problem = HttpProblem(
                detail=message, title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.namespace = namespace
        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)", "MetricsProvider", body.metadata.name,
            body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route(
        "DELETE", "/core/namespaces/{namespace}/metricsproviders/{name}"
    )
    @protected(
        api="core", resource="metricsproviders", verb="delete"
    )
    @load("entity", MetricsProvider)
    async def delete_metrics_provider(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "MetricsProvider", entity.metadata.name,
            entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route(
        "GET", "/core/metricsproviders"
    )
    @routes.route(
        "GET", "/core/namespaces/{namespace}/metricsproviders"
    )
    @protected(
        api="core", resource="metricsproviders", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_metrics_providers(request, heartbeat, watch, **query):
        resource_class = MetricsProvider

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

            body = MetricsProviderList(
                metadata=ListMetadata(), items=objs
            )
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

    @routes.route(
        "GET", "/core/namespaces/{namespace}/metricsproviders/{name}"
    )
    @protected(
        api="core", resource="metricsproviders", verb="get"
    )
    @load("entity", MetricsProvider)
    async def read_metrics_provider(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/namespaces/{namespace}/metricsproviders/{name}"
    )
    @protected(
        api="core", resource="metricsproviders", verb="update"
    )
    @use_schema(
        "body", schema=MetricsProvider.Schema
    )
    @load("entity", MetricsProvider)
    async def update_metrics_provider(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                           " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR
            )
            raise HttpProblemError(web.HTTPBadRequest, problem)

        try:
            entity.update(body)
        except ValueError as e:
            problem = HttpProblem(
                detail=str(e), title=HttpProblemTitle.UPDATE_ERROR
            )
            raise HttpProblemError(web.HTTPBadRequest, problem)

        entity.metadata.modified = utils.now()

        # Resource is in "deletion in progress" state and all finalizers have
        # been removed. Delete the resource from database.
        if entity.metadata.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)", "MetricsProvider", entity.metadata.name,
                entity.metadata.uid
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)", "MetricsProvider", entity.metadata.name,
                entity.metadata.uid
            )

        return web.json_response(entity.serialize())
