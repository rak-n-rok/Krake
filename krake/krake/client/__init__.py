"""This module provides a simple Python client to the Krake HTTP API. It
leverages the same data models as the API server from :mod:`krake.data`.
"""
from aiohttp import ClientSession
from yarl import URL

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
        kubernetes (.kubernetes.KubernetesAPI): API for all Kubernetes
            resources

    """

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
        """Open the internal HTTP session and initializes all resource
        attributes.
        """
        if self.session is not None:
            return
        headers = {}
        if self.token:
            headers["Authorization"] = self.token
        self.session = ClientSession(
            headers=headers, loop=self.loop, raise_for_status=True
        )
        self.kubernetes = KubernetesAPI(session=self.session, url=self.url)

    async def close(self):
        """Close the internal HTTP session and remove all resource attributes."""
        if self.session is None:
            return
        self.kubernetes = None
        await self.session.close()
        self.session = None
