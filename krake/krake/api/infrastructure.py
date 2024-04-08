from aiohttp import web

from krake.api.auth import protected
from krake.api.helpers import (
    load,
    use_schema,
)
from krake.api import base
from krake.data.serializable import ApiObject
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
from krake.api.crud_api import CrudApi, crud_api


INFRASTRUCTURE_API_PREFIX = "infrastructure"


@crud_api
class GlobalInfrastructureProviderApi(CrudApi):
    routes = web.RouteTableDef()

    namespacing = False
    api = INFRASTRUCTURE_API_PREFIX
    resource = "globalinfrastructureproviders"
    resource_type = GlobalInfrastructureProvider
    resoure_list_type = GlobalInfrastructureProviderList


@crud_api
class InfrastructureProviderApi(CrudApi):
    routes = web.RouteTableDef()

    api = INFRASTRUCTURE_API_PREFIX
    resource = "infrastructureproviders"
    resource_type = InfrastructureProvider
    resoure_list_type = InfrastructureProviderList


@crud_api
class GlobalCloudsApi(CrudApi):
    routes = web.RouteTableDef()

    namespacing = False
    api = INFRASTRUCTURE_API_PREFIX
    resource = "globalclouds"
    resource_type = GlobalCloud
    resoure_list_type = GlobalCloudList

    @routes.route("PUT", "/infrastructure/globalclouds/{name}/status")
    @protected(api="infrastructure", resource="globalclouds/status", verb="update")
    @use_schema("body", GlobalCloud.Schema)
    @load("entity", GlobalCloud)
    async def update_global_cloud_status_async(
        request: web.Request, body: GlobalCloud, entity: GlobalCloud
    ):
        return await base.update_property_async("status", request, body, entity)

    @staticmethod
    async def before_create_async(_: web.Request, body: ApiObject):
        body = base.initialize_subresource_fields(body)


@crud_api
class CloudsApi(CrudApi):
    routes = web.RouteTableDef()

    namespacing = True
    api = INFRASTRUCTURE_API_PREFIX
    resource = "clouds"
    resource_type = Cloud
    resoure_list_type = CloudList

    @routes.route("PUT", "/infrastructure/namespaces/{namespace}/clouds/{name}/status")
    @protected(api="infrastructure", resource="clouds/status", verb="update")
    @use_schema("body", Cloud.Schema)
    @load("entity", Cloud)
    async def update_cloud_status_async(request: web.Request, body, entity):
        return await base.update_property_async("status", request, body, entity)

    @staticmethod
    async def before_create_async(_: web.Request, body: ApiObject):
        body = base.initialize_subresource_fields(body)


class InfrastructureApi(object):
    """Contains all handlers for the resources of the "infrastructure" API.

    These handlers will be added to the Krake API components.
    """

    # TODO solution without accessing private attribute _items
    routes = GlobalInfrastructureProviderApi.routes
    routes._items += InfrastructureProviderApi.routes
    routes._items += GlobalCloudsApi.routes
    routes._items += CloudsApi.routes
