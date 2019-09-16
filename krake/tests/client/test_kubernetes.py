from datetime import datetime
import json
import pytz
from aiohttp.web import json_response, StreamResponse

from krake.client import Client
from krake.data.kubernetes import (
    Application,
    ApplicationStatus,
    ApplicationState,
)
from krake.data import serialize
from krake.test_utils import stream


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


async def test_list_applications(k8s_app_factory, aresponses, loop):
    data = [k8s_app_factory()]
    aresponses.add(
        "api.krake.local",
        "/kubernetes/applications",
        "GET",
        json_response([serialize(i) for i in data]),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        apps = await client.kubernetes.application.list()

    assert apps == data


async def test_create_application(k8s_app_factory, aresponses, loop):
    data = k8s_app_factory(status__state=ApplicationState.CREATED)
    aresponses.add(
        "api.krake.local",
        "/kubernetes/applications",
        "POST",
        json_response(serialize(data)),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        app = await client.kubernetes.application.create(manifest=data.manifest)

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


async def test_update_application(k8s_app_factory, aresponses, loop):
    running = k8s_app_factory(status__state=ApplicationState.RUNNING)
    updated = k8s_app_factory(
        id=running.id,
        status__state=ApplicationState.UPDATED,
        user_id=running.user_id,
        manifest=updated_manifest,
    )

    aresponses.add(
        "api.krake.local",
        f"/kubernetes/applications/{running.id}",
        "GET",
        json_response(serialize(running)),
    )
    aresponses.add(
        "api.krake.local",
        f"/kubernetes/applications/{running.id}",
        "PUT",
        json_response(serialize(updated)),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        app = await client.kubernetes.application.update(
            running.id, manifest=updated_manifest
        )

    assert app == updated


async def test_get_application(k8s_app_factory, aresponses, loop):
    data = k8s_app_factory()
    aresponses.add(
        "api.krake.local",
        f"/kubernetes/applications/{data.id}",
        "GET",
        json_response(serialize(data)),
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        app = await client.kubernetes.application.get(data.id)

    assert app == data


async def aenumerate(iterable):
    i = 0
    async for item in iterable:
        yield i, item
        i += 1


async def test_watch_applications(k8s_app_factory, aresponses, loop):
    data = [k8s_app_factory(), k8s_app_factory(), k8s_app_factory()]

    aresponses.add(
        "api.krake.local", f"/kubernetes/applications/watch", "GET", stream(data)
    )
    async with Client(url="http://api.krake.local", loop=loop) as client:
        async for i, app in aenumerate(client.kubernetes.application.watch()):
            expected = data[i]
            assert app == expected

    assert i == len(data) - 1
