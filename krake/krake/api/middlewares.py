"""This modules defines aiohttp middlewares for the Krake HTTP API"""
import asyncio
from dataclasses import dataclass
from aiohttp import web

from .database import Session
from .helpers import json_error


def database(host, port):
    """Middleware factory for per-request etcd database sessions

    Args:
        host (str): Host of the etcd server
        port (int): TCP port of the etcd server

    Returns:
        aiohttp middleware injecting an etcd database session into each HTTP
        request.

    """
    # TODO: Maybe we can share the TCP connection pool across all HTTP
    #     handlers (like for SQLAlchemy engines)
    @web.middleware
    async def database_middleware(request, handler):
        async with Session(host=host, port=port) as session:
            request["db"] = session
            return await handler(request)

    return database_middleware


def error_log(logger):
    """Middleware factory for logging exceptions in request handlers

    Args:
        logger (logging.Logger): Logger instance that should be used for error
            logging

    Returns:
        aiohttp middleware catching every exception logging it to the passed
        logger and reraising the exception.

    """

    @web.middleware
    async def logging_middleware(request, handler):
        try:
            return await handler(request)
        except asyncio.CancelledError:
            pass
        except web.HTTPException:
            raise
        except Exception as err:
            logger.exception(err)
            raise

    return logging_middleware


@dataclass
class User(object):
    """Data container for the authenticated user

    Attributes:
        name (str): Username of the authenticated user

    """

    name: str


def anonymous_auth(anonymous):
    """Middleware factory for anonymous authentication.

    Args:
        anonymous (User): User instance that should be used as authenticated
            user for every request.

    Returns:
        aiohttp middleware authenticating every request with the passed the
        anonymous user.

    """

    @web.middleware
    async def auth_middleware(request, handler):
        request["user"] = anonymous
        return await handler(request)

    return auth_middleware


def keystone_auth(endpoint):
    """Middleware factory for OpenStack Keystone authentication.

    The token in the ``Authorization`` header of request will be used as
    ``X-Auth-Token`` header for a request to the Keystone token endpoint.
    The returned user information from Keystone is published under key
    ``user`` in the current request.

    The middleware requires an HTTP client session that is loaded from the
    ``http`` key of the application.

    Args:
        endpoint (str): Keystone HTTP endpoint

    Returns:
        aiohttp middleware authenticating requests against a Keystone service.
    """

    @web.middleware
    async def auth_middleware(request, handler):
        token = request.headers.get("Authorization")
        if not token:
            raise json_error(
                web.HTTPUnauthorized, {"reason": "Authorization header is missing"}
            )

        resp = await request.app["http"].get(
            f"{endpoint}/auth/tokens",
            headers={"X-Auth-Token": token, "X-Subject-Token": token},
        )
        if resp.status != 200:
            raise json_error(
                web.HTTPUnauthorized,
                {
                    "reason": f"Invalid Keystone token (HTTP {resp.status} {resp.reason})"
                },
            )
        data = await resp.json()

        user = User(name=data["token"]["user"]["name"])
        request["user"] = user

        return await handler(request)

    return auth_middleware
