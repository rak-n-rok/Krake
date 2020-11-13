"""This module provides a simple Python client to the Krake HTTP API. It
leverages the same data models as the API server from :mod:`krake.data`.
"""
import json

from aiohttp import ClientSession, TCPConnector, ClientTimeout, ClientPayloadError
from krake.data.core import WatchEvent
from yarl import URL


class Client(object):
    """Simple async Python client for the Krake HTTP API.

    The specific APIs are implemented in separate classes. Each API object
    requires an :class:`Client` instance to interface the HTTP REST API.

    The client implements the asynchronous context manager protocol used to
    handle opening and closing the internal HTTP session.

    Example:
        .. code:: python

            from krake.client import Client
            from krake.client.core import CoreApi

            async with Client("http://localhost:8080") as client:
                core_api = CoreApi(client)
                role = await core_api.read_role(name="reader")

    """

    def __init__(self, url, loop=None, ssl_context=None):
        self.loop = loop
        self.url = URL(url)
        self.session = None
        self.ssl_context = ssl_context

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def open(self):
        """Open the internal HTTP session and initializes all resource
        attributes.
        """
        if self.session is not None:
            return

        connector = None
        if self.ssl_context:
            connector = TCPConnector(ssl_context=self.ssl_context)

        self.session = ClientSession(
            loop=self.loop, raise_for_status=True, connector=connector
        )

    async def close(self):
        """Close the internal HTTP session and remove all resource attributes."""
        if self.session is None:
            return
        await self.session.close()
        self.session = None


class Watcher(object):
    """Async context manager used by ``watch_*()`` methods of :class:`ClientApi`.

    The context manager returns the async generator of resources. On entering
    it is ensured that the watch is created. This means inside the context a
    watch is already established.

    Args:
        session (aiohttp.ClientSession): HTTP session that is used to access
            the REST API.
        url (str): URL for the watch request
        model (type): Type that will be used to deserialize
            :attr:`krake.data.core.WatchEvent.object`

    """

    def __init__(self, session, url, model):
        self.session = session
        self.url = url
        self.model = model
        self.response = None
        self.timeout = ClientTimeout(sock_read=None)

    async def __aenter__(self):
        self.response = await self.session.get(self.url, timeout=self.timeout)
        return self.watch()

    async def __aexit__(self, *exc):
        await self.response.release()
        self.response = None

    async def watch(self):
        """Async generator yielding watch events

        Yields:
            krake.data.core.WatchEvent: Watch events where ``object`` is
                already deserialized correctly according to the API
                definition (see ``model`` argument)

        """
        try:
            async for line in self.response.content:
                if not line:  # EOF
                    return
                if line == b"\n":  # Heartbeat
                    continue

                event = WatchEvent.deserialize(json.loads(line))
                event.object = self.model.deserialize(event.object)

                yield event

        except ClientPayloadError:
            return


class ApiClient(object):
    """Base class for all clients of a specific Krake API.

    Attributes:
        client (krake.client.Client): the lower-level client to use to create the actual
            connections.
        plurals (dict[str, str]): contains the name of the resources handled by the
            current API and their corresponding names in plural:
            "<name_in_singular>": "<name_in_plural>"

    Args:
        client (krake.client.Client): client to use for the HTTP communications.

    """

    plurals = {}

    def __init__(self, client):
        self.client = client
