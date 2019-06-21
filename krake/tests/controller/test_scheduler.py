import json
import asyncio
from datetime import datetime
import pytz
from aiohttp.web import json_response, StreamResponse

from krake.data import serialize, deserialize
from krake.data.kubernetes import (
    Application,
    ApplicationState,
    ApplicationStatus,
)
from krake.controller import Worker
from krake.controller.scheduler import Scheduler, SchedulerWorker
from krake.client import Client
from krake.test_utils import stream


async def test_kubernetes_reception(k8s_app_factory, aresponses, loop):
    scheduled = k8s_app_factory(status__state=ApplicationState.SCHEDULED)
    updated = k8s_app_factory(status__state=ApplicationState.UPDATED)
    created = k8s_app_factory(status__state=ApplicationState.PENDING)

    aresponses.add(
        "api.krake.local", "/kubernetes/applications", "GET", json_response([])
    )
    # aresponses remove an HTTP endpoint if it was called. If the watch stream
    # would terminate, the scheduler would restart the watcher. At this time,
    # aresponses does not have the /watch endpoint anymore which would lead to
    # an exception. Hence, the watch stream just blocks infinitly after all
    # data was streamed.
    aresponses.add(
        "api.krake.local",
        "/kubernetes/applications/watch",
        "GET",
        stream([scheduled, updated, created], infinite=True),
    )

    class CountingWorker(Worker):
        def __init__(self):
            self.count = 0
            self.done = loop.create_future()

        async def resource_received(self, app):
            if self.count == 0:
                assert app == updated

            elif self.count == 1:
                assert app == created
                self.done.set_result(None)

            self.count += 1

    worker = CountingWorker()

    async with Scheduler(
        api_endpoint="http://api.krake.local",
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
    ) as scheduler:
        await asyncio.wait(
            [scheduler, worker.done], timeout=0.5, return_when=asyncio.FIRST_COMPLETED
        )

    assert worker.done.done()
    assert worker.count == 2


async def test_kubernetes_scheduling(
    k8s_app_factory, k8s_magnum_cluster_factory, aresponses, loop
):
    app = k8s_app_factory(status__state=ApplicationState.UPDATED)
    cluster = k8s_magnum_cluster_factory()

    async def echo(request):
        status = deserialize(ApplicationStatus, await request.json())
        status.state == ApplicationState.SCHEDULED
        status.cluster == cluster.id
        return json_response(serialize(status))

    aresponses.add(
        "api.krake.local",
        "/kubernetes/clusters",
        "GET",
        json_response([serialize(cluster)]),
    )
    aresponses.add(
        "api.krake.local", f"/kubernetes/applications/{app.id}/status", "PUT", echo
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = SchedulerWorker(client=client)

        await worker.resource_received(app)
