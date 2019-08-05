import ssl
import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer as Server
from krake.api.app import create_app


async def test_static_auth(aiohttp_client, config):
    client = await aiohttp_client(
        create_app(
            config=dict(
                config,
                authentication={"strategy": {"kind": "static", "name": "test-user"}},
            )
        )
    )
    resp = await client.get("/me")
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == "test-user"


@pytest.mark.require_module("keystone")
@pytest.mark.slow
async def test_keystone(keystone):
    async with ClientSession() as session:
        # Create a new authentication token
        resp = await session.post(
            f"{keystone.auth_url}/auth/tokens",
            json={
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": keystone.username,
                                "domain": {"name": keystone.user_domain_name},
                                "password": keystone.password,
                            }
                        },
                    },
                    "scope": {
                        "project": {
                            "name": keystone.project_name,
                            "domain": {"name": keystone.project_domain_name},
                        }
                    },
                }
            },
        )
        assert resp.status == 201
        token = resp.headers.get("X-Subject-Token")
        data = await resp.json()

        # Fetch token information
        resp = await session.get(
            f"{keystone.auth_url}/auth/tokens",
            headers={"X-Auth-Token": token, "X-Subject-Token": token},
        )
        assert resp.status == 200
        _data = await resp.json()
        assert data == _data

        # Revoke authentication token
        resp = await session.delete(
            f"{keystone.auth_url}/auth/tokens",
            headers={"X-Auth-Token": token, "X-Subject-Token": token},
        )
        assert resp.status == 204


@pytest.mark.require_module("keystone")
@pytest.mark.slow
async def test_keystone_auth(keystone, aiohttp_client, config):
    async with ClientSession() as session:
        # Issue Keystone token
        resp = await session.post(
            f"{keystone.auth_url}/auth/tokens",
            json={
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": keystone.username,
                                "domain": {"name": keystone.user_domain_name},
                                "password": keystone.password,
                            }
                        },
                    },
                    "scope": {
                        "project": {
                            "name": keystone.project_name,
                            "domain": {"name": keystone.project_domain_name},
                        }
                    },
                }
            },
        )
        assert resp.status == 201
        token = resp.headers.get("X-Subject-Token")

    # Use the issued token to access Krake API
    client = await aiohttp_client(
        create_app(
            config=dict(
                config,
                authentication={
                    "strategy": {"kind": "keystone", "endpoint": keystone.auth_url}
                },
            )
        )
    )
    resp = await client.get("/me", headers={"Authorization": token})
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == keystone.username


async def test_deny_anonymous_requests(aiohttp_client, config):
    client = await aiohttp_client(
        create_app(dict(config, authentication={"allow_anonymous": False}))
    )
    resp = await client.get("/me")
    assert resp.status == 401


@pytest.mark.require_executable("cfssl")
async def test_client_cert_auth(aiohttp_client, config, pki):
    server_cert = pki.gencert("api-server")
    client_cert = pki.gencert("test-user")

    app = create_app(
        config=dict(
            config,
            authentication={"strategy": None},
            tls={
                "client_ca": pki.ca.cert,
                "cert": server_cert.cert,
                "key": server_cert.key,
            },
        )
    )
    server = Server(app)
    try:
        await server.start_server(ssl=app["ssl_context"])
        assert server.scheme == "https"

        client = await aiohttp_client(server)

        # No client certificate
        context = ssl.create_default_context(cafile=pki.ca.cert)
        resp = await client.get("/me", ssl=context)
        data = await resp.json()
        assert data["user"] == "system:anonymous"

        # Authenticate with client certificate
        context = ssl.create_default_context(
            purpose=ssl.Purpose.CLIENT_AUTH, cafile=pki.ca.cert
        )
        context.load_cert_chain(*client_cert)
        resp = await client.get("/me", ssl=context)
        data = await resp.json()
        assert data["user"] == "test-user"
    finally:
        await server.close()
