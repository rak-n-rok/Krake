from operator import attrgetter

from krake.api.app import create_app
from krake.client import Client
from krake.data.core import Role, RoleBinding

from factories.core import RoleFactory, RoleBindingFactory, RoleRuleFactory


async def test_list_roles(aiohttp_server, config, db, loop):
    # Populate database
    data = [RoleFactory(), RoleFactory()]
    for role in data:
        await db.put(role)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        roles = await client.core.role.list()

    key = attrgetter("metadata.name")
    assert sorted(roles, key=key) == sorted(data, key=key)


async def test_create_role(aiohttp_server, config, db, loop):
    data = RoleFactory(metadata__uid=None, status=None)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        received = await client.core.role.create(data)

    assert received.metadata.name == data.metadata.name
    assert received.status.created
    assert received.status.modified
    assert received.rules == data.rules

    stored, _ = await db.get(Role, name=data.metadata.name)
    assert stored == received


async def test_update_role(aiohttp_server, config, db, loop):
    role = RoleFactory()
    await db.put(role)
    role.rules.append(RoleRuleFactory())

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        received = await client.core.role.update(role)

    assert received.rules == role.rules
    assert received.status.created == role.status.created
    assert received.status.modified

    stored, _ = await db.get(Role, name=role.metadata.name)
    assert stored.rules == role.rules
    assert stored.status.created == role.status.created
    assert stored.status.modified


async def test_get_role(aiohttp_server, config, db, loop):
    data = RoleFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        received = await client.core.role.get(name=data.metadata.name)
        assert received == data


async def test_list_rolebindings(aiohttp_server, config, db, loop):
    # Populate database
    data = [RoleBindingFactory(), RoleBindingFactory()]
    for binding in data:
        await db.put(binding)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        roles = await client.core.role_binding.list()

    key = attrgetter("metadata.name")
    assert sorted(roles, key=key) == sorted(data, key=key)


async def test_create_rolebinding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory(metadata__uid=None, status=None)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        received = await client.core.role_binding.create(data)

    assert received.metadata.name == data.metadata.name
    assert received.status.created
    assert received.status.modified
    assert received.users == data.users
    assert received.roles == data.roles

    stored, _ = await db.get(RoleBinding, name=data.metadata.name)
    assert stored == received


async def test_update_rolebinding(aiohttp_server, config, db, loop):
    binding = RoleBindingFactory()
    await db.put(binding)
    binding.users.append("test-user")
    binding.roles.append("test-role")

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        received = await client.core.role_binding.update(binding)

    assert received.users == binding.users
    assert received.roles == binding.roles
    assert received.status.created == binding.status.created
    assert received.status.modified

    stored, _ = await db.get(RoleBinding, name=binding.metadata.name)
    assert stored.users == binding.users
    assert stored.roles == binding.roles
    assert stored.status.created == binding.status.created
    assert stored.status.modified


async def test_get_rolebinding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        received = await client.core.role_binding.get(name=data.metadata.name)
        assert received == data
