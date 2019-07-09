"""Simple helper functions that are used by the HTTP endpoints."""
import asyncio
import json
from functools import wraps
from aiohttp import web


def json_error(exc, content):
    """Create an aiohttp exception with JSON body.

    Args:
        exc (type): aiohttp exception class
        content (object): JSON serializable object

    Returns:
        Instance of the exception with JSON-serialized content as body
    """
    return exc(text=json.dumps(content), content_type="application/json")


def session(request):
    """Load the database session for a given aiohttp request

    Internally, it just returns the value that was assigned by
    func:`krake.middlewares.database`.

    Args:
        request (aiohttp.web.Request): HTTP request

    Returns:
        krake.database.Session: Database session for the given request
    """
    return request["db"]


def protected(handler):
    """Decorator for aiohttp request handlers checking if an authenticated
    user exists for a given request.

    It is the responsibility of authentication middlewares to load and set the
    ``user`` key of the request object.

    Example:
        .. code:: python

            from krake.api.helpers import protected

            @routes.get("/resource/{name}")
            @protected
            async def get_resource(request):
                assert "user" in request

    Args:
        handler (coroutine): aiohttp request handler

    Returns:
        Wrapped aiohttp request handler raising an HTTP 401 Unauthorized error
        of no ``user`` key exists in the request object.

    """

    @wraps(handler)
    async def wrapper(request, *args, **kwargs):
        if "user" not in request:
            raise web.HTTPUnauthorized()
        return await handler(request, *args, **kwargs)

    return wrapper


class Heartbeat(object):
    """Asyncronous context manager for heatbeating long running HTTP responses.

    Writes newlines to the response body in a given heartbeat interval. If
    ``interval`` is set to 0, no heartbeat will be sent.

    Args:
        response (aiohttp.web.StreamResponse): Prepared HTTP response with
            chunked encoding
        interval (int, float, optional): Heartbeat interval in seconds.
            Default: 10 seconds.
        loop (asyncio.AbstractEventLoop, optional): Event loop

    Raises:
        ValueError: If the response is not prepared or not chunk encoded

    Example:
        .. code:: python

            import asyncio
            from aiohttp import web

            from krake.helpers import Heartbeat


            async def handler(request):
                # Prepare streaming response
                resp = web.StreamResponse()
                resp.enable_chunked_encoding()
                await resp.prepare(request)

                async with Heartbeat(resp):
                    while True:
                        await resp.write(b"spam\\n")
                        await asyncio.sleep(120)

    """

    def __init__(self, response, interval=None, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        if interval is None:
            interval = 10

        if not response.prepared:
            raise ValueError("Response must be prepared")

        if not response.chunked:
            raise ValueError("Response must be chunk encoded")

        self.loop = loop
        self.interval = interval
        self.response = response
        self.task = None

    async def __aenter__(self):
        assert self.task is None
        if self.interval:
            self.task = self.loop.create_task(self.heartbeat())
        return self

    async def __aexit__(self, *exc):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

            self.task = None

    async def heartbeat(self):
        """Indefinitly write a new line to the response body and sleep for
        :attr:`interval`.
        """
        while True:
            await asyncio.sleep(self.interval, loop=self.loop)
            await self.response.write(b"\n")
