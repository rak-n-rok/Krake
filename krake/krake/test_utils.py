"""Some utilities for testing Krake components"""
import asyncio
from functools import wraps


def with_timeout(timeout):
    """Decorator function for coroutines

    Example:
        .. code:: python

            from krake.test_utils import with_timeout

            @with_timeout(3)
            async def test_my_coroutine():
                await infinite_coroutine()

    Args:
        timeout (int, float): Timeout interval in seconds

    Returns:
        callable: Decorator that can be used for decorating coroutines.

    """

    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)

        return wrapper

    return decorator


def server_endpoint(server):
    """Return the HTTP endpoint for the given test server.

    Args:
        server (aiohttp.test_utils.TestServer): aiohttp test server instance

    Returns:
        str: HTTP endpoint of the server

    """
    return f"{server.scheme}://{server.host}:{server.port}"
