"""Some utilities for testing Krake components"""
import json
from aiohttp.web import StreamResponse
from krake.data import serialize


def stream(data, done=None, infinite=False):
    """aiohttp handler factory returning a aiohttp request handler streaming
    the passed list of data. Each item will be JSON-serialized on a new line.

    Example:
        .. code:: python

            import aresponses

            # Mock an API watch stream
            aresponses.add(
                "api.krake.local",
                "/kubernetes/applications/watch",
                "GET",
                stream([app1, app2, app3], infinite=True),
            )

    Args:
        data (list): List of serializable (func:`krake.data.serialize`) objects
        done (asyncio.Future, optional): Future that will be resolved if all
            objects are written to response stream
        infinite (bool, optional): If set to True, the handler will block
            indefinitly after all data was written to the response stream.
            Default: False

    Returns:
        coroutine: An aiohttp request handler
    """

    async def handler(request):
        resp = StreamResponse(headers={"Content-Type": "application/json"})
        resp.enable_chunked_encoding()
        await resp.prepare(request)

        for item in data:
            await resp.write(json.dumps(serialize(item)).encode())
            await resp.write(b"\n")

        if done:
            done.set_result(None)

        if infinite:
            await request.loop.create_future()

        return resp

    return handler
