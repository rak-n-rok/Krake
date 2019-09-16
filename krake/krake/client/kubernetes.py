from aiohttp.client_exceptions import ClientPayloadError

from krake.data.serializable import deserialize, serialize
from krake.data.kubernetes import Application, Cluster


class KubernetesResource(object):
    def __init__(self, session, url):
        self.application = ApplicationResource(session, url)
        self.cluster = ClusterResource(session, url)


class ApplicationResource(object):
    model = Application

    def __init__(self, session, url):
        self.session = session
        self.url = url

    async def list(self):
        url = self.url.with_path(self.model.__url__)
        resp = await self.session.get(url)
        datas = await resp.json()
        return [deserialize(self.model, data) for data in datas]

    async def get(self, id):
        url = self.url.with_path(f"{self.model.__url__}/{id}")
        resp = await self.session.get(url)
        data = await resp.json()
        app = deserialize(self.model, data)
        return app

    async def create(self, manifest):
        url = self.url.with_path(self.model.__url__)
        resp = await self.session.post(url, json={"manifest": manifest})
        data = await resp.json()
        return deserialize(self.model, data)

    async def update(self, id, manifest):
        url = self.url.with_path(f"{self.model.__url__}/{id}")
        resp = await self.session.put(url, json={"manifest": manifest})
        data = await resp.json()
        return deserialize(self.model, data)

    async def update_status(self, id, status):
        url = self.url.with_path(f"{self.model.__url__}/{id}/status")
        resp = await self.session.put(url, json=serialize(status))
        data = await resp.json()
        return deserialize(status.__class__, data)

    async def delete(self, id):
        url = self.url.with_path(f"{self.model.__url__}/{id}")
        resp = await self.session.delete(url)
        data = await resp.json()
        return deserialize(self.model, data)

    async def watch(self):
        url = self.url.with_path(f"{self.model.__url__}/watch")
        resp = await self.session.get(url)

        async with resp:
            try:
                async for line in resp.content:
                    if not line:  # EOF
                        break
                    yield deserialize(self.model, line)
            except ClientPayloadError:
                return


class ClusterResource(object):
    model = Cluster

    def __init__(self, session, url):
        self.session = session
        self.url = url

    async def list(self):
        url = self.url.with_path(self.model.__url__)
        resp = await self.session.get(url)
        datas = await resp.json()
        return [deserialize(self.model, data) for data in datas]

    async def get(self, id):
        url = self.url.with_path(f"{self.model.__url__}/{id}")
        resp = await self.session.get(url)
        data = await resp.json()
        app = deserialize(self.model, data)
        return app

    async def watch(self):
        url = self.url.with_path(f"{self.model.__url__}/watch")
        resp = await self.session.get(url)

        async with resp:
            async for line in resp.content:
                if not line:  # EOF
                    break
                yield deserialize(self.model, line)
