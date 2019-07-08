from datetime import datetime
import json
import pytz
from aiohttp.web import json_response, StreamResponse

from krake.client import Client
from krake.data.kubernetes import Application, ApplicationStatus, ApplicationState
from krake.data import serialize
from krake.test_utils import stream

from factories.kubernetes import ApplicationFactory


manifest = """---
apiVersion: v1
kind: Service
metadata:
  name: wordpress-mysql
  labels:
    app: wordpress
spec:
  ports:
    - port: 3306
  selector:
    app: wordpress
    tier: mysql
  clusterIP: None
"""


async def test_list_applications(aresponses, loop):
    data = [ApplicationFactory()]
    aresponses.add(
        "api.krake.local",
        "/namespaces/testing/kubernetes/applications",
        "GET",
        json_response([serialize(i) for i in data]),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        apps = await client.kubernetes.application.list(namespace="testing")

    assert apps == data


async def test_create_application(aresponses, loop):
    data = ApplicationFactory(status__state=ApplicationState.PENDING)
    aresponses.add(
        "api.krake.local",
        "/namespaces/testing/kubernetes/applications",
        "POST",
        json_response(serialize(data)),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        app = await client.kubernetes.application.create(
            namespace="testing", manifest=data.spec.manifest
        )

    assert app == data


updated_manifest = """
apiVersion: apps/v1 # for versions before 1.9.0 use apps/v1beta2
kind: Deployment
metadata:
  name: nginx-deployment
spec:
  selector:
    matchLabels:
      app: nginx
  replicas: 2 # tells deployment to run 2 pods matching the template
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
"""


async def test_update_application(aresponses, loop):
    running = ApplicationFactory(status__state=ApplicationState.RUNNING)
    updated = ApplicationFactory(
        metadata__uid=running.metadata.uid,
        metadata__user=running.metadata.user,
        status__state=ApplicationState.UPDATED,
        spec__manifest=updated_manifest,
    )

    aresponses.add(
        "api.krake.local",
        f"/namespaces/testing/kubernetes/applications/{running.metadata.name}",
        "GET",
        json_response(serialize(running)),
    )
    aresponses.add(
        "api.krake.local",
        f"/namespaces/testing/kubernetes/applications/{running.metadata.name}",
        "PUT",
        json_response(serialize(updated)),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        app = await client.kubernetes.application.update(
            namespace="testing", name=running.metadata.name, manifest=updated_manifest
        )

    assert app == updated


async def test_get_application(aresponses, loop):
    data = ApplicationFactory()
    aresponses.add(
        "api.krake.local",
        f"/namespaces/testing/kubernetes/applications/{data.metadata.name}",
        "GET",
        json_response(serialize(data)),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        app = await client.kubernetes.application.get(
            namespace="testing", name=data.metadata.name
        )

    assert app == data


async def aenumerate(iterable):
    i = 0
    async for item in iterable:
        yield i, item
        i += 1


async def test_watch_applications(aresponses, loop):
    data = [ApplicationFactory(), ApplicationFactory(), ApplicationFactory()]

    aresponses.add(
        "api.krake.local",
        "/namespaces/testing/kubernetes/applications?watch",
        "GET",
        stream(data),
        match_querystring=True,
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        async for i, app in aenumerate(
            client.kubernetes.application.watch(namespace="testing")
        ):
            expected = data[i]
            assert app == expected

    assert i == len(data) - 1
