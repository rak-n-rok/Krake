import json
from aiohttp.web import StreamResponse
from krake.data import serialize


def stream(data, done=None, infinite=False):
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
