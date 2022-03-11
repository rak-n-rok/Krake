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
from krake.data.core import WatchEvent, WatchEventType, ListMetadata
from krake.data.openstack import (
    ProjectList,
    Project,
    MagnumCluster,
    MagnumClusterList,
    MagnumClusterBinding,
)

logger = logging.getLogger(__name__)


class OpenStackApi(object):
    """Contains all handlers for the resources of the "openstack" API.
    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    @routes.route("POST", "/openstack/namespaces/{namespace}/magnumclusters")
    @protected(api="openstack", resource="magnumclusters", verb="create")
    @use_schema("body", schema=make_create_request_schema(MagnumCluster))
    async def create_magnum_cluster(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=(
                    f"MagnumCluster {body.metadata.name!r} already "
                    f"exists in namespace {namespace!r}"
                ),
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
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
            "Created %s %r (%s)", "MagnumCluster", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route("DELETE", "/openstack/namespaces/{namespace}/magnumclusters/{name}")
    @protected(api="openstack", resource="magnumclusters", verb="delete")
    @load("entity", MagnumCluster)
    async def delete_magnum_cluster(request, entity):
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
            "MagnumCluster",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/openstack/magnumclusters")
    @routes.route("GET", "/openstack/namespaces/{namespace}/magnumclusters")
    @protected(api="openstack", resource="magnumclusters", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_magnum_clusters(request, heartbeat, watch, **query):
        resource_class = MagnumCluster

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

            body = MagnumClusterList(metadata=ListMetadata(), items=objs)
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

    @routes.route("GET", "/openstack/namespaces/{namespace}/magnumclusters/{name}")
    @protected(api="openstack", resource="magnumclusters", verb="get")
    @load("entity", MagnumCluster)
    async def read_magnum_cluster(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/openstack/namespaces/{namespace}/magnumclusters/{name}")
    @protected(api="openstack", resource="magnumclusters", verb="update")
    @use_schema("body", schema=MagnumCluster.Schema)
    @load("entity", MagnumCluster)
    async def update_magnum_cluster(request, body, entity):
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
                "Delete %s %r (%s)",
                "MagnumCluster",
                entity.metadata.name,
                entity.metadata.uid,
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)",
                "MagnumCluster",
                entity.metadata.name,
                entity.metadata.uid,
            )

        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/openstack/namespaces/{namespace}/magnumclusters/{name}/binding"
    )
    @protected(api="openstack", resource="magnumclusters/binding", verb="update")
    @load("cluster", MagnumCluster)
    @use_schema("body", MagnumClusterBinding.Schema)
    async def update_magnum_cluster_binding(request, body, cluster):
        cluster.status.project = body.project
        cluster.status.template = body.template

        if body.project not in cluster.metadata.owners:
            cluster.metadata.owners.append(body.project)

        await session(request).put(cluster)
        logger.info("Bind %r to %r", cluster, cluster.status.project)
        return web.json_response(cluster.serialize())

    @routes.route(
        "PUT", "/openstack/namespaces/{namespace}/magnumclusters/{name}/status"
    )
    @protected(api="openstack", resource="magnumclusters/status", verb="update")
    @use_schema("body", MagnumCluster.Schema)
    @load("entity", MagnumCluster)
    async def update_magnum_cluster_status(request, body, entity):
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
            "MagnumCluster",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("POST", "/openstack/namespaces/{namespace}/projects")
    @protected(api="openstack", resource="projects", verb="create")
    @use_schema("body", schema=make_create_request_schema(Project))
    async def create_project(request, body):
        kwargs = {"name": body.metadata.name}

        namespace = request.match_info.get("namespace")
        kwargs["namespace"] = namespace

        # Ensure that a resource with the same name does not already
        # exists.
        existing = await session(request).get(body.__class__, **kwargs)

        if existing is not None:
            problem = HttpProblem(
                detail=(
                    f"Project {body.metadata.name!r} already "
                    f"exists in namespace {namespace!r}"
                ),
                title=HttpProblemTitle.RESOURCE_ALREADY_EXISTS
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
            "Created %s %r (%s)", "Project", body.metadata.name, body.metadata.uid
        )

        return web.json_response(body.serialize())

    @routes.route("DELETE", "/openstack/namespaces/{namespace}/projects/{name}")
    @protected(api="openstack", resource="projects", verb="delete")
    @load("entity", Project)
    async def delete_project(request, entity):
        # Resource is already deleting
        if entity.metadata.deleted:
            return web.json_response(entity.serialize())

        # TODO: Should be update "modified" here?
        # Resource marked as deletion, to be deleted by the Garbage Collector
        entity.metadata.deleted = utils.now()
        entity.metadata.finalizers.append("cascade_deletion")

        await session(request).put(entity)
        logger.info(
            "Deleting %s %r (%s)", "Project", entity.metadata.name, entity.metadata.uid
        )

        return web.json_response(entity.serialize())

    @routes.route("GET", "/openstack/projects")
    @routes.route("GET", "/openstack/namespaces/{namespace}/projects")
    @protected(api="openstack", resource="projects", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_projects(request, heartbeat, watch, **query):
        resource_class = Project

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

            body = ProjectList(metadata=ListMetadata(), items=objs)
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

    @routes.route("GET", "/openstack/namespaces/{namespace}/projects/{name}")
    @protected(api="openstack", resource="projects", verb="get")
    @load("entity", Project)
    async def read_project(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/openstack/namespaces/{namespace}/projects/{name}")
    @protected(api="openstack", resource="projects", verb="update")
    @use_schema("body", schema=Project.Schema)
    @load("entity", Project)
    async def update_project(request, body, entity):
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
                "Delete %s %r (%s)",
                "Project",
                entity.metadata.name,
                entity.metadata.uid,
            )
        else:
            await session(request).put(entity)
            logger.info(
                "Update %s %r (%s)",
                "Project",
                entity.metadata.name,
                entity.metadata.uid,
            )

        return web.json_response(entity.serialize())

    @routes.route("PUT", "/openstack/namespaces/{namespace}/projects/{name}/status")
    @protected(api="openstack", resource="projects/status", verb="update")
    @use_schema("body", Project.Schema)
    @load("entity", Project)
    async def update_project_status(request, body, entity):
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
            "Project",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())
