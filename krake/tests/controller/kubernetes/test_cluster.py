import asyncio
from datetime import datetime
from aiohttp.web import json_response, Response

from krake.data import serialize
from krake.data.kubernetes import ApplicationStatus, ClusterStatus
from krake.data.kubernetes import ClusterState, ApplicationState
from krake.controller import Worker
from krake.controller.kubernetes.cluster import ClusterController, ClusterWorker
from krake.client import Client
from krake.test_utils import stream

from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_cluster_reception(aresponses, loop):
    """
    Verify that the ClusterController hands over the Cluster being deleted to the
    Workers.
    """
    creating = ClusterFactory(status__state=ClusterState.PENDING)
    running = ClusterFactory(status__state=ClusterState.RUNNING)
    deleting = ClusterFactory(status__state=ClusterState.DELETING)

    aresponses.add(
        "api.krake.local",
        "/kubernetes/namespaces/all/clusters",
        "GET",
        json_response([]),
    )
    aresponses.add(
        "api.krake.local",
        "/kubernetes/namespaces/all/clusters?watch",
        "GET",
        stream([creating, running, deleting], infinite=True),
        match_querystring=True,
    )

    class SimpleWorker(Worker):
        def __init__(self):
            self.done = loop.create_future()

        async def resource_received(self, cluster):
            assert cluster == deleting
            self.done.set_result(None)

    worker = SimpleWorker()

    async with ClusterController(
        api_endpoint="api.krake.local",
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
    ) as controller:
        await asyncio.wait(
            [controller, worker.done], timeout=0.5, return_when=asyncio.FIRST_COMPLETED
        )
    assert worker.done.done()


class Cluster(object):
    pass


async def test_cluster_deletion(aresponses, loop):
    cluster = ClusterFactory(status__state=ClusterState.DELETING)
    cluster_ref = (
        f"/kubernetes/namespaces/{cluster.metadata.namespace}"
        f"/clusters/{cluster.metadata.name}"
    )

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__cluster=cluster_ref
    )
    app_ref = (
        f"/kubernetes/namespaces/{app.metadata.namespace}"
        f"/applications/{app.metadata.name}"
    )

    async def delete_app(request):
        url = request.rel_url
        assert str(url) == app_ref

        status = ApplicationStatus(
            state=ApplicationState.DELETED,
            reason=None,
            cluster=None,
            created=app.status.created,
            modified=datetime.now(),
        )
        app.status = status
        return json_response(serialize(app))

    async def update_cluster_status(request):
        payload = await request.json()
        assert payload["state"] == "DELETED"

        status = ClusterStatus(
            state=ClusterState.DELETED,
            reason=None,
            created=cluster.status.created,
            modified=datetime.now(),
        )
        return json_response(serialize(status))

    # Kubernetes deployment API
    aresponses.add(
        "127.0.0.1:8080",
        "/apis/apps/v1/namespaces/default/deployments/nginx-demo",
        "GET",
        Response(status=200),
    )
    aresponses.add(
        "127.0.0.1:8080",
        "/apis/apps/v1/namespaces/default/deployments/nginx-demo",
        "DELETE",
        Response(status=200),
    )
    aresponses.add(
        "127.0.0.1:8080",
        "/api/v1/namespaces/default/services/nginx-demo",
        "DELETE",
        Response(status=200),
    )

    # Krake API
    aresponses.add(
        "api.krake.local",
        "/kubernetes/namespaces/all/applications",
        "GET",
        json_response([serialize(app)]),
    )
    aresponses.add(
        "api.krake.local", cluster_ref, "GET", json_response(serialize(cluster))
    )
    aresponses.add(
        "api.krake.local",
        f"/kubernetes/namespaces/testing/applications/{app.metadata.name}",
        "DELETE",
        delete_app,
    )
    aresponses.add(
        "api.krake.local",
        f"/kubernetes/namespaces/testing/clusters/{cluster.metadata.name}/status",
        "PUT",
        update_cluster_status,
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = ClusterWorker(client=client)
        await worker.resource_received(cluster)

    assert app.status.state == ApplicationState.DELETED
