import asyncio
from aiohttp import web
from etcd3.aio_client import AioClient

from .database import Session


def database(host, port):
    @web.middleware
    async def database_middleware(request, handler):
        async with Session(host=host, port=port) as session:
            request["db"] = session
            return await handler(request)

    return database_middleware


def error_log(logger):
    @web.middleware
    async def logging_middleware(request, handler):
        try:
            return await handler(request)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            logger.exception(err)
            raise

    return logging_middleware
