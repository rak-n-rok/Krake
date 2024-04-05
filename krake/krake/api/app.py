"""This module defines the bootstrap function for creating the aiohttp server
instance serving Krake's HTTP API.

Krake serves multiple APIs for different technologies, e.g. the core
functionality like roles and role bindings are served by the
:mod:`krake.api.core` API where as the Kubernetes API is provided by
:mod:`krake.api.kubernetes`.

Example:
    The API server can be run as follows:

    .. code:: python

        from aiohttp import web
        from krake.api.app import create_app

        config = ...
        app = create_app(config)
        web.run_app(app)

"""
from typing import Callable
import aiohttp_cors
import logging
import ssl

from aiohttp import ClientSession, TCPConnector, web
from functools import partial
from krake.api.database import Session

from krake.data.core import RoleBinding
from krake.data.config import ApiConfiguration
from . import __version__ as version
from . import middlewares
from . import auth
from .helpers import session
from .core import CoreApi
from .openstack import OpenStackApi
from .kubernetes import KubernetesApi
from .infrastructure import InfrastructureApi

routes = web.RouteTableDef()


@routes.get("/")
async def index_async(request) -> web.Response:
    return web.json_response({"version": version})


@routes.get("/me")
async def me_async(request) -> web.Response:
    roles = set()
    user: str = request["user"]

    async for binding in session(request).all(RoleBinding):
        if user in binding.users:
            roles.update(binding.roles)

    return web.json_response({"user": user, "roles": sorted(roles)})


@routes.get("/release")
async def release_async(request) -> web.Response:
    return web.json_response("You released the Krake.", status=202)


def create_app(config: ApiConfiguration) -> web.Application:
    """Create aiohttp application instance providing the Krake HTTP API

    Args:
        config (krake.data.config.ApiConfiguration): Application configuration object

    Returns:
        aiohttp.web.Application: Krake HTTP API
    """
    logger = logging.getLogger("krake.api")

    if not config.tls.enabled:
        ssl_context = None
    else:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.verify_mode = ssl.CERT_OPTIONAL

        ssl_context.load_cert_chain(certfile=config.tls.cert, keyfile=config.tls.key)

        # Load authorities for client certificates.
        client_ca = config.tls.client_ca
        if client_ca:
            ssl_context.load_verify_locations(cafile=client_ca)

    authentication = load_authentication(config)
    authorizer = load_authorizer(config)

    app = web.Application(
        logger=logger,
        middlewares=[
            middlewares.problem_response(problem_base_url=config.docs.problem_base_url),
            middlewares.error_log(),
            authentication,
            middlewares.retry_transaction(retry=config.etcd.retry_transactions),
        ],
    )
    app["config"] = config
    app["authorizer"] = authorizer
    app["ssl_context"] = ssl_context

    # Cleanup contexts
    app.cleanup_ctx.append(partial(http_session_async, ssl_context=ssl_context))
    app.cleanup_ctx.append(
        partial(db_session_async, host=config.etcd.host, port=config.etcd.port)
    )

    # Routes
    app.add_routes(routes)
    app.add_routes(CoreApi.routes)
    app.add_routes(OpenStackApi.routes)
    app.add_routes(KubernetesApi.routes)
    app.add_routes(InfrastructureApi.routes._items)

    cors_setup(app)
    return app


def cors_setup(app: web.Application):
    """Set the default CORS (Cross-Origin Resource Sharing) rules for all routes of the
    given web application.

    Args:
        app (aiohttp.web.Application): Web application

    """
    cors_origin = app["config"].authentication.cors_origin

    default_origin = "*"
    if cors_origin == default_origin:
        app.logger.warning(
            f"Setting the default origin '{default_origin}' for the CORS setup may be a"
            " security concern. See the 'Security principles' in the admin"
            " documentation."
        )

    cors = aiohttp_cors.setup(
        app,
        defaults={
            cors_origin: aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                allow_headers="*",
                allow_methods=["DELETE", "GET", "OPTIONS", "POST", "PUT"],
            )
        },
    )
    for route in app.router.routes():
        cors.add(route)


async def db_session_async(app: web.Application, host: str, port: int):
    """Async generator creating a database :class:`krake.api.database.Session` that can
    be used by other components (middleware, route handlers) or by the requests
    handlers. The database session is available under the ``db`` key of the application.

    This function should be used as cleanup context (see
    :attr:`aiohttp.web.Application.cleanup_ctx`).

    Args:
        app (aiohttp.web.Application): Web application
        host (str): host name the application listens to
        port (int): port the application listens to

    """
    async with Session(host=host, port=port) as session:
        app["db"] = session
        yield


async def http_session_async(app: web.Application, ssl_context: ssl.SSLContext = None):
    """Async generator creating an :class:`aiohttp.ClientSession` HTTP(S) session
    that can be used by other components (middleware, route handlers). The HTTP(S)
    client session is available under the ``http`` key of the application.

    This function should be used as cleanup context (see
    :attr:`aiohttp.web.Application.cleanup_ctx`).

    Args:
        app (aiohttp.web.Application): Web application
        ssl_context (ssl.SSLContext): SSL Context (optional)
    """
    connector = None
    if ssl_context:
        connector = TCPConnector(ssl_context=ssl_context)

    async with ClientSession(connector=connector) as session:
        app["http"] = session
        yield


def load_authentication(config: ApiConfiguration) -> Callable:
    """Create the authentication middleware :func:`.middlewares.authentication`.

    The authenticators are loaded from the "authentication" configuration key.
    If the server is configured with TLS, client certificates are also added
    as authentication (:func:`.auth.client_certificate_authentication`)
    strategy.

    Args:
        config (krake.data.config.ApiConfiguration): Application configuration object

    Returns:
        aiohttp middleware handling request authentication

    """
    authenticators = []

    allow_anonymous = config.authentication.allow_anonymous
    strategy = config.authentication.strategy

    if strategy.static.enabled:
        authenticators.append(auth.static_authentication(name=strategy.static.name))

    elif strategy.keystone.enabled:
        authenticators.append(
            auth.keystone_authentication(endpoint=strategy.keystone.endpoint)
        )
    elif strategy.keycloak.enabled:
        authenticators.append(
            auth.keycloak_authentication(
                endpoint=strategy.keycloak.endpoint, realm=strategy.keycloak.realm
            )
        )

    # If the "client_ca" TLS configuration parameter is given, enable client
    # certificate authentication.
    if config.tls.enabled and config.tls.client_ca:
        authenticators.append(auth.client_certificate_authentication())

    return middlewares.authentication(authenticators, allow_anonymous)


UNKNOWN_AUTHORIZATION_STRATEGY_ERROR = "Unknown authorization strategy"


def load_authorizer(config: ApiConfiguration) -> Callable:
    """Load authorization function from configuration.

    Args:
        config (krake.data.config.ApiConfiguration): Application configuration object

    Raises:
        ValueError: If an unknown authorization strategy is configured

    Returns:
        Coroutine function for authorizing resource requests

    """
    if config.authorization == "always-allow":
        return auth.always_allow

    if config.authorization == "always-deny":
        return auth.always_deny

    if config.authorization == "RBAC":
        return auth.rbac

    raise ValueError(f"{UNKNOWN_AUTHORIZATION_STRATEGY_ERROR} {config.authorization!r}")
