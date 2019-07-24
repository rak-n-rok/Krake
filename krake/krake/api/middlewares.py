"""This modules defines aiohttp middlewares for the Krake HTTP API"""
import asyncio
from aiohttp import web

from .database import Session


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


def authentication(authenticator):
    """Middleware factory authenticating every request.

    The concret implementation is delegated to the passed asynchronous
    authenticator function (see :mod:`krake.api.auth` for details). This
    function returns the username for an incoming request. If the request is
    unauthenticated -- meaning the authenticator returns None --
    ``system:anonymous`` is used as username.

    The username is registed under the ``user`` key of the incoming request.

    Args:
        authenticator (callable): Asynchronous function returning the username
            for a given request.

    Returns:
        aiohttp middleware loading a username for every incoming HTTP request.

    """

    @web.middleware
    async def auth_middleware(request, handler):
        user = await authenticator(request)
        if user is None:
            user = "system:anonymous"
        request["user"] = user

        return await handler(request)

    return auth_middleware
