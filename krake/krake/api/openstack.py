import logging
from aiohttp import web
from webargs.aiohttpparser import use_kwargs

from krake.api.auth import protected
from krake.api.helpers import (
    load,
    session,
    use_schema,
    make_create_request_schema,
    ListQuery,
)
from krake.api.base import (
    must_create_resource_async,
    initialize_subresource_fields,
    delete_resource_async,
    update_resource_async,
    list_resources_async,
    watch_resource_async,
    update_property_async,
)
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
        body = initialize_subresource_fields(body)
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("DELETE", "/openstack/namespaces/{namespace}/magnumclusters/{name}")
    @protected(api="openstack", resource="magnumclusters", verb="delete")
    @load("entity", MagnumCluster)
    async def delete_magnum_cluster(request, entity):
        return await delete_resource_async(request, entity)

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
            return await list_resources_async(
                resource_class, MagnumClusterList, request, namespace)

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

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
        return await update_resource_async(request, entity, body)

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
        return await update_property_async("status", request, body, entity)

    @routes.route("POST", "/openstack/namespaces/{namespace}/projects")
    @protected(api="openstack", resource="projects", verb="create")
    @use_schema("body", schema=make_create_request_schema(Project))
    async def create_project(request, body):
        body = initialize_subresource_fields(body)
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("DELETE", "/openstack/namespaces/{namespace}/projects/{name}")
    @protected(api="openstack", resource="projects", verb="delete")
    @load("entity", Project)
    async def delete_project(request, entity):
        return await delete_resource_async(request, entity)

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
            return await list_resources_async(
                resource_class, ProjectList, request, namespace)

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

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
        return await update_resource_async(request, entity, body)

    @routes.route("PUT", "/openstack/namespaces/{namespace}/projects/{name}/status")
    @protected(api="openstack", resource="projects/status", verb="update")
    @use_schema("body", Project.Schema)
    @load("entity", Project)
    async def update_project_status(request, body, entity):
        return await update_property_async("status", request, body, entity)
