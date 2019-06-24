"""Simple helper functions that are used by the HTTP endpoints."""
import json
from functools import wraps
from aiohttp import web

from krake.data import deserialize


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


def with_resource(name, cls, identity="id"):
    """Decorator function returning a decorator that can be used to load a
    database model from a dynamic aiohttp resource.

    Example:
        .. code:: python

            from krake.data.serialzable import Serializable

            class Book(Serializable):
                isbn: int
                title: str

                __namespace__ = "/books"
                __identity__ = "isbn"

            @routes.put("/books/{id}")
            @with_resource("book", Book)
            async def get_model(request, book):
                # Do what every you want with your book ...
                pass

    Args:
        name (str): Name of the keyword argument that should be passed to the
            wrapped handler.
        cls (type): Serializable type that should be loaded from database
        identity (str, optional): Name of the dynamic URL parameter that
            should be used as identity

    Returns:
        callable: Returns a function that can be used as decorator for aiohttp
        handlers.

    """

    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            instance, rev = await session(request).get(
                cls, request.match_info[identity]
            )
            if instance is None:
                raise web.HTTPNotFound()
            kwargs[name] = instance
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator
