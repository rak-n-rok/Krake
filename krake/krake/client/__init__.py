"""This module provides a simple Python client to the Krake HTTP API. It
leverages the same data models as the API server from :mod:`krake.data`.
"""
import ssl
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

    def __init__(self, url, loop=None, ssl_cert=None, ssl_key=None, client_ca=None):
        self.loop = loop
        self.url = URL(url)
        self.session = None
        self.kubernetes = None
        self.core = None
        self.ssl_cert = ssl_cert
        self.ssl_key = ssl_key
        self.client_ca = client_ca

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
        if self.ssl_cert and self.ssl_key:
            ssl_context = create_ssl_context(
                self.ssl_cert, self.ssl_key, self.client_ca
            )
            connector = TCPConnector(ssl_context=ssl_context)

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


def create_ssl_context(cert, key, client_ca=None):
    """
    From a certificate, create an SSL Context that can be used on the client side
    for communicating with a Server.

    Args:
        cert (str): path to the certificate file
        key (str): path to the key file of the certificate
        client_ca (str, optional): path to the "certification authority" certificates

    Returns:
        ssl.SSLContext: a default SSL Context tweaked with the given certificate
        elements

    """
    ssl_context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    ssl_context.verify_mode = ssl.CERT_OPTIONAL

    ssl_context.load_cert_chain(certfile=cert, keyfile=key)

    # Load authorities for client certificates.
    if client_ca:
        ssl_context.load_verify_locations(cafile=client_ca)

    return ssl_context
