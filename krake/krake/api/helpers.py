"""Simple helper functions that are used by the HTTP endpoints."""
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
