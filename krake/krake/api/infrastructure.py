import logging

from aiohttp import web
from webargs.aiohttpparser import use_kwargs

from krake.api.auth import protected
from krake.api.helpers import (
    load,
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

logger = logging.getLogger(__name__)


class InfrastructureApi(object):
    """Contains all handlers for the resources of the "infrastructure" API.

    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    # region GlobalInfrastructureProvider
    @routes.route("POST", "/infrastructure/globalinfrastructureproviders")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="create"
    )
    @use_schema("body", schema=make_create_request_schema(GlobalInfrastructureProvider))
    async def create_global_infrastructure_provider(request, body):
        return await must_create_resource_async(request, body, None)

    @routes.route("GET", "/infrastructure/globalinfrastructureproviders")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_infrastructure_providers(
        request, heartbeat, watch, **query
    ):
        return await list_or_watch_resources_async(
            GlobalInfrastructureProvider,
            GlobalInfrastructureProviderList,
            request,
            watch,
            heartbeat,
        )

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
        return await update_resource_async(request, entity, body)

    @routes.route("DELETE", "/infrastructure/globalinfrastructureproviders/{name}")
    @protected(
        api="infrastructure", resource="globalinfrastructureproviders", verb="delete"
    )
    @load("entity", GlobalInfrastructureProvider)
    async def delete_global_infrastructure_provider(request, entity):
        return await delete_resource_async(request, entity)

    # endregion GlobalInfrastructureProvider

    # region InfrastructureProvider
    @routes.route(
        "POST", "/infrastructure/namespaces/{namespace}/infrastructureproviders"
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="create")
    @use_schema("body", schema=make_create_request_schema(InfrastructureProvider))
    async def create_infrastructure_provider(request, body):
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("GET", "/infrastructure/infrastructureproviders")
    @routes.route(
        "GET", "/infrastructure/namespaces/{namespace}/infrastructureproviders"
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_infrastructure_providers(
        request, heartbeat, watch, **query
    ):
        namespace = request.match_info.get("namespace", None)

        return await list_or_watch_resources_async(
            InfrastructureProvider,
            InfrastructureProviderList,
            request,
            watch,
            heartbeat,
            namespace,
        )

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
        return await update_resource_async(request, entity, body)

    @routes.route(
        "DELETE",
        "/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}",
    )
    @protected(api="infrastructure", resource="infrastructureproviders", verb="delete")
    @load("entity", InfrastructureProvider)
    async def delete_infrastructure_provider(request, entity):
        return await delete_resource_async(request, entity)

    # endregion InfrastructureProvider

    # region GlobalClouds
    @routes.route("POST", "/infrastructure/globalclouds")
    @protected(api="infrastructure", resource="globalclouds", verb="create")
    @use_schema("body", schema=make_create_request_schema(GlobalCloud))
    async def create_global_cloud(request, body):
        body = initialize_subresource_fields(body)
        return await must_create_resource_async(request, body, None)

    @routes.route("GET", "/infrastructure/globalclouds")
    @protected(api="infrastructure", resource="globalclouds", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_clouds(request, heartbeat, watch, **query):
        return await list_or_watch_resources_async(
            GlobalCloud, GlobalCloudList, request, watch, heartbeat
        )

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
        return await update_resource_async(request, entity, body)

    @routes.route("PUT", "/infrastructure/globalclouds/{name}/status")
    @protected(api="infrastructure", resource="globalclouds/status", verb="update")
    @use_schema("body", GlobalCloud.Schema)
    @load("entity", GlobalCloud)
    async def update_global_cloud_status(request, body, entity):
        return await update_property_async("status", request, body, entity)

    @routes.route("DELETE", "/infrastructure/globalclouds/{name}")
    @protected(api="infrastructure", resource="globalclouds", verb="delete")
    @load("entity", GlobalCloud)
    async def delete_global_cloud(request, entity):
        return await delete_resource_async(request, entity)

    # endregion GlobalClouds

    # region Clouds
    @routes.route("POST", "/infrastructure/namespaces/{namespace}/clouds")
    @protected(api="infrastructure", resource="clouds", verb="create")
    @use_schema("body", schema=make_create_request_schema(Cloud))
    async def create_cloud(request, body):
        body = initialize_subresource_fields(body)
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("GET", "/infrastructure/clouds")
    @routes.route("GET", "/infrastructure/namespaces/{namespace}/clouds")
    @protected(api="infrastructure", resource="clouds", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_clouds(request, heartbeat, watch, **query):
        # If the ListAll operation
        namespace = request.match_info.get("namespace", None)

        return await list_or_watch_resources_async(
            Cloud, CloudList, request, watch, heartbeat, namespace
        )

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
        return await update_resource_async(request, entity, body)

    @routes.route("PUT", "/infrastructure/namespaces/{namespace}/clouds/{name}/status")
    @protected(api="infrastructure", resource="clouds/status", verb="update")
    @use_schema("body", Cloud.Schema)
    @load("entity", Cloud)
    async def update_cloud_status(request, body, entity):
        return await update_property_async("status", request, body, entity)

    @routes.route("DELETE", "/infrastructure/namespaces/{namespace}/clouds/{name}")
    @protected(api="infrastructure", resource="clouds", verb="delete")
    @load("entity", Cloud)
    async def delete_cloud(request, entity):
        return await delete_resource_async(request, entity)

    # endregion Clouds
