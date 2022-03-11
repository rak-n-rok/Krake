"""Authentication and Authorization module for Krake.

Access to the Krake API is controlled by two distinct mechanisms performed
after each other:

Authentication
    verifies the identity of a user (Who is requesting?)
Authorization
    decides if the user has permission to access a resource


Authentication
--------------

Authentication is performed for every request. The
:func:`krake.api.middlewares.authentication` middleware factory is used for
this purpose. The concrete authentication implementation will be derived from
the configuration.

.. code:: yaml

    # Anonymous authentication
    authentication:
      kind: static
      name: system

    # Keystone authentication
    authentication:
      kind: keystone
      endpoint: http://localhost:5000/v3

An authenticator is a simple asynchronous function:

.. py:function authenticator(request)

    :param aiohttp.web.Request: Incoming HTTP request
    :raises aiohttp.web.HTTPUnauthorized: If the given authentication
        information is invalid.
    :rtype: str
    :return: Name of the authenticated user. If no authentication is given,
        None is returned.

Currently, there are two authentication implementations available:

 - Static authentication (:func:`static_authentication`)
 - Keystone authentication (:func:`keystone_authentication`)


Authorization
-------------

Authorization is established with the help of the :func:`protected` decorator
function. The decorator annotates a given aiohttp request handler with the
required authorization information (see :class:`AuthorizationRequest`).

An authorizer is a simple asynchronous function:

.. py:function authorizer(request, auth_request)

    :param aiohttp.web.Request request: Incoming HTTP request
    :param AuthorizationRequest auth_request: Requested authorization
    :raises aiohttp.web.HTTPForbidden: If the authenticated user does not have
        the permission to access the resource

The concrete authentication implementation will be derived from the
configuration and is stored under the ``authorizer`` key of the application.

.. code:: yaml

    # Authorization mode
    #
    #  - RBAC (Role-based access control)
    #  - always-allow (Allow all requests. No authorization is performed.)
    #  - always-deny (Deny all requests. Only for testing purposes.)
    #
    authorization: always-allow

Currently, there are three authorization implementations available:

 - Always allow (:func:`always_allow`)
 - Always deny (:func:`always_deny`)
 - Role-based access control / RBAC (:func:`rbac`)

"""
from functools import wraps
from typing import NamedTuple, Optional
from aiohttp import web

from krake.data.core import Verb, Role, RoleBinding
from yarl import URL

from .helpers import session, HttpProblemError, HttpProblem, HttpProblemTitle


def static_authentication(name):
    """Authenticator factory for authenticating every request with the given
    name.

    Args:
        name (str): Static user name that should be used for every request.

    Returns:
        callable: Authenticator returning the given name for every request.

    """

    async def authenticator(request):
        return name

    return authenticator


def client_certificate_authentication():
    """Authenticator factory for authenticating requests with client
    certificates.

    The client certificate is loaded from the ``peercert`` attribute of the
    underlying TCP transport. The common name of the client certificate is
    used as username


    Returns:
        callable: Authenticator using client certificate information for
        authentication.

    """

    async def authenticator(request):
        peercert = request.transport.get_extra_info("peercert")
        if not peercert:
            return None
        try:
            return _get_common_name(peercert["subject"])
        except ValueError:
            return None

    return authenticator


def _get_common_name(subject):
    for rdn in subject:
        for name, value in rdn:
            if name == "commonName":
                return value
    raise ValueError("'commonName' not found")


def keystone_authentication(endpoint):
    """Authenticator factory for OpenStack Keystone authentication.

    The token in the ``Authorization`` header of a request will be used as
    ``X-Auth-Token`` header for a request to the Keystone token endpoint.
    The returned user name from Keystone is used as authenticated user name.

    The authenticator requires an HTTP client session that is loaded from the
    ``http`` key of the application.

    Args:
        endpoint (str): Keystone HTTP endpoint

    Returns:
        callable: Authenticator for the given Keystone endpoint.
    """

    async def authenticator(request):
        token = request.headers.get("Authorization")
        if not token:
            return None

        resp = await request.app["http"].get(
            f"{endpoint}/auth/tokens",
            headers={"X-Auth-Token": token, "X-Subject-Token": token},
        )
        if resp.status != 200:
            problem = HttpProblem(
                detail=f"Invalid Keystone token (HTTP {resp.status} {resp.reason})",
                title=HttpProblemTitle.INVALID_KEYSTONE_TOKEN
            )
            raise HttpProblemError(web.HTTPUnauthorized, problem)

        data = await resp.json()
        return data["token"]["user"]["name"]

    return authenticator


def keycloak_authentication(endpoint, realm):
    """Authenticator factory for Keycloak authentication.

    The token in the ``Authorization`` header of a request sent to Krake will be sent as
    access token to the OpenID user information endpoint. The returned user name from
    Keycloak is used as authenticated user name.

    The authenticator requires an HTTP client session that is loaded from the
    ``http`` key of the application.

    Args:
        endpoint (str): Keycloak HTTP endpoint.
        realm (str): Keycloak realm to use at this endpoint.

    Returns:
        callable: Authenticator for the given Keystone endpoint.

    """

    async def authenticator(request):
        token = request.headers.get("Authorization")
        if not token:
            return None

        path = f"auth/realms/{realm}/protocol/openid-connect/userinfo"
        url = URL(endpoint) / path
        resp = await request.app["http"].post(url, data={"access_token": token})
        if resp.status != 200:
            problem = HttpProblem(
                detail=f"Invalid Keycloak token " f"(HTTP {resp.status} {resp.reason})",
                title=HttpProblemTitle.INVALID_KEYCLOAK_TOKEN
            )
            raise HttpProblemError(web.HTTPUnauthorized, problem)

        data = await resp.json()
        return data["preferred_username"]

    return authenticator


class AuthorizationRequest(NamedTuple):
    """Authorization request handled by authorizers.

    Attributes:
        api (str): Name of the API group
        namespace (str, optional): If the resource is namespaced, the requested
            namespace
        resource (str): Name of the resource
        verb (krake.data.core.Verb): Verb that should be performed on the
            resource.

    """

    api: str
    namespace: Optional[str]
    resource: str
    verb: Verb


async def always_allow(request, auth_request):
    """Authorizer allowing every request.

    Args:
        request (aiohttp.web.Request): Incoming HTTP request
        auth_request (AuthorizationRequest): Authorization request associated with
            the incoming HTTP request.

    """
    pass


async def always_deny(request, auth_request):
    """Authorizer denying every request.

    Args:
        request (aiohttp.web.Request): Incoming HTTP request
        auth_request (AuthorizationRequest): Authorization request associated with
            the incoming HTTP request.

    Raises:
        aiohttp.web.HTTPForbidden: Always raised

    """
    raise web.HTTPForbidden()


async def rbac(request, auth_request):
    """Role-based access control authorizer.

    The roles of a user are loaded from the database. It checks if any role
    allows the verb on the resource in the namespace. Roles are only
    permissive. There are no denial rules.

    Args:
        request (aiohttp.web.Request): Incoming HTTP request
        auth_request (AuthorizationRequest): Authorization request associated with
            the incoming HTTP request.

    Returns:
        krake.data.core.Role: The role allowing access.

    Raises:
        aiohttp.web.HTTPForbidden: If no role allows access.
    """
    user = request["user"]
    if user == "system:anonymous":
        raise web.HTTPUnauthorized()

    # Load roles of the user
    roles = _fetch_roles(session(request), user)

    # Check if any role grants access
    async for role in roles:
        for rule in role.rules:
            # Check if the API group matches
            if rule.api == auth_request.api or rule.api == "":
                # Check if the requested verb is allowed
                if auth_request.verb in rule.verbs:
                    # Check if the requested resource is allowed
                    if auth_request.resource in rule.resources or "" in rule.resources:
                        # If the resource is not namespaced, grant access
                        if auth_request.namespace is None:
                            return role

                        if (
                            auth_request.namespace in rule.namespaces
                            or "" in rule.namespaces
                        ):
                            return role

    raise web.HTTPForbidden()


def protected(api, resource, verb):
    """Decorator function for aiohttp request handlers performing authorization.

    The returned decorator can be used to wrap a given aiohttp handler and
    call the current authorizer of the application (loaded from the
    ``authorizer`` key of the application). If the authorizer does not raise
    any exception the request is authorized and the wrapped request handler is
    called.

    Example:
        .. code:: python

            from krake.api.auth import protected

            @routes.get("/book/{name}")
            @protected(api="v1", resource="book", verb="get", namespaced=False)
            async def get_resource(request):
                assert "user" in request

    Args:
        api (str): Name of the API group
        resource (str): Name of the resource
        verb (str, krake.data.core.Verb): Verb that should be performed

    Returns:
        callable: Decorator that can be used to wrap a given aiohttp request
        handler.

    """
    # Allow string names for verbs
    if not isinstance(verb, Verb):
        verb = Verb.__members__[verb]

    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            namespace = request.match_info.get("namespace")
            auth_request = AuthorizationRequest(
                api=api, namespace=namespace, resource=resource, verb=verb
            )
            await request.app["authorizer"](request, auth_request)
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator


async def _fetch_roles(db, username):
    """Async generator for all roles associated with the given user.

    Args:
        db (krake.api.database.Session): Database session

    Yields:
        krake.data.core.Role: Role associated with the user.

    """
    roles = set()

    bindings = db.all(RoleBinding)

    # FIXME: Use a cache
    async for binding in bindings:
        if username in binding.users:
            for name in binding.roles:
                if name not in roles:
                    roles.add(name)

                    role = await db.get(Role, name=name)
                    if role is not None:
                        yield role
