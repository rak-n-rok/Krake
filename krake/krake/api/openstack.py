import logging
from aiohttp import web
from aiohttp.web_request import Request
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
    list_or_watch_resources_async,
    must_create_resource_async,
    initialize_subresource_fields,
    delete_resource_async,
    update_resource_async,
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

    # region MagnumClusters
    @routes.route("POST", "/openstack/namespaces/{namespace}/magnumclusters")
    @protected(api="openstack", resource="magnumclusters", verb="create")
    @use_schema("body", schema=make_create_request_schema(MagnumCluster))
    async def create_magnum_cluster_async(request: Request, body: MagnumCluster):
        body = initialize_subresource_fields(body)
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("GET", "/openstack/magnumclusters")
    @routes.route("GET", "/openstack/namespaces/{namespace}/magnumclusters")
    @protected(api="openstack", resource="magnumclusters", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_magnum_clusters_async(
        request: Request, heartbeat: int, watch: bool
    ):
        return await list_or_watch_resources_async(
            MagnumCluster, MagnumClusterList, request, watch, heartbeat
        )

    @routes.route("GET", "/openstack/namespaces/{namespace}/magnumclusters/{name}")
    @protected(api="openstack", resource="magnumclusters", verb="get")
    @load("entity", MagnumCluster)
    async def read_magnum_cluster_async(request: Request, entity: MagnumCluster):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/openstack/namespaces/{namespace}/magnumclusters/{name}")
    @protected(api="openstack", resource="magnumclusters", verb="update")
    @use_schema("body", schema=MagnumCluster.Schema)
    @load("entity", MagnumCluster)
    async def update_magnum_cluster_async(
        request: Request, body: MagnumCluster, entity: MagnumCluster
    ):
        return await update_resource_async(request, entity, body)

    @routes.route(
        "PUT", "/openstack/namespaces/{namespace}/magnumclusters/{name}/binding"
    )
    @protected(api="openstack", resource="magnumclusters/binding", verb="update")
    @use_schema("body", MagnumClusterBinding.Schema)
    @load("cluster", MagnumCluster)
    async def update_magnum_cluster_binding_async(
        request: Request, body: MagnumCluster, cluster: MagnumCluster
    ):
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
    async def update_magnum_cluster_status_async(
        request: Request, body: MagnumCluster, entity: MagnumCluster
    ):
        return await update_property_async("status", request, body, entity)

    @routes.route("DELETE", "/openstack/namespaces/{namespace}/magnumclusters/{name}")
    @protected(api="openstack", resource="magnumclusters", verb="delete")
    @load("entity", MagnumCluster)
    async def delete_magnum_cluster_async(request: Request, entity: MagnumCluster):
        return await delete_resource_async(request, entity)

    # endregion MagnumClusters

    # region Projects
    @routes.route("POST", "/openstack/namespaces/{namespace}/projects")
    @protected(api="openstack", resource="projects", verb="create")
    @use_schema("body", schema=make_create_request_schema(Project))
    async def create_project_async(request: Request, body: Project):
        body = initialize_subresource_fields(body)
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("GET", "/openstack/projects")
    @routes.route("GET", "/openstack/namespaces/{namespace}/projects")
    @protected(api="openstack", resource="projects", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_projects_async(
        request: Request, heartbeat: int, watch, bool
    ):
        return await list_or_watch_resources_async(
            Project, ProjectList, request, watch, heartbeat
        )

    @routes.route("GET", "/openstack/namespaces/{namespace}/projects/{name}")
    @protected(api="openstack", resource="projects", verb="get")
    @load("entity", Project)
    async def read_project_async(request: Request, entity: Project):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/openstack/namespaces/{namespace}/projects/{name}")
    @protected(api="openstack", resource="projects", verb="update")
    @use_schema("body", schema=Project.Schema)
    @load("entity", Project)
    async def update_project_async(request: Request, body: Project, entity: Project):
        return await update_resource_async(request, entity, body)

    @routes.route("PUT", "/openstack/namespaces/{namespace}/projects/{name}/status")
    @protected(api="openstack", resource="projects/status", verb="update")
    @use_schema("body", Project.Schema)
    @load("entity", Project)
    async def update_project_status_async(
        request: Request, body: MagnumCluster, entity: MagnumCluster
    ):
        return await update_property_async("status", request, body, entity)

    @routes.route("DELETE", "/openstack/namespaces/{namespace}/projects/{name}")
    @protected(api="openstack", resource="projects", verb="delete")
    @load("entity", Project)
    async def delete_project_async(request: Request, entity: MagnumCluster):
        return await delete_resource_async(request, entity)

    # endregion Projects
