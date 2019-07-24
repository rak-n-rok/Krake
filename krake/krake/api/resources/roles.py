import logging
from uuid import uuid4
from datetime import datetime
from aiohttp import web
from webargs import fields
from webargs.aiohttpparser import use_kwargs

from krake.data.serializable import serialize
from krake.data.system import (
    Role,
    RoleRule,
    RoleStatus,
    RoleBinding,
    RoleBindingStatus,
    SystemMetadata,
)
from ..helpers import session, json_error, load
from ..auth import protected


logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


# -----------------------------------------------------------------------------
# Roles
# -----------------------------------------------------------------------------


@routes.get("/roles")
@protected(resource="roles", verb="list", namespaced=False)
async def list_roles(request):
    roles = [role async for role, _ in session(request).all(Role)]
    return web.json_response([serialize(role) for role in roles])


@routes.post("/roles")
@protected(resource="roles", verb="create", namespaced=False)
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
        metadata=SystemMetadata(name=name, uid=str(uuid4())),
        rules=rules,
        status=RoleStatus(created=now, modified=now),
    )
    await session(request).put(role)
    logger.info("Created role %r", role.metadata.uid)

    return web.json_response(serialize(role))


@routes.get("/roles/{name}")
@protected(resource="roles", verb="get", namespaced=False)
@load("role", Role, namespaced=False)
async def get_role(request, role):
    return web.json_response(serialize(role))


@routes.delete("/roles/{name}")
@protected(resource="roles", verb="delete", namespaced=False)
@load("role", Role, namespaced=False)
async def delete_role(request, role):
    await session(request).delete(role)
    return web.Response(status=200)


# -----------------------------------------------------------------------------
# Role Bindings
# -----------------------------------------------------------------------------


@routes.get("/rolebindings")
@protected(resource="rolebindings", verb="list", namespaced=False)
async def list_role_bindings(request):
    bindings = [binding async for binding, _ in session(request).all(RoleBinding)]
    return web.json_response([serialize(binding) for binding in bindings])


@routes.post("/rolebindings")
@protected(resource="rolebindings", verb="create", namespaced=False)
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
        metadata=SystemMetadata(name=name, uid=str(uuid4())),
        users=users,
        roles=roles,
        status=RoleBindingStatus(created=now, modified=now),
    )
    await session(request).put(binding)
    logger.info("Created binding %r", binding.metadata.uid)

    return web.json_response(serialize(binding))


@routes.get("/rolebindings/{name}")
@protected(resource="rolebindings", verb="get", namespaced=False)
@load("binding", RoleBinding, namespaced=False)
async def get_role_binding(request, binding):
    return web.json_response(serialize(binding))


@routes.delete("/rolebindings/{name}")
@protected(resource="rolebindings", verb="delete", namespaced=False)
@load("binding", RoleBinding, namespaced=False)
async def delete_role_binding(request, binding):
    await session(request).delete(binding)
    return web.Response(status=200)
