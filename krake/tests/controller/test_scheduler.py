import json
import asyncio
from datetime import datetime
import pytz
from aiohttp.web import json_response

from krake.data import serialize
from krake.data.kubernetes import (
    Application,
    ApplicationState,
    ApplicationStatus,
    ClusterBinding,
)
from krake.controller import Worker
from krake.controller.scheduler import Scheduler, SchedulerWorker
from krake.client import Client
from krake.test_utils import stream

from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_kubernetes_reception(aresponses, loop):
    scheduled = ApplicationFactory(status__state=ApplicationState.SCHEDULED)
    updated = ApplicationFactory(status__state=ApplicationState.UPDATED)
    created = ApplicationFactory(status__state=ApplicationState.PENDING)

    aresponses.add(
        "api.krake.local",
        "/namespaces/all/kubernetes/applications",
        "GET",
        json_response([]),
    )
    # aresponses remove an HTTP endpoint if it was called. If the watch stream
    # would terminate, the scheduler would restart the watcher. At this time,
    # aresponses does not have the /watch endpoint anymore which would lead to
    # an exception. Hence, the watch stream just blocks infinitly after all
    # data was streamed.
    aresponses.add(
        "api.krake.local",
        "/namespaces/all/kubernetes/applications?watch",
        "GET",
        stream([scheduled, updated, created], infinite=True),
        match_querystring=True,
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


async def test_kubernetes_scheduling(aresponses, loop):
    app = ApplicationFactory(status__state=ApplicationState.UPDATED)
    cluster = ClusterFactory(magnum=True, metadata__user=app.metadata.user)

    async def echo_binding(request):
        payload = await request.json()
        ref = f"/namespaces/{app.metadata.namespace}/kubernetes/clusters/{cluster.metadata.name}"
        assert payload["cluster"] == ref
        binding = ClusterBinding(cluster=payload["cluster"])
        return json_response(serialize(binding))

    aresponses.add(
        "api.krake.local",
        "/namespaces/all/kubernetes/clusters",
        "GET",
        json_response([serialize(cluster)]),
    )
    aresponses.add(
        "api.krake.local",
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}/binding",
        "PUT",
        echo_binding,
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)
