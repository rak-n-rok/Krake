"""Some utilities for testing Krake components"""
import asyncio
from itertools import cycle
from functools import wraps
from time import time
from aiohttp import web

from krake.controller.kubernetes_application import listen


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


def make_prometheus(metrics):
    """Create an :class:`aiohttp.web.Application` instance mocking the HTTP
    API of Prometheus. The metric names and corresponding values are given as a
    simple dictionary.

    The values are iterables that are advanced for every HTTP call made to the
    server. If the end of an iterable is reached, the API server will respond
    with an empty response for further requests.

    Examples:
        .. code:: python

            async test_my_func(aiohttp_server):
                prometheus = await aiohttp_server(make_prometheus({
                    "my_metric": ["0.42"]
                }))

        If you want to return the same value for every HTTP request, use
        :func:`itertools.cycle`:

        .. code:: python

            from itertools import cycle

            prometheus = await aiohttp_server(make_prometheus({
                "my_metric": cycle(["0.42"])
            }))

    An additional HTTP endpoint ``/-/update`` is created that can be used to
    update the metrics. The request body must be JSON-encoded with the
    following structure:

    .. code:: python

        {
            # Mapping of metric names to list of values
            "metrics": {
                "my_metric": ["100", "500"]
            },
            "cycle": false   # Optional: if true, metrics are repeated
        }

    Args:
        metrics (Dict[str, Iterable]): Mapping of metric names an iterable of
            the corresponding value.

    Returns:

        aiohttp.web.Application: aiohttp application that can be run with the
        `aiohttp_server` fixture.

    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        name = request.query.get("query")
        if name not in request.app["series"]:
            result = []
        else:
            try:
                value = next(request.app["series"][name])
            except StopIteration:
                del request.app["series"][name]
                result = []
            else:
                result = [
                    {
                        "metric": {
                            "__name__": name,
                            "instance": "unittest",
                            "job": "unittest",
                        },
                        "value": [time(), str(value)],
                    }
                ]

        return web.json_response(
            {"status": "success", "data": {"resultType": "vector", "result": result}}
        )

    @routes.post("/-/update")
    async def _(request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("'metrics' must be a dictionary")
            metrics = body["metrics"]
            if not isinstance(metrics, dict):
                raise ValueError("Metric must be a dictionary")
            for value in metrics.values():
                if not isinstance(value, list):
                    raise ValueError("Metric values must be a list")
        except (KeyError, ValueError) as err:
            raise web.HTTPBadRequest() from err

        if body.get("cycle", False):
            series = {name: iter(cycle(value)) for name, value in metrics.items()}
        else:
            series = {name: iter(value) for name, value in metrics.items()}

        request.app["series"] = series

        return web.Response(status=200)

    app = web.Application()
    app.add_routes(routes)
    app["series"] = {name: iter(value) for name, value in metrics.items()}

    return app


class HandlerDeactivator(object):
    def __init__(self, hook, handler):
        self.hook = hook
        self.handler = handler

    def __enter__(self):
        listen.registry[self.hook].remove(self.handler)

    def __exit__(self, *exc):
        listen.registry[self.hook].append(self.handler)
