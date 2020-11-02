"""Simple helper functions that are used by the HTTP endpoints."""
import asyncio
import json
from enum import Enum, auto
from functools import wraps
from aiohttp import web
from krake.data.serializable import Serializable
from marshmallow import ValidationError


class HttpReasonCode(Enum):
    # When a database transaction failed
    TRANSACTION_ERROR = auto()
    # When the authentication through keystone failed
    INVALID_KEYSTONE_TOKEN = auto()
    # When the authentication through keycloak failed
    INVALID_KEYCLOAK_TOKEN = auto()
    # When a resource already in database is requested to be created
    RESOURCE_ALREADY_EXISTS = auto()


class HttpReason(Serializable):
    """Store the reasons for failures on the HTTP layers for the API.
    """

    code: HttpReasonCode
    reason: str


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


class Heartbeat(object):
    """Asynchronous context manager for heartbeating long running HTTP responses.

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
        """Indefinitely write a new line to the response body and sleep for
        :attr:`interval`.
        """
        while True:
            await asyncio.sleep(self.interval, loop=self.loop)
            await self.response.write(b"\n")


def load(argname, cls):
    """Decorator function for loading database models from URL parameters.

    The wrapper loads the ``name`` parameter from the requests ``match_info``
    attribute. If the ``match_info`` contains a ``namespace`` parameter, it
    is used as etcd key parameter as well.

    Example:
        .. code:: python

            from aiohttp import web

            from krake.data import serialize
            from krake.data.core import Role

            @load("role", Role)
            def get_role(request, role):
                return json_response(serialize(role))

    Args:
        argname (str): Name of the keyword argument that will be passed to the
            wrapped function.
        cls (type): Database model class that should be loaded

    Returns:
        callable: Decorator for aiohttp request handlers
    """

    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            key_params = {"name": request.match_info["name"]}

            # Try to load namespace from path
            namespace = request.match_info.get("namespace")
            if namespace:
                key_params["namespace"] = namespace

            instance = await session(request).get(cls, **key_params)
            if instance is None:
                raise web.HTTPNotFound()
            kwargs[argname] = instance
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator


def use_schema(argname, schema):
    """Decorator function for loading a :class:`marshmallow.Schema` from the
    request body.

    If the request body is not valid JSON
    :class:`aiohttp.web.HTTPUnsupportedMediaType` will be raised in the
    wrapper.

    Args:
        argname (str): Name of the keyword argument that will be passed to the
            wrapped function.
        schema (marshmallow.Schema): Schema that should used to deserialize
            the request body

    Returns:
        callable: Decorator for aiohttp request handlers

    """
    if isinstance(schema, type):
        schema = schema()

    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            try:
                body = await request.json()
            except json.JSONDecodeError:
                raise web.HTTPUnsupportedMediaType()

            try:
                payload = schema.load(body)
            except ValidationError as err:
                raise web.HTTPUnprocessableEntity(
                    body=json.dumps(err.messages).encode("utf-8"),
                    content_type="application/json",
                )

            kwargs[argname] = payload

            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator
