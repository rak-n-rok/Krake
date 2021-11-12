"""This modules defines aiohttp middlewares for the Krake HTTP API"""
import asyncio
from aiohttp import web, hdrs
from krake.api.helpers import HttpReason, HttpReasonCode, json_error

from .database import TransactionError

# added for test logging:


from asyncio import CancelledError

# from aiohttp import web
from aiohttp.web_exceptions import HTTPException
from aiohttp.web_log import AccessLogger as _AccessLogger
from contextvars import ContextVar

# from contextlib import ExitStack
import logging
from secrets import token_urlsafe

#


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
        raise json_error(web.HTTPConflict, reason.serialize())

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
                raise web.HTTPUnauthorized(reason="No user has been authenticated.")
            user = "system:anonymous"

        request["user"] = user

        return await handler(request)

    return auth_middleware


# apply logging middleware here:


# contextvar that contains given request tracing id
request_id = ContextVar("request_id")

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------


def setup_logging_request_id_prefix():

    # Wrap logging request factory so that every log record gets an attribute
    # record.requestIdPrefix.
    # You can then use it in log format as "%(requestIdPrefix)s".

    # make sure we are doing this only once
    if getattr(logging, "request_id_log_record_factory_set_up", False):
        return
    logging.request_id_log_record_factory_set_up = True

    old_factory = logging.getLogRecordFactory()

    def new_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        req_id = request_id.get(None)
        record.requestIdPrefix = f"[{req_id}] " if req_id else ""
        return record

    logging.setLogRecordFactory(new_factory)


class RequestIdContextAccessLogger(_AccessLogger):
    def log(self, request, response, time):
        token = request_id.set(request["request_id"])
        try:
            super().log(request, response, time)
        finally:
            request_id.reset(token)


def generate_request_id():

    # Used in request_id_middleware to generate the request id

    req_id = token_urlsafe(5)
    req_id = req_id.replace("_", "x").replace("-", "X")
    return req_id


def request_id_middleware(request_id_factory=None, log_function_name=True):
    request_id_factory = request_id_factory or generate_request_id

    @web.middleware
    async def _request_id_middleware(request, handler):

        # Aiohttp middleware that sets request_id contextvar and request['request_id']
        # to some random value identifying the given request.

        req_id = request_id_factory()
        request["request_id"] = req_id
        token = request_id.set(req_id)
        try:
            await _call_handler(request, handler, log_function_name)

        finally:
            request_id.reset(token)

    return _request_id_middleware


def get_function_name(f):
    try:
        return f"{f.__module__}:{f.__name__}"
    except Exception:
        return str(f)


async def _call_handler(request, handler, log_function_name):

    # Used in request_id_middleware to wrap handler call with some logging.

    try:
        if log_function_name:
            logger.info(
                "Processing %s %s (%s)",
                request.method,
                request.path,
                get_function_name(handler),
            )
        else:
            logger.info("Processing %s %s", request.method, request.path)
        return await handler(request)
    except CancelledError as e:
        logger.info("(Cancelled)")
        raise e
    except HTTPException as e:
        logger.debug("HTTPException: %r", e)
        raise e
    except Exception as e:
        # We are processing 500 error right here, because if we let it
        # the web server to process, it would be outside of the request_id
        # contextvar scope.
        # (And also outside the sentry scope, if sentry is enabled.)
        logger.exception("Error handling request: %r", e)
        resp = web.Response(
            status=500, text="500 Internal Server Error\n", content_type="text/plain"
        )
        resp.force_close()
        return resp


def aiohttp_logging_id():
    """Middleware to improve the logging of aiohttp by giving id's to processes

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


# ------------------------------------------------------------------------------
