import asyncio
from datetime import datetime

from aiohttp.web import json_response

from krake.data import serialize
from krake.data.kubernetes import ApplicationState, ApplicationStatus, ClusterBinding
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
        "/kubernetes/namespaces/all/applications",
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
        "/kubernetes/namespaces/all/applications?watch",
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
    cluster = ClusterFactory(metadata__user=app.metadata.user)

    async def echo_binding(request):
        payload = await request.json()
        ref = (
            f"/kubernetes/namespaces/{app.metadata.namespace}"
            f"/clusters/{cluster.metadata.name}"
        )
        assert payload["cluster"] == ref
        binding = ClusterBinding(cluster=payload["cluster"])
        return json_response(serialize(binding))

    aresponses.add(
        "api.krake.local",
        "/kubernetes/namespaces/all/clusters",
        "GET",
        json_response([serialize(cluster)]),
    )
    aresponses.add(
        "api.krake.local",
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/binding",
        "PUT",
        echo_binding,
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)


async def test_kubernetes_scheduling_error_handling(aresponses, loop):
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    async def update_status(request):
        payload = await request.json()

        assert payload["state"] == "FAILED"
        assert payload["cluster"] is None
        assert payload["reason"] == "No cluster available"

        status = ApplicationStatus(
            state=ApplicationState.FAILED,
            reason=payload["reason"],
            created=app.status.created,
            modified=datetime.now(),
        )
        return json_response(serialize(status))

    aresponses.add(
        "api.krake.local",
        "/kubernetes/namespaces/all/clusters",
        "GET",
        json_response([]),
    )
    aresponses.add(
        "api.krake.local",
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}/status",
        "PUT",
        update_status,
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)
