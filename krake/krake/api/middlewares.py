"""This modules defines aiohttp middlewares for the Krake HTTP API"""
import asyncio
import json
from aiohttp import web, hdrs
from krake.api.helpers import HttpReason, HttpReasonCode

from .database import TransactionError


def retry_transaction(retry=1):
    """Middleware factory for transaction error handling.

    If a :class:`.database.TransactionError` occurs, the request handler is retried for
    the specified number of times. If the transaction error persists, a *409 Conflict*
    HTTP exception is raised.

    Args:
        retry (int, optional): Number of retries if a transaction error occurs.

    Returns:
        coroutine: aiohttp middleware handling transaction errors.

    """
    # TODO: Maybe we can share the TCP connection pool across all HTTP
    #     handlers (like for SQLAlchemy engines)
    @web.middleware
    async def retry_transaction_middleware(request, handler):
        for _ in range(retry + 1):
            try:
                return await handler(request)
            except TransactionError as err:
                request.app.logger.warn("Transaction failed (%s)", err)

        reason = HttpReason(
            reason="Concurrent writes to database",
            code=HttpReasonCode.TRANSACTION_ERROR,
        )
        raise web.HTTPConflict(
            text=json.dumps(reason.serialize()), content_type="application/json"
        )

    return retry_transaction_middleware


def error_log():
    """Middleware factory for logging exceptions in request handlers

    Returns:
        aiohttp middleware catching every exception logging it to the passed
        logger and reraising the exception.

    """

    @web.middleware
    async def logging_middleware(request, handler):
        try:
            return await handler(request)
        except (web.HTTPException, asyncio.CancelledError):
            raise
        except Exception as err:
            request.app.logger.exception(err)
            raise

    return logging_middleware


def authentication(authenticators, allow_anonymous):
    """Middleware factory authenticating every request.

    The concrete implementation is delegated to the passed asynchronous
    authenticator function (see :mod:`krake.api.auth` for details). This
    function returns the username for an incoming request. If the request is
    unauthenticated -- meaning the authenticator returns None --
    ``system:anonymous`` is used as username.

    The username is registered under the ``user`` key of the incoming request.

    Anonymous requests can be allowed. If no authenticator authenticates the
    incoming request, "system:anonymous" is assigned as user for the request.
    This behavior can be disabled. In that case "401 Unauthorized" is raised
    if an request is not authenticated by any authenticator.

    Args:
        authenticators (List[callable]): List if asynchronous function
            returning the username for a given request.
        allow_anonymous (bool): If True, anonymous (unauthenticated) requests
            are allowed.

    Returns:
        aiohttp middleware loading a username for every incoming HTTP request.

    """

    @web.middleware
    async def auth_middleware(request, handler):
        user = None

        for authenticator in authenticators:
            user = await authenticator(request)
            if user is not None:
                break

        if user is None:
            # Set OPTIONS requests (only directed to the CORS handler) to be received,
            # even if authentication mechanisms are used.
            if not allow_anonymous and request.method != hdrs.METH_OPTIONS:
                raise web.HTTPUnauthorized()
            user = "system:anonymous"

        request["user"] = user

        return await handler(request)

    return auth_middleware
