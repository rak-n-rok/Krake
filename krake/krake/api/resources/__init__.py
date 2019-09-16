from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs

from krake.api import __version__ as version


routes = web.RouteTableDef()


@routes.get("/")
@use_kwargs({"all": fields.Bool(location="query")})
async def index(request, all=False):
    return web.json_response({"version": version})
