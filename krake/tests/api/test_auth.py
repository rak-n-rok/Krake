import ssl

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer as Server
from krake.api.app import create_app
from krake.api.helpers import HttpProblemTitle
from krake.client import Client
from krake.controller import create_ssl_context
from krake.data.config import (
    AuthenticationConfiguration,
    TlsServerConfiguration,
    TlsClientConfiguration,
)


async def test_static_auth(aiohttp_client, config):
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "localhost", "realm": "krake"},
            "static": {"enabled": True, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me")
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == "test-user"


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
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": True, "endpoint": keystone.auth_url},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me", headers={"Authorization": token})
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == keystone.username


@pytest.mark.slow
async def test_keystone_auth_invalid_token(keystone, aiohttp_client, config):
    """Verify with keystone authentication enabled, an invalid token does not allow to
    be authenticated.
    """
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": True, "endpoint": keystone.auth_url},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me", headers={"Authorization": "invalid-token"})
    assert resp.status == 401

    data = await resp.json()
    assert data["title"] == HttpProblemTitle.INVALID_KEYSTONE_TOKEN.name


async def test_keystone_auth_no_token(aiohttp_client, config):
    """Verify that even with keystone authentication enabled, a user does not get
    authenticated if no token has been provided.
    """
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": True, "endpoint": "http://keystone.url"},
            "keycloak": {"enabled": True, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me")
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == "system:anonymous"


@pytest.mark.slow
async def test_keycloak(keycloak):
    """Test the Keycloak fixture."""
    async with ClientSession() as session:
        # Create a new authentication token
        url = (
            f"{keycloak.auth_url}/auth/realms/{keycloak.realm}"
            f"/protocol/openid-connect/token"
        )
        resp = await session.post(
            url,
            data={
                "grant_type": "password",
                "username": keycloak.username,
                "password": keycloak.password,
                "client_id": keycloak.client_id,
                "client_secret": keycloak.client_secret,
            },
        )
        assert resp.status == 200
        data = await resp.json()
        token = data["access_token"]

        url = (
            f"{keycloak.auth_url}/auth/realms/{keycloak.realm}"
            f"/protocol/openid-connect/userinfo"
        )
        resp = await session.post(url, data={"access_token": token})
        data = await resp.json()
        assert data["preferred_username"] == keycloak.username


@pytest.mark.slow
async def test_keycloak_auth(keycloak, aiohttp_client, config):
    """Using the keycloak fixture, test the API's Keycloak authentication."""
    async with ClientSession() as session:
        # Create a new authentication token
        url = (
            f"{keycloak.auth_url}/auth/realms/{keycloak.realm}"
            f"/protocol/openid-connect/token"
        )
        resp = await session.post(
            url,
            data={
                "grant_type": "password",
                "username": keycloak.username,
                "password": keycloak.password,
                "client_id": keycloak.client_id,
                "client_secret": keycloak.client_secret,
            },
        )
        assert resp.status == 200
        data = await resp.json()
        token = data["access_token"]

    # Use the issued token to access Krake API
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {
                "enabled": True,
                "endpoint": keycloak.auth_url,
                "realm": keycloak.realm,
            },
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    # Valid token
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me", headers={"Authorization": token})
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == keycloak.username

    # Invalid token
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me", headers={"Authorization": "SomeInvalidToken"})
    assert resp.status == 401


async def test_keycloak_auth_no_token(aiohttp_client, config):
    """Verify that even with keycloak authentication enabled, a user does not get
    authenticated if no token has been provided.
    """

    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": True, "endpoint": "http://keystone.url"},
            "keycloak": {"enabled": True, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me")
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == "system:anonymous"


async def test_deny_anonymous_requests(aiohttp_client, config):
    authentication = {
        "allow_anonymous": False,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/me")
    assert resp.status == 401


async def test_client_connect_ssl(config, loop, pki):
    server_cert = pki.gencert("api-server")
    client_cert = pki.gencert("client")

    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    tls_config = {
        "enabled": True,
        "client_ca": pki.ca.cert,
        "cert": server_cert.cert,
        "key": server_cert.key,
    }
    config.tls = TlsServerConfiguration.deserialize(tls_config)
    app = create_app(config=config)

    server = Server(app)
    await server.start_server(ssl=app["ssl_context"])
    assert server.scheme == "https"

    client_tls = {
        "enabled": True,
        "client_ca": pki.ca.cert,
        "client_cert": client_cert.cert,
        "client_key": client_cert.key,
    }
    ssl_context = create_ssl_context(TlsClientConfiguration.deserialize(client_tls))

    url = f"https://{server.host}:{server.port}"
    async with Client(url=url, loop=loop, ssl_context=ssl_context) as client:
        resp = await client.session.get(f"{url}/me")
        data = await resp.json()
        assert data["user"] == "client"


async def test_client_anonymous_cert_auth(aiohttp_client, config, pki):
    server_cert = pki.gencert("api-server")

    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    tls_config = {
        "enabled": True,
        "client_ca": pki.ca.cert,
        "cert": server_cert.cert,
        "key": server_cert.key,
    }
    config.tls = TlsServerConfiguration.deserialize(tls_config)

    app = create_app(config=config)
    server = Server(app)
    try:
        await server.start_server(ssl=app["ssl_context"])
        assert server.scheme == "https"

        client = await aiohttp_client(server)
        context = ssl.create_default_context(cafile=pki.ca.cert)
        resp = await client.get("/me", ssl=context)
        data = await resp.json()
        assert data["user"] == "system:anonymous"
    finally:
        await server.close()


async def test_client_cert_auth(aiohttp_client, config, pki):
    server_cert = pki.gencert("api-server")
    client_cert = pki.gencert("test-user")
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    tls_config = {
        "enabled": True,
        "client_ca": pki.ca.cert,
        "cert": server_cert.cert,
        "key": server_cert.key,
    }
    config.tls = TlsServerConfiguration.deserialize(tls_config)

    app = create_app(config=config)
    server = Server(app)
    try:
        await server.start_server(ssl=app["ssl_context"])
        assert server.scheme == "https"

        client = await aiohttp_client(server)
        context = ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH, cafile=pki.ca.cert
        )
        context.load_cert_chain(*client_cert)
        resp = await client.get("/me", ssl=context)
        data = await resp.json()
        assert data["user"] == "test-user"
    finally:
        await server.close()


async def test_allow_anonymous_rbac(aiohttp_client, config):
    """Ensure that with RBAC enabled, an anonymous user is not considered authenticated
    when he/she sends requests for resources.
    """
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)
    config.authorization = "RBAC"

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/roles")
    assert resp.status == 401


async def test_always_deny(aiohttp_client, config):
    """Ensure that the "always-deny" authorization mode prevents accessing resources
    even if anonymous users are allowed.
    """
    authentication = {
        "allow_anonymous": True,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)
    config.authorization = "always-deny"

    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/core/roles")
    assert resp.status == 403
