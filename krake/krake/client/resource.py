from aiohttp.client_exceptions import ClientPayloadError
from aiohttp.client import ClientTimeout

from krake.data.serializable import deserialize, serialize


class Resource(object):
    """Base class for Krake API client resources. It implements common
    functionality like listing, getting, deleting and watching of REST
    resources.

    Attributes:
        model (type): Serializable type from :mod:`krake.data` that is managed
            by this resource. This attribute is used by :meth:`list`,
            :meth:`get`, :meth:`delete` and :meth:`watch`.
        endpoints (Dict[str, krake.data.Key]): Dictionary of verbs to HTTP
            endpoints.

    Args:
        session (aiohttp.ClientSession): HTTP session used for all HTTP
            communication.
        url (yarl.URL): HTTP URL of the Krake API

    """

    def __init__(self, session, url):
        self.session = session
        self.url = url

    @classmethod
    def ref(cls, **kwargs):
        return cls.endpoints["list"].format_kwargs(**kwargs)

    async def list(self, **kwargs):
        url = self.url.with_path(self.endpoints["list"].format_kwargs(**kwargs))
        resp = await self.session.get(url)
        datas = await resp.json()
        return [deserialize(self.model, data) for data in datas]

    async def get(self, ref=None, **kwargs):
        url = self.url.with_path(self.endpoints["get"].format_kwargs(**kwargs))
        resp = await self.session.get(url)
        data = await resp.json()
        instance = deserialize(self.model, data)
        return instance

    async def get_by_url(self, path):
        url = self.url.with_path(path)
        resp = await self.session.get(url)
        data = await resp.json()
        instance = deserialize(self.model, data)
        return instance

    async def create(self, resource):
        url = self.url.with_path(
            self.endpoints["create"].format_object(resource.metadata)
        )
        resp = await self.session.post(url, json=serialize(resource))
        data = await resp.json()
        return deserialize(self.model, data)

    async def update(self, resource):
        url = self.url.with_path(self.endpoints["get"].format_object(resource.metadata))
        resp = await self.session.put(url, json=serialize(resource))
        data = await resp.json()
        return deserialize(self.model, data)

    async def delete(self, **kwargs):
        url = self.url.with_path(self.endpoints["get"].format_kwargs(**kwargs))
        resp = await self.session.delete(url)
        data = await resp.json()
        return deserialize(self.model, data)

    def watch(self, **kwargs):
        return Watcher(self, **kwargs)


class Watcher(object):
    """Async context manager used by :meth:`Resource.watch`.

    The context manager returns the async generator of resources. On entering
    it is ensured that the watch is created. This means inside the context a
    watch is already established.

    Args:
        resource (Resource): Resource requesting a watch
        **kwargs (dict): Keyword arguments that are used to format the
            ``list`` endpoint.

    """

    def __init__(self, resource, **kwargs):
        self.resource = resource
        self.response = None
        self.timeout = ClientTimeout(sock_read=float("inf"))
        self.url = self.resource.url.with_path(
            self.resource.endpoints["list"].format_kwargs(**kwargs)
        ).with_query("watch")

    async def __aenter__(self):
        self.response = await self.resource.session.get(self.url, timeout=self.timeout)
        return self.watch()

    async def __aexit__(self, *exc):
        await self.response.release()
        self.response = None

    async def watch(self):
        """Async generator yielding instances of the watched resource model

        Yields:
            Deserialized resource model (see :attr:`Resource.model`)

        """
        try:
            async for line in self.response.content:
                if not line:  # EOF
                    return
                if line == b"\n":  # Heartbeat
                    continue

                yield deserialize(self.resource.model, line)

        except ClientPayloadError:
            return
