"""This module defines the bootstrap function for creating the aiohttp server
instance serving Krake's HTTP API.

The specific HTTP endpoints are specified in submodules in in
:mod:`.resources`. For example, all Kubernetes related HTTP endpoints are
specified in :mod:`.resources.kubernetes`.

Example:
    The API server can be run as follows:

    .. code:: python

        from aiohttp import web
        from krake.api.app import create_app

        config = ...
        app = create_app(config)
        web.run_app(app)

"""
import logging
from aiohttp import web

from . import middlewares
from .resources import routes
from .resources.kubernetes import routes as kubernetes


def create_app(config):
    """Create aiohttp application instance providing the Krake HTTP API

    Args:
        config (dict): Application configuration

    Returns:
        aiohttp.web.Application: Krake HTTP API
    """
    logger = logging.getLogger("krake.api.error")

    # Authentication middlewares
    if config["auth"]["kind"] == "anonymous":
        anonymous = middlewares.User(name=config["auth"]["name"])
        auth_middleware = middlewares.anonymous_auth(anonymous)

    app = web.Application(
        middlewares=[
            middlewares.error_log(logger),
            middlewares.database(config["etcd"]["host"], config["etcd"]["port"]),
            auth_middleware,
        ]
    )
    app["config"] = config
    app.add_routes(routes)
    app.add_routes(kubernetes)

    return app
