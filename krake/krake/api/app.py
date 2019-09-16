import logging
from aiohttp import web

from . import middlewares
from .resources import routes
from .resources.kubernetes import routes as kubernetes


logger = logging.getLogger(__name__)


def create_app(config):
    app = web.Application(
        middlewares=[
            middlewares.database(config["etcd"]["host"], config["etcd"]["port"]),
            middlewares.error_log(logger),
        ]
    )
    app["config"] = config
    app.add_routes(routes)
    app.add_routes(kubernetes)

    return app
