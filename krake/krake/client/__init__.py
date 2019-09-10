"""This module provides a simple Python client to the Krake HTTP API. It
leverages the same data models as the API server from :mod:`krake.data`.
"""
from aiohttp import ClientSession, TCPConnector
from yarl import URL

from .core import CoreAPI
from .kubernetes import KubernetesAPI


class Client(object):
    """Simple async Python client for the Krake HTTP API.

    REST resources are structured with attributes. For example, all Kubernetes
    related resources are accessible via the ``.kubernetes`` attribute.

    The client implements the asynchronous context manager protocol used to
    handle opening and closing the internal HTTP session.

    Example:
        .. code:: python

            from krake.client import Client

            async with Client("http://localhost:8080") as client:
                id = "0520e107-519b-4aed-8ab0-8e6c03134ef8"
                await client.kubernetes.application.get(id)

    Attributes:
        core (.core.CoreAPI): API or all core resources
        kubernetes (.kubernetes.KubernetesAPI): API for all Kubernetes
            resources

    """

    def __init__(self, url, loop=None, ssl_context=None):
        self.loop = loop
        self.url = URL(url)
        self.session = None
        self.kubernetes = None
        self.core = None
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

        headers = {}
        self.session = ClientSession(
            headers=headers, loop=self.loop, raise_for_status=True, connector=connector
        )

        self.core = CoreAPI(session=self.session, url=self.url)
        self.kubernetes = KubernetesAPI(session=self.session, url=self.url)

    async def close(self):
        """Close the internal HTTP session and remove all resource attributes."""
        if self.session is None:
            return
        self.kubernetes = None
        await self.session.close()
        self.session = None
