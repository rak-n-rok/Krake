from aiohttp.client_exceptions import ClientPayloadError

from krake.data.serializable import deserialize


class Resource(object):
    """Base class for Krake API client resources. It implements common
    functionality like listing, getting, deleting and watching of REST
    resources.

    Attributes:
        model (type): Serializable type from :mod:`krake.data` that is managed
            by this resource. This attribute is used by :meth:`list`,
            :meth:`get`, :meth:`delete` and :meth:`watch`.

    Args:
        session (aiohttp.ClientSession): HTTP session used for all HTTP
            communication.
        url (str): HTTP URL of the Krake API

    """

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
                        return
                    yield deserialize(self.model, line)
            except ClientPayloadError:
                return
