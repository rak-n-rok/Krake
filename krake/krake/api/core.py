"""This module comprises request handlers forming the HTTP REST API for
the core functionality of Krake.
"""
import logging
from datetime import datetime
from uuid import uuid4
from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs

from krake.data.serializable import serialize
from krake.data.core import (
    Role,
    RoleRule,
    RoleStatus,
    RoleBinding,
    RoleBindingStatus,
    CoreMetadata,
)
from . import __version__ as version
from .auth import protected
from .helpers import session, json_error, load


logger = logging.getLogger(__name__)
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


# -----------------------------------------------------------------------------
# Roles
# -----------------------------------------------------------------------------


@routes.get("/core/roles")
@protected(api="core", resource="roles", verb="list", namespaced=False)
async def list_roles(request):
    roles = [role async for role, _ in session(request).all(Role)]
    return web.json_response([serialize(role) for role in roles])


@routes.post("/core/roles")
@protected(api="core", resource="roles", verb="create", namespaced=False)
@use_kwargs(
    {
        "name": fields.String(required=True),
        "rules": fields.List(fields.Nested(RoleRule.Schema), required=True),
    }
)
async def create_role(request, name, rules):
    # Ensure that a role with the same name does not already exists
    role, _ = await session(request).get(Role, name=name)
    if role is not None:
        raise json_error(
            web.HTTPBadRequest, {"reason": f"Role {name!r} already exists"}
        )

    now = datetime.now()
    role = Role(
        metadata=CoreMetadata(name=name, uid=str(uuid4())),
        rules=rules,
        status=RoleStatus(created=now, modified=now),
    )
    await session(request).put(role)
    logger.info("Created role %r", role.metadata.uid)

    return web.json_response(serialize(role))


@routes.get("/core/roles/{name}")
@protected(api="core", resource="roles", verb="get", namespaced=False)
@load("role", Role, namespaced=False)
async def get_role(request, role):
    return web.json_response(serialize(role))


@routes.delete("/core/roles/{name}")
@protected(api="core", resource="roles", verb="delete", namespaced=False)
@load("role", Role, namespaced=False)
async def delete_role(request, role):
    await session(request).delete(role)
    return web.Response(status=200)


# -----------------------------------------------------------------------------
# Role Bindings
# -----------------------------------------------------------------------------


@routes.get("/core/rolebindings")
@protected(api="core", resource="rolebindings", verb="list", namespaced=False)
async def list_role_bindings(request):
    bindings = [binding async for binding, _ in session(request).all(RoleBinding)]
    return web.json_response([serialize(binding) for binding in bindings])


@routes.post("/core/rolebindings")
@protected(api="core", resource="rolebindings", verb="create", namespaced=False)
@use_kwargs(
    {
        "name": fields.String(required=True),
        "users": fields.List(fields.String, required=True),
        "roles": fields.List(fields.String, required=True),
    }
)
async def create_role_binding(request, name, users, roles):
    # Ensure that a binding with the same name does not already exists
    binding, _ = await session(request).get(RoleBinding, name=name)
    if binding is not None:
        raise json_error(
            web.HTTPBadRequest, {"reason": f"RoleBinding {name!r} already exists"}
        )

    now = datetime.now()
    binding = RoleBinding(
        metadata=CoreMetadata(name=name, uid=str(uuid4())),
        users=users,
        roles=roles,
        status=RoleBindingStatus(created=now, modified=now),
    )
    await session(request).put(binding)
    logger.info("Created binding %r", binding.metadata.uid)

    return web.json_response(serialize(binding))


@routes.get("/core/rolebindings/{name}")
@protected(api="core", resource="rolebindings", verb="get", namespaced=False)
@load("binding", RoleBinding, namespaced=False)
async def get_role_binding(request, binding):
    return web.json_response(serialize(binding))


@routes.delete("/core/rolebindings/{name}")
@protected(api="core", resource="rolebindings", verb="delete", namespaced=False)
@load("binding", RoleBinding, namespaced=False)
async def delete_role_binding(request, binding):
    await session(request).delete(binding)
    return web.Response(status=200)
