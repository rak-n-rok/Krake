from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs

from krake.data.system import RoleBinding
from .. import __version__ as version
from ..helpers import session


routes = web.RouteTableDef()


@routes.get("/")
@use_kwargs({"all": fields.Bool(location="query")})
async def index(request, all=False):
    return web.json_response({"version": version})


@routes.get("/me")
async def me(request):
    roles = set()
    user = request["user"]

    async for binding in session(request).all(RoleBinding):
        if user in binding.users:
            roles.update(binding.roles)

    return web.json_response({"user": user, "roles": sorted(roles)})
