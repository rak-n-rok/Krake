from krake.api import __version__ as version
from krake.api.app import create_app


async def test_index(aiohttp_client, db, config):
    client = await aiohttp_client(create_app(config=config))
    resp = await client.get("/")
    assert resp.status == 200
    data = await resp.json()
    assert data["version"] == version
