import json
import asyncio
from datetime import datetime
import pytz
from aiohttp.web import json_response, StreamResponse

from krake.data import serialize
from krake.data.kubernetes import ApplicationState
from krake.controller import Worker
from krake.controller.kubernetes import KubernetesController
from krake.test_utils import stream


async def test_app_reception(k8s_app_factory, aresponses, loop):
    created = k8s_app_factory(status__state=ApplicationState.PENDING)
    updated = k8s_app_factory(status__state=ApplicationState.UPDATED)
    scheduled = k8s_app_factory(status__state=ApplicationState.SCHEDULED)

    aresponses.add(
        "api.krake.local", "/kubernetes/applications", "GET", json_response([])
    )
    # aresponses remove an HTTP endpoint if it was called. If the watch stream
    # would terminate, the controller would restart the watcher. At this time,
    # aresponses does not have the /watch endpoint anymore which would lead to
    # an exception. Hence, the watch stream just blocks infinitly after all
    # data was streamed.
    aresponses.add(
        "api.krake.local",
        "/kubernetes/applications?watch",
        "GET",
        stream([created, updated, scheduled], infinite=True),
    )

    class SimpleWorker(Worker):
        def __init__(self):
            self.done = loop.create_future()

        async def resource_received(self, app):
            assert app == scheduled
            self.done.set_result(None)

    worker = SimpleWorker()

    async with KubernetesController(
        api_endpoint="http://api.krake.local",
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
    ) as controller:
        await asyncio.wait(
            [controller, worker.done], timeout=0.5, return_when=asyncio.FIRST_COMPLETED
        )
    assert worker.done.done()
