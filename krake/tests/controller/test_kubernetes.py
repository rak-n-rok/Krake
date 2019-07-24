import json
import asyncio
from datetime import datetime
import pytz
from aiohttp.web import json_response, Response

from krake.data import serialize
from krake.data.kubernetes import ApplicationState, ApplicationStatus
from krake.controller import Worker
from krake.controller.kubernetes import KubernetesController, KubernetesWorker
from krake.client import Client
from krake.test_utils import stream

from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_app_reception(aresponses, loop):
    created = ApplicationFactory(status__state=ApplicationState.PENDING)
    updated = ApplicationFactory(status__state=ApplicationState.UPDATED)
    scheduled = ApplicationFactory(status__state=ApplicationState.SCHEDULED)

    aresponses.add(
        "api.krake.local",
        "/namespaces/all/kubernetes/applications",
        "GET",
        json_response([]),
    )
    aresponses.add(
        "api.krake.local",
        "/namespaces/all/kubernetes/applications?watch",
        "GET",
        stream([created, updated, scheduled], infinite=True),
        match_querystring=True,
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


nginx_manifest = """---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-demo
spec:
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.7.9
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: nginx-demo
spec:
  type: NodePort
  selector:
    app: nginx
  ports:
  - port: 80
    protocol: TCP
    targetPort: 80
"""


async def test_app_creation(aresponses, loop):
    cluster = ClusterFactory(magnum=False)
    cluster_ref = f"/namespaces/{cluster.metadata.namespace}/kubernetes/clusters/{cluster.metadata.name}"
    app = ApplicationFactory(
        status__state=ApplicationState.SCHEDULED,
        spec__cluster=cluster_ref,
        spec__manifest=nginx_manifest,
    )

    async def update_status(request):
        payload = await request.json()
        assert payload["state"] == "RUNNING"
        assert payload["cluster"] == cluster_ref

        status = ApplicationStatus(
            state=ApplicationState.RUNNING,
            reason=None,
            cluster=payload["cluster"],
            created=app.status.created,
            modified=datetime.now(),
        )
        return json_response(serialize(status))

    aresponses.add(
        "api.krake.local", cluster_ref, "GET", json_response(serialize(cluster))
    )
    aresponses.add(
        "127.0.0.1:8080",
        "/apis/apps/v1/namespaces/default/deployments/nginx-demo",
        "GET",
        Response(status=404),
    )
    aresponses.add(
        "127.0.0.1:8080",
        "/apis/apps/v1/namespaces/default/deployments",
        "POST",
        Response(status=200),
    )
    aresponses.add(
        "127.0.0.1:8080",
        "/api/v1/namespaces/default/services/nginx-demo",
        "GET",
        Response(status=404),
    )
    aresponses.add(
        "127.0.0.1:8080",
        "/api/v1/namespaces/default/services",
        "POST",
        Response(status=200),
    )
    aresponses.add(
        "api.krake.local",
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}/status",
        "PUT",
        update_status,
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = KubernetesWorker(client=client)
        await worker.resource_received(app)


async def test_app_deletion(aresponses, loop):
    cluster = ClusterFactory(magnum=False)
    cluster_ref = f"/namespaces/{cluster.metadata.namespace}/kubernetes/clusters/{cluster.metadata.name}"
    app = ApplicationFactory(
        status__state=ApplicationState.DELETING,
        spec__cluster=cluster_ref,
        spec__manifest=nginx_manifest,
    )
    app_ref = f"/namespaces/{app.metadata.namespace}/kubernetes/applications/{app.metadata.name}"

    async def update_status(request):
        payload = await request.json()
        assert payload["state"] == "DELETED"

        status = ApplicationStatus(
            state=ApplicationState.DELETED,
            reason=None,
            cluster=None,
            created=app.status.created,
            modified=datetime.now(),
        )
        return json_response(serialize(status))

    aresponses.add("api.krake.local", app_ref, "GET", json_response(serialize(app)))
    aresponses.add(
        "api.krake.local", cluster_ref, "GET", json_response(serialize(cluster))
    )
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
    aresponses.add(
        "api.krake.local",
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}/status",
        "PUT",
        update_status,
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = KubernetesWorker(client=client)
        await worker.resource_received(app)


async def test_app_deletion_without_binding(aresponses, loop):
    app = ApplicationFactory(
        status__state=ApplicationState.DELETING,
        spec__cluster=None,
        spec__manifest=nginx_manifest,
    )
    app_ref = f"/namespaces/{app.metadata.namespace}/kubernetes/applications/{app.metadata.name}"

    async def update_status(request):
        payload = await request.json()
        assert payload["state"] == "DELETED"

        status = ApplicationStatus(
            state=ApplicationState.DELETED,
            reason=None,
            cluster=None,
            created=app.status.created,
            modified=datetime.now(),
        )
        return json_response(serialize(status))

    aresponses.add("api.krake.local", app_ref, "GET", json_response(serialize(app)))
    aresponses.add(
        "api.krake.local",
        f"/namespaces/testing/kubernetes/applications/{app.metadata.name}/status",
        "PUT",
        update_status,
    )

    async with Client(url="http://api.krake.local", loop=loop) as client:
        worker = KubernetesWorker(client=client)
        await worker.resource_received(app)
