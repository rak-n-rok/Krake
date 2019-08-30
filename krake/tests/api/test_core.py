from operator import attrgetter

from krake.api.app import create_app
from krake.data.core import Role, RoleBinding, RoleList, RoleBindingList, resource_ref

from factories.core import RoleFactory, RoleBindingFactory


# -----------------------------------------------------------------------------
# Roles
# -----------------------------------------------------------------------------


async def test_list_roles(aiohttp_client, config, db):
    data = [RoleFactory() for _ in range(10)]
    for role in data:
        await db.put(role)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/roles")
    assert resp.status == 200

    body = await resp.json()
    roles = RoleList.deserialize(body)

    key = attrgetter("metadata.uid")
    assert sorted(roles.items, key=key) == sorted(data, key=key)


async def test_list_roles_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/core/roles")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "list", namespace=None):
        resp = await client.get("/core/roles")
        assert resp.status == 200


async def test_create_role(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = RoleFactory()

    resp = await client.post("/core/roles", json=data.serialize(readonly=False))
    assert resp.status == 200
    role = Role.deserialize(await resp.json())

    assert role.metadata.created
    assert role.metadata.modified
    assert role.rules == data.rules

    stored, _ = await db.get(Role, name=data.metadata.name)
    assert stored == role


async def test_create_role_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/core/roles")
    assert resp.status == 403

    async with rbac_allow("core", "roles", "create", namespace=None):
        resp = await client.post("/core/roles")
        assert resp.status == 415


async def test_create_role_with_existing_name(aiohttp_client, config, db):
    existing = RoleFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/roles", json=existing.serialize(readonly=False))
    assert resp.status == 409


async def test_get_role(aiohttp_client, config, db):
    role = RoleFactory()
    await db.put(role)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/roles/{role.metadata.name}")
    assert resp.status == 200
    data = Role.deserialize(await resp.json())
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
    data = Role.deserialize(await resp.json())
    assert resource_ref(data) == resource_ref(role)

    deleted, _ = await db.get(Role, name=role.metadata.name)
    assert deleted.metadata.deleted is not None


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

    body = await resp.json()
    received = RoleBindingList.deserialize(body)

    key = attrgetter("metadata.name")
    assert sorted(received.items, key=key) == sorted(bindings, key=key)


async def test_list_role_bindings_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.get("/core/rolebindings")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "list", namespace=None):
        resp = await client.get("/core/rolebindings")
        assert resp.status == 200


async def test_create_role_binding(aiohttp_client, config, db):
    data = RoleBindingFactory()
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/core/rolebindings", json=data.serialize(readonly=False))
    assert resp.status == 200
    binding = RoleBinding.deserialize(await resp.json())

    assert binding.metadata.created
    assert binding.metadata.modified
    assert set(binding.users) == set(data.users)
    assert set(binding.roles) == set(data.roles)

    stored, _ = await db.get(RoleBinding, name=data.metadata.name)
    assert binding == stored


async def test_create_role_binding_rbac(rbac_allow, config, aiohttp_client):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.post("/core/rolebindings")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "create", namespace=None):
        resp = await client.post("/core/rolebindings")
        assert resp.status == 415


async def test_create_role_binding_with_existing_name(aiohttp_client, config, db):
    existing = RoleBindingFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/core/rolebindings", json=existing.serialize(readonly=False)
    )
    assert resp.status == 409


async def test_get_role_binding(aiohttp_client, config, db):
    binding = RoleBindingFactory()
    await db.put(binding)
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get(f"/core/rolebindings/{binding.metadata.name}")
    assert resp.status == 200
    data = RoleBinding.deserialize(await resp.json())
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
    data = RoleBinding.deserialize(await resp.json())
    assert resource_ref(data) == resource_ref(binding)

    deleted, _ = await db.get(RoleBinding, name=binding.metadata.name)
    assert deleted.metadata.deleted is not None


async def test_delete_role_binding_rbac(rbac_allow, aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=dict(config, authorization="RBAC")))

    resp = await client.delete("/core/rolebindings/mybinding")
    assert resp.status == 403

    async with rbac_allow("core", "rolebindings", "delete", namespace=None):
        resp = await client.delete("/core/rolebindings/mybinding")
        assert resp.status == 404
