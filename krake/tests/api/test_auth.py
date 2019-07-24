from aiohttp import ClientSession
from krake.api.app import create_app


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
                config, auth={"kind": "keystone", "endpoint": keystone.auth_url}
            )
        )
    )
    resp = await client.get("/", headers={"Authorization": token})
    assert resp.status == 200
