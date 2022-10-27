"""Simple helper functions that are used by the HTTP endpoints."""
import asyncio
import json
import time

from enum import Enum
from functools import wraps
from aiohttp import web
from aiohttp.web_exceptions import HTTPException

from krake.data.serializable import Serializable
from krake.data.kubernetes import ApplicationState
from marshmallow import ValidationError, fields, missing, post_dump
from marshmallow.validate import Range


class HttpProblemTitle(Enum):
    """Store the title of an RFC 7807 problem.

    The RFC 7807 Problem title is a short, human-readable summary of
    the problem type. The name defines the title itself.
    The value is used as part of the URI reference that identifies
    the problem type, see :func:`.middlewares.problem_response`
    for details.
    """

    # When a requested resource cannot be found in the database
    NOT_FOUND_ERROR = "not-found-error"
    # When a database transaction failed
    TRANSACTION_ERROR = "transaction-error"
    # When the update failed
    UPDATE_ERROR = "update-error"
    # When the authentication through keystone failed
    INVALID_KEYSTONE_TOKEN = "invalid-keystone-token"
    # When the authentication through keycloak failed
    INVALID_KEYCLOAK_TOKEN = "invalid-keycloak-token"
    # When a resource already in database is requested to be created
    RESOURCE_ALREADY_EXISTS = "resource-already-exists"


class HttpProblem(Serializable):
    """Store the reasons for failures of the HTTP layers for the API.

    The reason is stored as an RFC 7807 Problem. It is a way to define
    a uniform, machine-readable details of errors in a HTTP response.
    See https://tools.ietf.org/html/rfc7807 for details.

    Attributes:
        type (str): A URI reference that identifies the
            problem type. It should point the Krake API users to the
            concrete part of the Krake documentation where the problem
            type is explained in detail. Defaults to about:blank.
        title (HttpProblemTitle): A short, human-readable summary of
            the problem type
        status (int): The HTTP status code
        detail (str): A human-readable explanation of the problem
        instance (str): A URI reference that identifies the specific
            occurrence of the problem

    """

    type: str = "about:blank"
    title: HttpProblemTitle = None
    status: int = None
    detail: str = None
    instance: str = None

    def __post_init__(self):
        """HACK:
        :class:`marshmallow.Schema` allows registering hooks like ``post_dump``.
        This is not allowed in krake :class:`Serializable`, therefore within
        :class:`marshmallow.Schema` allows registering hooks like ``post_dump``.
        This is not allowed in krake :class:`Serializable`, therefore
        the __post_init__ method is registered directly within the hook.
        """
        self.Schema._hooks.update({("post_dump", False): ["remove_none_values"]})
        setattr(self.Schema, "remove_none_values", self.remove_none_values)

    @post_dump
    def remove_none_values(self, data, **kwargs):
        """Remove attributes if value equals None"""
        return {key: value for key, value in data.items() if value is not None}


class HttpProblemError(Exception):
    """Custom exception raised if failures on the HTTP layers occur"""

    def __init__(
        self, exc: HTTPException, problem: HttpProblem = HttpProblem(), **kwargs
    ):
        self.exc = exc
        self.problem = problem
        self.kwargs = kwargs


def session(request):
    """Load the database session for a given aiohttp request

    Internally, it just returns the value that was given as cleanup context by
    func:`krake.api.app.db_session`.

    Args:
        request (aiohttp.web.Request): HTTP request

    Returns:
        krake.database.Session: Database session for the given request
    """
    return request.app["db"]


class Heartbeat(object):
    """Asynchronous context manager for heartbeating long running HTTP responses.

    Writes newlines to the response body in a given heartbeat interval. If
    ``interval`` is set to 0, no heartbeat will be sent.

    Args:
        response (aiohttp.web.StreamResponse): Prepared HTTP response with
            chunked encoding
        interval (int, float, optional): Heartbeat interval in seconds.
            Default: 10 seconds.

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

    def __init__(self, response, interval=None):

        if interval is None:
            interval = 10

        if not response.prepared:
            raise ValueError("Response must be prepared")

        if not response.chunked:
            raise ValueError("Response must be chunk encoded")

        self.interval = interval
        self.response = response
        self.task = None

    async def __aenter__(self):
        assert self.task is None
        if self.interval:
            self.task = asyncio.create_task(self.heartbeat())
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
            await asyncio.sleep(self.interval)
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
                problem = HttpProblem(
                    detail=(
                        f"{getattr(cls, 'kind', 'Entity')!r} "
                        f"{key_params['name']!r} does not "
                        f"exist in namespace {namespace!r}"
                    ),
                    title=HttpProblemTitle.NOT_FOUND_ERROR,
                )
                raise HttpProblemError(web.HTTPNotFound, problem)

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
                problem = HttpProblem(
                    detail=err.messages,
                )
                raise HttpProblemError(web.HTTPUnprocessableEntity, problem)

            kwargs[argname] = payload

            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator


def blocking():
    """Decorator function to enable function blocking. This allows only a return of the
    response if the requested action is completed (eg. deletion of a resource).
    The function logic is therefore executed after its decorated counterpart.

    Returns:
        Response: JSON style response coming from the handler
    """

    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            resp = await handler(request, *args, **kwargs)

            if "blocking" in request.query and request.query["blocking"] != "False":

                entity = {}
                if kwargs.get("body"):
                    entity = kwargs["body"]
                if kwargs.get("entity"):
                    entity = kwargs["entity"]

                key_params = {}
                if entity.metadata.name:
                    key_params = {"name": entity.metadata.name}
                if entity.metadata.namespace:
                    key_params = {"namespace": entity.metadata.namespace}

                t_end = time.time() + 60
                async with session(request).watch(entity, **key_params) as w:
                    async for event, obj, rev in w:
                        if time.time() > t_end:
                            break
                        if obj is not None and obj.status.state.equals(
                            request.query["blocking"]
                        ):
                            return web.json_response(obj.serialize())

                        if obj is None and request.query["blocking"] == "deleted":
                            entity.status.state = ApplicationState.DELETED
                            return web.json_response(entity.serialize())

            return resp

        return wrapper

    return decorator


def make_create_request_schema(cls):
    """Create a :class:`marshmallow.Schema` excluding subresources and read-only.

    Args:
        cls (type): Data class with ``Schema`` attribute

    Returns:
        marshmallow.Schema: Schema instance with excluded subresources

    """
    exclude = cls.fields_ignored_by_creation()
    return cls.Schema(exclude=exclude)


class QueryFlag(fields.Field):
    """Field used for boolean query parameters.

    If the query parameter exists the field is deserialized to :data:`True`
    regardless of the value. The field is marked as ``load_only``.

    """

    def __init__(self, **metadata):
        super().__init__(load_only=True, **metadata)

    def deserialize(self, value, attr=None, data=None, **kwargs):
        if value is missing:
            return False
        return True


class ListQuery(object):
    """Simple mixin class for :class:`operation` template classes.

    Defines default :attr:`operation.query` attribute for *list* and *list
    all* operations.

    """

    query = {
        "heartbeat": fields.Integer(
            missing=None,
            doc=(
                "Number of seconds after which the server sends a heartbeat in "
                "form of an empty newline. Passing 0 disables the heartbeat. "
                "Default: 10 seconds"
            ),
            validate=Range(min=0),
        ),
        "watch": QueryFlag(
            doc=(
                "Watches for changes to the described resources and return "
                "them as a stream of :class:`krake.data.core.WatchEvent`"
            )
        ),
    }
