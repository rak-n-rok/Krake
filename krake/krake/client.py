from aiohttp import ClientSession
from yarl import URL
import json
from krake.data.serializable import deserialize, serialize
from krake.data.kubernetes import Application


class Client(object):
    def __init__(self, url, token=None, loop=None):
        self.loop = loop
        self.url = URL(url)
        self.token = token
        self.session = None
        self.kubernetes = None

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def open(self):
        if self.session is not None:
            return
        headers = {}
        if self.token:
            headers["Authorization"] = self.token
        self.session = ClientSession(
            headers=headers, loop=self.loop, raise_for_status=True
        )
        self.kubernetes = KubernetesResource(session=self.session, url=self.url)

    async def close(self):
        if self.session is None:
            return
        await self.session.close()
        self.session = None
        self.kubernetes = None
