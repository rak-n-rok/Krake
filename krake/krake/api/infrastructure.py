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
    HttpProblem,
    HttpProblemTitle,
    make_create_request_schema,
    HttpProblemError,
    ListQuery,
)
from krake.data.core import WatchEvent, WatchEventType, DeletionState

from krake.data.infrastructure import (
    Cloud,
    CloudList,
    GlobalCloud,
    GlobalCloudList,
    GlobalInfrastructureProvider,
    GlobalInfrastructureProviderList,
    InfrastructureProvider,
    InfrastructureProviderList,
)

logger = logging.getLogger("krake.api.infrastructure")


class InfrastructureApi(object):
    """Contains all handlers for the resources of the "infrastructure" API.
    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    @routes.route("POST", "/infrastructure/globalinfrastructureproviders")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="create"
    )
    @use_schema("body", schema=make_create_request_schema(GlobalInfrastructureProvider))
    async def create_global_infrastructure_provider(request, body):
        kwargs = {"name": body.metadata.name}

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=f"GlobalInfrastructureProvider {body.metadata.name!r} "
                "already exists",
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS,
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)",
            "GlobalInfrastructureProvider",
            body.metadata.name,
            body.metadata.uid,
        )

        return web.json_response(body.serialize())

    @routes.route("DELETE", "/infrastructure/globalinfrastructureproviders/{name}")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="delete"
    )
    @load("entity", GlobalInfrastructureProvider)
    async def delete_global_infrastructure_provider(request, entity):
        # Resource is already deleting
        if entity.metadata.deletion_state.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deletion_state = DeletionState.create_deleted()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)",
            "GlobalInfrastructureProvider",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/infrastructure/globalinfrastructureproviders")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_infrastructure_providers(
        request, heartbeat, watch, **query
    ):
        resource_class = GlobalInfrastructureProvider

        # Return the list of resources
        if not watch:
            objs = [obj async for obj in session(request).all(resource_class)]

            body = GlobalInfrastructureProviderList(items=objs)
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

    @routes.route("GET", "/infrastructure/globalinfrastructureproviders/{name}")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="get"
    )
    @load("entity", GlobalInfrastructureProvider)
    async def read_global_infrastructure_provider(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/infrastructure/globalinfrastructureproviders/{name}")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="update"
    )
    @use_schema("body", schema=GlobalInfrastructureProvider.Schema)
    @load("entity", GlobalInfrastructureProvider)
    async def update_global_infrastructure_provider(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deletion_state.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                    " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR,
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR,
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
        if entity.metadata.deletion_state.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)",
                "GlobalInfrastructureProvider",
                entity.metadata.name,
                entity.metadata.uid,
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)",
                "GlobalInfrastructureProvider",
                entity.metadata.name,
                entity.metadata.uid,
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "POST", "/infrastructure/namespaces/{namespace}/infrastructureproviders"
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="create")
    @use_schema("body", schema=make_create_request_schema(InfrastructureProvider))
    async def create_infrastructure_provider(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=(
                    f"InfrastructureProvider {body.metadata.name!r} already "
                    f"exists in namespace {namespace!r}"
                ),
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS,
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

        body.metadata.namespace = namespace
        body.metadata.uid = str(uuid4())
        body.metadata.created = now
        body.metadata.modified = now

        await session(request).put(body)
        logger.info(
            "Created %s %r (%s)",
            "InfrastructureProvider",
            body.metadata.name,
            body.metadata.uid,
        )

        return web.json_response(body.serialize())

    @routes.route(
        "DELETE",
        "/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}",
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="delete")
    @load("entity", InfrastructureProvider)
    async def delete_infrastructure_provider(request, entity):
        # Resource is already deleting
        if entity.metadata.deletion_state.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deletion_state = DeletionState.create_deleted()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)",
            "InfrastructureProvider",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/infrastructure/infrastructureproviders")
    @routes.route(
        "GET", "/infrastructure/namespaces/{namespace}/infrastructureproviders"
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_infrastructure_providers(
        request, heartbeat, watch, **query
    ):
        resource_class = InfrastructureProvider

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

            body = InfrastructureProviderList(items=objs)
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
        "GET", "/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}"
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="get")
    @load("entity", InfrastructureProvider)
    async def read_infrastructure_provider(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}"
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="update")
    @use_schema("body", schema=InfrastructureProvider.Schema)
    @load("entity", InfrastructureProvider)
    async def update_infrastructure_provider(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deletion_state.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                    " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR,
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR,
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
        if entity.metadata.deletion_state.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)",
                "InfrastructureProvider",
                entity.metadata.name,
                entity.metadata.uid,
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)",
                "InfrastructureProvider",
                entity.metadata.name,
                entity.metadata.uid,
            )

        return web.json_response(entity.serialize())

    @routes.route("POST", "/infrastructure/globalclouds")
    @protected(api="infrastructure", resource="globalclouds", verb="create")
    @use_schema("body", schema=make_create_request_schema(GlobalCloud))
    async def create_global_cloud(request, body):
        kwargs = {"name": body.metadata.name}

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=f"GlobalCloud {body.metadata.name!r} already exists",
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS,
            )
            raise HttpProblemError(web.HTTPConflict, problem)

        now = utils.now()

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
            "Created %s %r (%s)", "GlobalCloud", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route("DELETE", "/infrastructure/globalclouds/{name}")
    @protected(api="infrastructure", resource="globalclouds", verb="delete")
    @load("entity", GlobalCloud)
    async def delete_global_cloud(request, entity):
        # Resource is already deleting
        if entity.metadata.deletion_state.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deletion_state = DeletionState.create_deleted()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)",
            "GlobalCloud",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/infrastructure/globalclouds")
    @protected(api="infrastructure", resource="globalclouds", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_clouds(request, heartbeat, watch, **query):
        resource_class = GlobalCloud

        # Return the list of resources
        if not watch:
            objs = [obj async for obj in session(request).all(resource_class)]

            body = GlobalCloudList(items=objs)
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

    @routes.route("GET", "/infrastructure/globalclouds/{name}")
    @protected(api="infrastructure", resource="globalclouds", verb="get")
    @load("entity", GlobalCloud)
    async def read_global_cloud(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/infrastructure/globalclouds/{name}")
    @protected(api="infrastructure", resource="globalclouds", verb="update")
    @use_schema("body", schema=GlobalCloud.Schema)
    @load("entity", GlobalCloud)
    async def update_global_cloud(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deletion_state.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                    " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR,
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR,
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
        if entity.metadata.deletion_state.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)",
                "GlobalCloud",
                entity.metadata.name,
                entity.metadata.uid,
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)",
                "GlobalCloud",
                entity.metadata.name,
                entity.metadata.uid,
            )

        return web.json_response(entity.serialize())

    @routes.route("PUT", "/infrastructure/globalclouds/{name}/status")
    @protected(api="infrastructure", resource="globalclouds/status", verb="update")
    @use_schema("body", GlobalCloud.Schema)
    @load("entity", GlobalCloud)
    async def update_global_cloud_status(request, body, entity):
        source = getattr(body, "status")
        dest = getattr(entity, "status")

        try:
            dest.update(source)
        except ValueError as e:
            problem = HttpProblem(detail=str(e), title=HttpProblemTitle.UPDATE_ERROR)
            raise HttpProblemError(web.HTTPBadRequest, problem)

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            "Status",
            "GlobalCloud",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("POST", "/infrastructure/namespaces/{namespace}/clouds")
    @protected(api="infrastructure", resource="clouds", verb="create")
    @use_schema("body", schema=make_create_request_schema(Cloud))
    async def create_cloud(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=(
                    f"Cloud {body.metadata.name!r} already "
                    f"exists in namespace {namespace!r}"
                ),
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS,
            )
            raise HttpProblemError(web.HTTPConflict, problem)

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
            "Created %s %r (%s)", "Cloud", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route("DELETE", "/infrastructure/namespaces/{namespace}/clouds/{name}")
    @protected(api="infrastructure", resource="clouds", verb="delete")
    @load("entity", Cloud)
    async def delete_cloud(request, entity):
        # Resource is already deleting
        if entity.metadata.deletion_state.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deletion_state = DeletionState.create_deleted()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "Cloud", entity.metadata.name, entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/infrastructure/clouds")
    @routes.route("GET", "/infrastructure/namespaces/{namespace}/clouds")
    @protected(api="infrastructure", resource="clouds", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_clouds(request, heartbeat, watch, **query):
        resource_class = Cloud

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

            body = CloudList(items=objs)
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

    @routes.route("GET", "/infrastructure/namespaces/{namespace}/clouds/{name}")
    @protected(api="infrastructure", resource="clouds", verb="get")
    @load("entity", Cloud)
    async def read_cloud(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/infrastructure/namespaces/{namespace}/clouds/{name}")
    @protected(api="infrastructure", resource="clouds", verb="update")
    @use_schema("body", schema=Cloud.Schema)
    @load("entity", Cloud)
    async def update_cloud(request, body, entity):
        # Once a resource is in the "deletion in progress" state, finalizers
        # can only be removed.
        if entity.metadata.deletion_state.deleted:
            if not set(body.metadata.finalizers) <= set(entity.metadata.finalizers):
                problem = HttpProblem(
                    detail="Finalizers can only be removed"
                    " if a deletion is in progress.",
                    title=HttpProblemTitle.UPDATE_ERROR,
                )
                raise HttpProblemError(web.HTTPConflict, problem)

        if body == entity:
            problem = HttpProblem(
                detail="The body contained no update.",
                title=HttpProblemTitle.UPDATE_ERROR,
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
        if entity.metadata.deletion_state.deleted and not entity.metadata.finalizers:
            await session(request).delete(entity)
            logger.info(
                "Delete %s %r (%s)", "Cloud", entity.metadata.name, entity.metadata.uid
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)", "Cloud", entity.metadata.name, entity.metadata.uid
            )

        return web.json_response(entity.serialize())

    @routes.route("PUT", "/infrastructure/namespaces/{namespace}/clouds/{name}/status")
    @protected(api="infrastructure", resource="clouds/status", verb="update")
    @use_schema("body", Cloud.Schema)
    @load("entity", Cloud)
    async def update_cloud_status(request, body, entity):
        source = getattr(body, "status")
        dest = getattr(entity, "status")

        try:
            dest.update(source)
        except ValueError as e:
            problem = HttpProblem(detail=str(e), title=HttpProblemTitle.UPDATE_ERROR)
            raise HttpProblemError(web.HTTPBadRequest, problem)

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            "Status",
            "Cloud",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())
