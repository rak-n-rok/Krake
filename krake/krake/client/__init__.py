from aiohttp import ClientSession
from yarl import URL
import json

from .kubernetes import KubernetesResource


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


# class Client(object):
#     def __init__(self, url, token=None, loop=None):
#         self.loop = loop
#         self.url = URL(url)
#         self.token = token
#         self.session = None

#     async def __aenter__(self):
#         await self.open()
#         return self

#     async def __aexit__(self, *exc):
#         await self.close()

#     async def open(self):
#         if self.session is not None:
#             return
#         headers = {}
#         if self.token:
#             headers["Authorization"] = self.token
#         self.session = ClientSession(
#             headers=headers, loop=self.loop, raise_for_status=True
#         )

#     async def close(self):
#         if self.session is None:
#             return
#         await self.session.close()
#         self.session = None
#         self.kubernetes = None

#     async def list(self, cls):
#         url = self.url.with_path(cls.__url__)
#         resp = await self.session.get(url)
#         datas = await resp.json()
#         return [deserialize(cls, data) for data in datas]

#     async def get(self, cls, id):
#         url = self.url.with_path(f"{cls.__url__}/{id}")
#         resp = await self.session.get(url)
#         data = await resp.json()
#         app = deserialize(cls, data)
#         return app

#     async def create(self, resource):
#         url = self.url.with_path(resource.__url__)
#         resp = await self.session.post(url, json=serialize(resource))
#         data = await resp.json()
#         return deserialize(resource.__class__, data)

#     async def update(self, resource):
#         identity = getattr(resource, resource.__identity__)
#         url = self.url.with_path(f"{resource.__url__}/{identity}")
#         resp = await self.session.put(url, json=serialize(resource))
#         data = await resp.json()
#         return deserialize(resource.__class__, data)

#     async def delete(self, resource):
#         identity = getattr(resource, resource.__identity__)
#         url = self.url.with_path(f"{resource.__url__}/{identity}")
#         resp = await self.session.delete(url)
#         data = await resp.json()
#         return deserialize(resource.__class__, data)

#     async def watch(self, cls):
#         url = self.url.with_path(f"{cls.__url__}/watch")
#         resp = await self.session.get(url)

#         async with resp:
#             async for line in resp.content:
#                 if not line:  # EOF
#                     break
#                 yield deserialize(cls, line)
