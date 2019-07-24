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
from aiohttp import web, ClientSession

from krake.data.system import SystemMetadata, Verb, RoleRule, Role, RoleBinding
from . import middlewares
from . import auth
from .resources import routes
from .resources.roles import routes as roles
from .resources.kubernetes import routes as kubernetes


def create_app(config):
    """Create aiohttp application instance providing the Krake HTTP API

    Args:
        config (dict): Application configuration

    Returns:
        aiohttp.web.Application: Krake HTTP API
    """
    logger = logging.getLogger("krake.api.error")

    # Authenticators
    if config["authentication"]["kind"] == "static":
        authenticator = auth.static_authentication(
            name=config["authentication"]["name"]
        )
    elif config["authentication"]["kind"] == "keystone":
        authenticator = auth.keystone_authentication(
            endpoint=config["authentication"]["endpoint"]
        )
    else:
        raise ValueError(f"Unknown authentication method {config['auth']['kind']!r}")

    # Authorizers
    if config["authorization"] == "always-allow":
        authorizer = auth.always_allow
    elif config["authorization"] == "RBAC":
        authorizer = auth.rbac

    app = web.Application(
        middlewares=[
            middlewares.error_log(logger),
            middlewares.database(config["etcd"]["host"], config["etcd"]["port"]),
            middlewares.authentication(authenticator),
        ]
    )
    app["config"] = config
    app["authorizer"] = authorizer

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
    app.add_routes(routes)
    app.add_routes(roles)
    app.add_routes(kubernetes)

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
    """Create :class:`krake.data.system.Role` from configuration.

    This is an example configuration for default roles:

    .. code:: yaml

        default-roles:
        - metadata:
            name: system:admin
          rules:
          - namespaces: ["all"]
            resources: ["all"]
            verbs: ["create", "list", "get", "update", "delete"]

    Args:
        role (dict): Configuration dictionary for a single role

    Returns:
        krake.data.system.Role: Role created from configuration

    """
    return Role(
        metadata=SystemMetadata(name=role["metadata"]["name"], uid=None),
        status=None,
        rules=[
            RoleRule(
                namespaces=rule["namespaces"],
                resources=rule["resources"],
                verbs=[Verb.__members__[verb] for verb in rule["verbs"]],
            )
            for rule in role["rules"]
        ],
    )


def load_default_role_binding(binding):
    """Create :class:`krake.data.system.RoleBinding` from configuration.

    This is an example configuration for default role bindings:

    .. code:: yaml

        default-role-bindings:
        - metadata:
            name: system:admin
          users: ["system:admin"]
          roles: ["system:admin"]

    Args:
        role (dict): Configuration dictionary for a single role binding

    Returns:
        krake.data.system.RoleBinding: Role binding created from configuration

    """
    return RoleBinding(
        metadata=SystemMetadata(name=binding["metadata"]["name"], uid=None),
        status=None,
        users=binding["users"],
        roles=binding["roles"],
    )
