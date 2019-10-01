from operator import attrgetter
import pytest
from aiohttp.test_utils import TestServer as Server

from krake.api.app import create_app
from krake.client import Client
from krake.controller import create_ssl_context
from krake.client.core import CoreApi
from krake.data.core import ListMetadata, Role, RoleBinding, resource_ref

from factories.core import RoleFactory, RoleBindingFactory, RoleRuleFactory


async def test_list_roles(aiohttp_server, config, db, loop):
    # Populate database
    data = [RoleFactory(), RoleFactory()]
    for role in data:
        await db.put(role)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        roles = await core_api.list_roles()

    assert roles.api == "core"
    assert roles.kind == "RoleList"
    assert isinstance(roles.metadata, ListMetadata)

    key = attrgetter("metadata.name")
    assert sorted(roles.items, key=key) == sorted(data, key=key)


async def test_create_role(aiohttp_server, config, db, loop):
    data = RoleFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_role(data)

    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified
    assert received.rules == data.rules

    stored = await db.get(Role, name=data.metadata.name)
    assert stored == received


async def test_update_role(aiohttp_server, config, db, loop):
    role = RoleFactory()
    await db.put(role)
    role.rules.append(RoleRuleFactory())

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_role(name=role.metadata.name, body=role)

    assert received.rules == role.rules
    assert received.metadata.created == role.metadata.created
    assert received.metadata.modified

    stored = await db.get(Role, name=role.metadata.name)
    assert stored.rules == role.rules
    assert stored.metadata.created == role.metadata.created
    assert stored.metadata.modified


async def test_read_role(aiohttp_server, config, db, loop):
    data = RoleFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_role(name=data.metadata.name)
        assert received == data


async def test_delete_role(aiohttp_server, config, db, loop):
    data = RoleFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_role(name=data.metadata.name)

        assert resource_ref(received) == resource_ref(data)

    stored = await db.get(Role, name=data.metadata.name)
    assert stored.metadata.deleted is not None


async def test_list_rolebindings(aiohttp_server, config, db, loop):
    # Populate database
    data = [RoleBindingFactory(), RoleBindingFactory()]
    for binding in data:
        await db.put(binding)

    # Start API server
    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        bindings = await core_api.list_role_bindings()

    assert bindings.api == "core"
    assert bindings.kind == "RoleBindingList"
    assert isinstance(bindings.metadata, ListMetadata)

    key = attrgetter("metadata.name")
    assert sorted(bindings.items, key=key) == sorted(data, key=key)


async def test_create_rolebinding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory()

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.create_role_binding(data)

    assert received.metadata.name == data.metadata.name
    assert received.metadata.namespace is None
    assert received.metadata.created
    assert received.metadata.modified
    assert received.users == data.users
    assert received.roles == data.roles

    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored == received


async def test_update_rolebinding(aiohttp_server, config, db, loop):
    binding = RoleBindingFactory()
    await db.put(binding)
    binding.users.append("test-user")
    binding.roles.append("test-role")

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.update_role_binding(
            name=binding.metadata.name, body=binding
        )

    assert received.users == binding.users
    assert received.roles == binding.roles
    assert received.metadata.created == binding.metadata.created
    assert received.metadata.modified

    stored = await db.get(RoleBinding, name=binding.metadata.name)
    assert stored.users == binding.users
    assert stored.roles == binding.roles
    assert stored.metadata.created == binding.metadata.created
    assert stored.metadata.modified


async def test_get_rolebinding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.read_role_binding(name=data.metadata.name)
        assert received == data


async def test_delete_rolebinding(aiohttp_server, config, db, loop):
    data = RoleBindingFactory()
    await db.put(data)

    server = await aiohttp_server(create_app(config=config))

    async with Client(url=f"http://{server.host}:{server.port}", loop=loop) as client:
        core_api = CoreApi(client)
        received = await core_api.delete_role_binding(name=data.metadata.name)
        assert resource_ref(received) == resource_ref(data)

    stored = await db.get(RoleBinding, name=data.metadata.name)
    assert stored.metadata.deleted is not None


@pytest.mark.require_executable("cfssl")
async def test_connect_ssl(aiohttp_server, config, loop, pki):
    server_cert = pki.gencert("api-server")
    client_cert = pki.gencert("client")

    app = create_app(
        config=dict(
            config,
            authentication={
                "allow_anonymous": True,
                "strategy": {
                    "keystone": {"enabled": False, "endpoint": "localhost"},
                    "static": {"enabled": False, "name": "test-user"},
                },
            },
            tls={
                "enabled": True,
                "client_ca": pki.ca.cert,
                "cert": server_cert.cert,
                "key": server_cert.key,
            },
        )
    )

    server = Server(app)
    await server.start_server(ssl=app["ssl_context"])
    assert server.scheme == "https"

    client_tls = {
        "enabled": True,
        "client_ca": pki.ca.cert,
        "client_cert": client_cert.cert,
        "client_key": client_cert.key,
    }
    ssl_context = create_ssl_context(client_tls)

    url = f"https://{server.host}:{server.port}"
    async with Client(url=url, loop=loop, ssl_context=ssl_context) as client:
        resp = await client.session.get(f"{url}/me")
        data = await resp.json()
        assert data["user"] == "client"
