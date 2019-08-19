"""This module provides a simple Python client to the Krake HTTP API. It
leverages the same data models as the API server from :mod:`krake.data`.
"""
from aiohttp import ClientSession, TCPConnector
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
