import json
from functools import wraps
from aiohttp import web

from krake.data import deserialize


def json_error(exc, content):
    return exc(text=json.dumps(content), content_type="application/json")


def session(request):
    return request["db"]


def with_resource(name, cls, identity="id"):
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


def use_payload(name, cls):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(request, *args, **kwargs):
            payload = await request.json()
            try:
                instance = deserialize(cls, payload)
            except ValueError as err:
                raise json_error(web.HTTPUnprocessableEntity, err.args[0])
            kwargs[name] = instance
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator
