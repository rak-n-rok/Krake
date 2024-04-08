from abc import ABCMeta, abstractmethod

from krake.data.serializable import ApiObject
from webargs.aiohttpparser import use_kwargs

from aiohttp import web

from krake.api.auth import protected
from krake.api.helpers import (
    ListQuery,
    load,
    use_schema,
    make_create_request_schema,
)
from krake.api import base


def crud_api(cls):
    if getattr(cls, CrudApi.static_init.__name__, None):
        cls.static_init()
    return cls


class CrudApi(metaclass=ABCMeta):
    @classmethod
    @abstractmethod
    def static_init(cls):
        cls.create_crud_routes()

    @classmethod
    def create_crud_routes(cls):

        api_route: str = None
        if cls.namespacing:
            api_route = f"/{cls.api}/namespaces/{{namespace}}/{cls.resource}"
        else:
            api_route = f"/{cls.api}/{cls.resource}"

        # routes = web.RouteTableDef()
        # region GlobalInfrastructureProvider
        @cls.routes.route("POST", api_route)
        @protected(api=cls.api, resource=cls.resource, verb="create")
        @use_schema("body", schema=make_create_request_schema(cls.resource_type))
        async def create_resource_async(request: web.Request, body: ApiObject):
            await cls.before_create_async(request, body)
            namespace = request.match_info.get("namespace")
            return await base.must_create_resource_async(request, body, namespace)

        if cls.namespacing:

            @cls.routes.route("GET", api_route)
            @cls.routes.route("GET", f"/{cls.api}/{cls.resource}")
            @protected(api=cls.api, resource=cls.resource, verb="list")
            @use_kwargs(ListQuery.query, location="query")
            async def list_or_watch_resource_async(
                request: web.Request, heartbeat: int, watch: bool
            ):
                return await base.list_or_watch_resources_async(
                    cls.resource_type, cls.resoure_list_type, request, heartbeat, watch
                )

        else:

            @cls.routes.route("GET", api_route)
            @protected(api=cls.api, resource=cls.resource, verb="list")
            @use_kwargs(ListQuery.query, location="query")
            async def list_or_watch_resource_async(
                request: web.Request, heartbeat: int, watch: bool
            ):
                return await base.list_or_watch_resources_async(
                    cls.resource_type, cls.resoure_list_type, request, heartbeat, watch
                )

        @cls.routes.route("GET", f"{api_route}/{{name}}")
        @protected(api=cls.api, resource=cls.resource, verb="get")
        @load("entity", cls.resource_type)
        async def read_resource_async(request: web.Request, entity: ApiObject):
            return web.json_response(entity.serialize())

        @cls.routes.route("PUT", f"{api_route}/{{name}}")
        @protected(api=cls.api, resource=cls.resource, verb="update")
        @use_schema("body", schema=cls.resource_type.Schema)
        @load("entity", cls.resource_type)
        async def update_resource_asnyc(
            request: web.Request, body: ApiObject, entity: ApiObject
        ):
            return await base.update_resource_async(request, entity, body)

        @cls.routes.route("DELETE", f"{api_route}/{{name}}")
        @protected(api=cls.api, resource=cls.resource, verb="delete")
        @load("entity", cls.resource_type)
        async def delete_global_infrastructure_provider_async(
            request: web.Request, entity: ApiObject
        ):
            return await base.delete_resource_async(request, entity)

    @staticmethod
    async def before_create_async(request: web.Request, body: ApiObject):
        pass

    @property
    @staticmethod
    @abstractmethod
    def routes(self) -> web.RouteTableDef:
        pass

    @property
    @staticmethod
    def namespacing(self) -> bool:
        return True

    @property
    @abstractmethod
    def api(self) -> str:
        pass

    @property
    @abstractmethod
    def resource(self) -> str:
        pass

    @property
    @abstractmethod
    def resource_type(self) -> type:
        pass

    @property
    @abstractmethod
    def resoure_list_type(self) -> type:
        pass
