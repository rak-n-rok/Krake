import asyncio

from krake.api.helpers import Heartbeat


async def test_heartbeat(loop):
    class Response(object):
        prepared = True
        chunked = True

        def __init__(self):
            self.beats = 0
            self.done = loop.create_future()

        async def write(self, payload):
            assert payload == b"\n"
            self.beats += 1

            if self.beats == 25:
                self.done.set_result(None)

    resp = Response()

    async with Heartbeat(resp, interval=0.01):
        await asyncio.wait([resp.done], timeout=0.3)

    assert resp.beats == 25
