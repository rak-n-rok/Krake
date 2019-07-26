import re
from operator import attrgetter

from krake.data import serialize, deserialize
from krake.api.app import create_app
from krake.data.core import Role, RoleBinding

from factories.core import RoleFactory, RoleRuleFactory, RoleBindingFactory


uuid_re = re.compile(
    r"^[0-9A-F]{8}-[0-9A-F]{4}-[4][0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$",
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# Roles
# -----------------------------------------------------------------------------


async def test_list_roles(aiohttp_client, config, db):
    roles = [RoleFactory() for _ in range(10)]
    for role in roles:
        await db.put(role)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/roles")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(Role, item) for item in data]

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(roles, key=key)


async def test_list_roles_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/core/roles")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "list", namespace=None):
        resp = await client.get("/core/roles")
        assert resp.status == 200


async def test_create_role(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    rules = [RoleRuleFactory() for _ in range(2)]

    resp = await client.post(
        "/core/roles", json={"rules": serialize(rules), "name": "test-role"}
    )
    assert resp.status == 200
    data = await resp.json()

    assert uuid_re.match(data["metadata"]["uid"]) is not None

    role, rev = await db.get(Role, name=data["metadata"]["name"])
    assert rev is not None
    assert rev.version == 1
    assert role.rules == rules


async def test_create_role_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/core/roles")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "create", namespace=None):
        resp = await client.post("/core/roles")
        assert resp.status == 422


async def test_create_role_with_existing_name(aiohttp_client, config, db):
    existing = RoleFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/roles", json={"rules": [], "name": "existing"})
    assert resp.status == 400


async def test_get_role(aiohttp_client, config, db):
    role = RoleFactory()
    await db.put(role)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/roles/{role.metadata.name}")
    assert resp.status == 200
    data = deserialize(Role, await resp.json())
    assert role == data


async def test_get_role_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/core/roles/myrole")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "get", namespace=None):
        resp = await client.get("/core/roles/myrole")
        assert resp.status == 404


async def test_delete_role(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create role
    role = RoleFactory()
    await db.put(role)

    # Delete role
    resp = await client.delete(f"/core/roles/{role.metadata.name}")
    assert resp.status == 200

    deleted, _ = await db.get(Role, name=role.metadata.name)
    assert deleted is None


async def test_delete_role_rbac(rbac_allow, aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/core/roles/myrole")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "delete", namespace=None):
        resp = await client.delete("/core/roles/myrole")
        assert resp.status == 404


# -----------------------------------------------------------------------------
# Role Bindings
# -----------------------------------------------------------------------------


async def test_list_role_bindings(aiohttp_client, config, db):
    bindings = [RoleBindingFactory() for _ in range(10)]
    for binding in bindings:
        await db.put(binding)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/rolebindings")
    assert resp.status == 200

    data = await resp.json()
    received = [deserialize(RoleBinding, item) for item in data]

    key = attrgetter("metadata.uid")
    assert sorted(received, key=key) == sorted(bindings, key=key)


async def test_list_role_bindings_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/core/rolebindings")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "list", namespace=None):
        resp = await client.get("/core/rolebindings")
        assert resp.status == 200


async def test_create_role_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    users = RoleBindingFactory().users
    roles = RoleBindingFactory().roles

    resp = await client.post(
        "/core/rolebindings",
        json={"users": users, "roles": roles, "name": "test-binding"},
    )
    assert resp.status == 200
    data = await resp.json()

    assert uuid_re.match(data["metadata"]["uid"]) is not None

    binding, rev = await db.get(RoleBinding, name=data["metadata"]["name"])
    assert rev is not None
    assert rev.version == 1
    assert set(binding.users) == set(users)
    assert set(binding.roles) == set(roles)


async def test_create_role_binding_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/core/rolebindings")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "create", namespace=None):
        resp = await client.post("/core/rolebindings")
        assert resp.status == 422


async def test_create_role_binding_with_existing_name(aiohttp_client, config, db):
    existing = RoleBindingFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/core/rolebindings", json={"users": [], "roles": [], "name": "existing"}
    )
    assert resp.status == 400


async def test_get_role_binding(aiohttp_client, config, db):
    binding = RoleBindingFactory()
    await db.put(binding)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/rolebindings/{binding.metadata.name}")
    assert resp.status == 200
    data = deserialize(RoleBinding, await resp.json())
    assert binding == data


async def test_get_role_binding_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/core/rolebindings/mybinding")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "get", namespace=None):
        resp = await client.get("/core/rolebindings/mybinding")
        assert resp.status == 404


async def test_delete_role_binding(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    # Create binding
    binding = RoleBindingFactory()
    await db.put(binding)

    # Delete binding
    resp = await client.delete(f"/core/rolebindings/{binding.metadata.name}")
    assert resp.status == 200

    deleted, _ = await db.get(Role, name=binding.metadata.name)
    assert deleted is None


async def test_delete_role_binding_rbac(rbac_allow, aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/core/rolebindings/mybinding")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "delete", namespace=None):
        resp = await client.delete("/core/rolebindings/mybinding")
        assert resp.status == 404
