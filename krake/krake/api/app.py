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
import logging
import ssl
from aiohttp import web, ClientSession

from krake.data.core import Metadata, Verb, RoleRule, Role, RoleBinding
from . import middlewares
from . import auth
from .core import routes as core_api
from .kubernetes import routes as kubernetes_api


def create_app(config):
    """Create aiohttp application instance providing the Krake HTTP API

    Args:
        config (dict): Application configuration

    Returns:
        aiohttp.web.Application: Krake HTTP API
    """
    logger = logging.getLogger("krake.api.error")

    if not config["tls"]["enabled"]:
        ssl_context = None
    else:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.verify_mode = ssl.CERT_OPTIONAL

        ssl_context.load_cert_chain(
            certfile=config["tls"]["cert"], keyfile=config["tls"]["key"]
        )

        # Load authorities for client certificates.
        client_ca = config["tls"]["client_ca"]
        if client_ca:
            ssl_context.load_verify_locations(cafile=client_ca)

    authentication = load_authentication(config)
    authorizer = load_authorizer(config)

    app = web.Application(
        middlewares=[
            middlewares.error_log(logger),
            authentication,
            middlewares.database(config["etcd"]["host"], config["etcd"]["port"]),
        ]
    )
    app["config"] = config
    app["authorizer"] = authorizer
    app["ssl_context"] = ssl_context

    # TODO: Default roles and role bindings should reside in the database as
    #   well. This means the database needs to be populated with these roles and
    #   bindings during the bootstrap process of Krake (with "rag" tool).
    app["default_roles"] = {
        role.metadata.name: role
        for role in (load_default_role(role) for role in config["default-roles"])
    }
    app["default_role_bindings"] = [
        binding
        for binding in (
            load_default_role_binding(binding)
            for binding in config["default-role-bindings"]
        )
    ]

    # Cleanup contexts
    app.cleanup_ctx.append(http_session)

    # Routes
    app.add_routes(core_api)
    app.add_routes(kubernetes_api)

    return app


async def http_session(app):
    """Async generator creating an :class:`aiohttp.ClientSession` HTTP session
    that can be used by other components (middlewares, route handlers). The HTTP
    client session is available under the ``http`` key of the application.

    This function should be used as cleanup context (see
    :attr:`aiohttp.web.Application.cleapup_ctx`).

    Args:
        app (aiohttp.web.Application): Web application

    """
    async with ClientSession() as session:
        app["http"] = session
        yield


def load_default_role(role):
    """Create :class:`krake.data.core.Role` from configuration.

    This is an example configuration for default roles:

    .. code:: yaml

        default-roles:
        - metadata:
            name: system:admin
          rules:
          - api: all
            namespaces: ["all"]
            resources: ["all"]
            verbs: ["create", "list", "get", "update", "delete"]

    Args:
        role (dict): Configuration dictionary for a single role

    Returns:
        krake.data.core.Role: Role created from configuration

    """
    return Role(
        metadata=Metadata(
            name=role["metadata"]["name"], uid=None, created=None, modified=None
        ),
        rules=[
            RoleRule(
                api=rule["api"],
                namespaces=rule["namespaces"],
                resources=rule["resources"],
                verbs=[Verb.__members__[verb] for verb in rule["verbs"]],
            )
            for rule in role["rules"]
        ],
    )


def load_default_role_binding(binding):
    """Create :class:`krake.data.core.RoleBinding` from configuration.

    This is an example configuration for default role bindings:

    .. code:: yaml

        default-role-bindings:
        - metadata:
            name: system:admin
          users: ["system:admin"]
          roles: ["system:admin"]

    Args:
        binding (dict): Configuration dictionary for a single role binding

    Returns:
        krake.data.core.RoleBinding: Role binding created from configuration

    """
    return RoleBinding(
        metadata=Metadata(
            name=binding["metadata"]["name"], uid=None, created=None, modified=None
        ),
        users=binding["users"],
        roles=binding["roles"],
    )


def load_authentication(config):
    """Create the authentication middleware :func:`.middlewares.authentication`.

    The authenticators are loaded from the "authentication" configuration key.
    If the server is configured with TLS, client certificates are also added
    as authentication (:func:`.auth.client_certificate_authentication`)
    strategy.

    Args:
        config (dict): Application configuration

    Returns:
        aiohttp middleware handling request authentication

    """
    authenticators = []

    allow_anonymous = config["authentication"].get("allow_anonymous", False)
    strategy = config["authentication"]["strategy"]

    if strategy["static"]["enabled"]:
        authenticators.append(
            auth.static_authentication(name=strategy["static"]["name"])
        )

    elif strategy["keystone"]["enabled"]:
        authenticators.append(
            auth.keystone_authentication(endpoint=strategy["keystone"]["endpoint"])
        )

    # If the "client_ca" TLS configuration parameter is given, enable client
    # certificate authentication.
    if config["tls"]["enabled"] and config["tls"]["client_ca"]:
        authenticators.append(auth.client_certificate_authentication())

    return middlewares.authentication(authenticators, allow_anonymous)


def load_authorizer(config):
    """Load authorization function from configuration.

    Args:
        config (dict): Application configuration

    Raises:
        ValueError: If an unknown authorization strategy is configured

    Returns:
        Coroutine function for authorizing resource requests

    """
    if config["authorization"] == "always-allow":
        return auth.always_allow

    if config["authorization"] == "always-deny":
        return auth.always_deny

    if config["authorization"] == "RBAC":
        return auth.rbac

    raise ValueError(f"Unknown authorization strategy {config['authorization']!r}")
