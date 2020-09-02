import asyncio
from copy import deepcopy

from aiohttp import web
import yaml

from krake.api.app import create_app
from krake.controller.kubernetes.hooks import register_observer
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes import (
    KubernetesController,
    KubernetesObserver,
    merge_status,
)
from krake.client import Client
from krake.test_utils import server_endpoint

from tests.factories.fake import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)
from tests.controller.kubernetes import nginx_manifest, hooks_config


def get_first_container(deployment):
    return deployment["spec"]["template"]["spec"]["containers"][0]


async def test_reception_for_observer(aiohttp_server, config, db, loop):
    cluster = ClusterFactory()
    pending = ApplicationFactory(status__state=ApplicationState.PENDING)
    running = ApplicationFactory(
        status__running_on=resource_ref(cluster), status__state=ApplicationState.RUNNING
    )

    server = await aiohttp_server(create_app(config))

    await db.put(cluster)
    await db.put(pending)
    await db.put(running)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await controller.prepare(client)  # need to be called explicitly
        await controller.reflector.list_resource()
    # Each running Application has a corresponding observer
    assert len(controller.observers) == 1
    assert running.metadata.uid in controller.observers


service_response = yaml.safe_load(
    """
    apiVersion: v1
    kind: Service
    metadata:
      creationTimestamp: "2019-11-11T12:01:05Z"
      name: nginx-demo
      namespace: secondary
      resourceVersion: "8080020"
      selfLink: /api/v1/namespaces/secondary/services/nginx-demo
      uid: e2b789b0-19a1-493d-9f23-3f2a63fade52
    spec:
      clusterIP: 10.100.78.172
      externalTrafficPolicy: Cluster
      ports:
      - nodePort: 32566
        port: 80
        protocol: TCP
        targetPort: 80
      selector:
        app: nginx
      sessionAffinity: None
      type: NodePort
    status:
      loadBalancer: {}
    """
)

app_response = yaml.safe_load(
    """
    apiVersion: extensions/v1beta1
    kind: Deployment
    metadata:
      annotations:
        deployment.kubernetes.io/revision: "1"
      creationTimestamp: "2019-11-11T12:01:05Z"
      generation: 1
      name: nginx-demo
      namespace: secondary
      resourceVersion: "8080030"
      selfLink: /apis/extensions/v1beta1/namespaces/secondary/deployments/nginx-demo
      uid: 047686e4-af52-4264-b2a4-2f82b890e809
    spec:
      progressDeadlineSeconds: 600
      replicas: 1
      revisionHistoryLimit: 10
      selector:
        matchLabels:
          app: nginx
      strategy:
        rollingUpdate:
          maxSurge: 25%
          maxUnavailable: 25%
        type: RollingUpdate
      template:
        metadata:
          creationTimestamp: null
          labels:
            app: nginx
        spec:
          containers:
          - image: nginx:1.7.9
            imagePullPolicy: IfNotPresent
            name: nginx
            ports:
            - containerPort: 80
              protocol: TCP
            resources: {}
            terminationMessagePath: /dev/termination-log
            terminationMessagePolicy: File
          dnsPolicy: ClusterFirst
          restartPolicy: Always
          schedulerName: default-scheduler
          securityContext: {}
          terminationGracePeriodSeconds: 30
    status:
      availableReplicas: 1
      conditions:
      - lastTransitionTime: "2019-11-11T12:01:07Z"
        lastUpdateTime: "2019-11-11T12:01:07Z"
        message: Deployment has minimum availability.
        reason: MinimumReplicasAvailable
        status: "True"
        type: Available
      - lastTransitionTime: "2019-11-11T12:01:05Z"
        lastUpdateTime: "2019-11-11T12:01:07Z"
        message: ReplicaSet "nginx-demo-5754944d6c" has successfully progressed.
        reason: NewReplicaSetAvailable
        status: "True"
        type: Progressing
      observedGeneration: 1
      readyReplicas: 1
      replicas: 1
      updatedReplicas: 1
    """
)


async def test_observer_on_poll_update(aiohttp_server, db, config, loop):
    """Test the Observer's behavior on update of an actual resource.

    State (0):
        a Deployment and a Service are present, the Deployment has an nginx
        image with version "1.7.9"
    State (1):
        both resources are still present, but the Deployment image version
        changed to "1.6"
    State (2):
        only the Deployment is present, with the version "1.6"
    """
    routes = web.RouteTableDef()

    # Actual resource, with container image and selector changed
    updated_app = deepcopy(app_response)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"
    # Test the observation of changes on values with a CamelCase format
    updated_app["spec"]["selector"]["matchLabels"] = {"app": "foo"}

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in (0, 1):
            return web.json_response(service_response)
        elif actual_state == 2:
            return web.Response(status=404)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(app_response)
        elif actual_state >= 1:
            return web.json_response(updated_app)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__manifest=nginx_manifest,
    )

    calls_to_res_update = 0

    async def on_res_update(resource):
        assert resource.metadata.name == app.metadata.name

        nonlocal calls_to_res_update, actual_state
        calls_to_res_update += 1

        manifests = resource.status.manifest
        status_image = get_first_container(manifests[0])["image"]
        if actual_state == 0:
            # As no changes are noticed by the Observer, the res_update function will
            # not be called.
            assert False
        elif actual_state == 1:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 2
        elif actual_state == 2:
            assert status_image == "nginx:1.6"
            assert len(manifests) == 1
            assert manifests[0]["kind"] == "Deployment"

        # The spec never changes
        spec_image = get_first_container(resource.spec.manifest[0])["image"]
        assert spec_image == "nginx:1.7.9"

    observer = KubernetesObserver(cluster, app, on_res_update, time_step=-1)

    # Observe an unmodified resource
    # As no changes are noticed by the Observer, the res_update function will not be
    # called.
    actual_state = 0
    assert calls_to_res_update == 0

    # Modify the actual resource "externally"
    actual_state = 1
    await observer.observe_resource()
    assert calls_to_res_update == 1

    # Delete the service "externally"
    actual_state = 2
    await observer.observe_resource()
    assert calls_to_res_update == 2


async def test_observer_on_status_update(aiohttp_server, db, config, loop):
    """Test the ``on_status_update`` method of the Kubernetes Controller
    """
    routes = web.RouteTableDef()

    # Actual resource, with container image changed
    updated_app = deepcopy(app_response)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.json_response(updated_app)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__manifest=nginx_manifest,
        spec__manifest=nginx_manifest,
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        observer = KubernetesObserver(
            cluster, app, controller.on_status_update, time_step=-1
        )

        await observer.observe_resource()
        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert updated.spec == app.spec
        assert updated.metadata.created == app.metadata.created
        first_container = get_first_container(updated.status.manifest[0])
        assert first_container["image"] == "nginx:1.6"


deploy_mangled_response = yaml.safe_load(
    """
    apiVersion: extensions/v1beta1
    kind: Deployment
    metadata:
      annotations:
        deployment.kubernetes.io/revision: "1"
      creationTimestamp: "2019-12-03T08:21:11Z"
      generation: 1
      name: nginx-demo
      namespace: secondary
      resourceVersion: "10373629"
      selfLink: /apis/extensions/v1beta1/namespaces/secondary/deployments/nginx-demo
      uid: 5ee5cbe8-6b18-4b2c-9691-3c9517748fe1
    spec:
      progressDeadlineSeconds: 600
      replicas: 1
      revisionHistoryLimit: 10
      selector:
        matchLabels:
          app: nginx
      strategy:
        rollingUpdate:
          maxSurge: 25%
          maxUnavailable: 25%
        type: RollingUpdate
      template:
        metadata:
          creationTimestamp: null
          labels:
            app: nginx
        spec:
          containers:
          - env:
            - name: KRAKE_TOKEN
              value: will_change
            - name: KRAKE_COMPLETE_URL
              value: will_change
            image: nginx:1.7.9
            imagePullPolicy: IfNotPresent
            name: nginx
            ports:
            - containerPort: 80
              protocol: TCP
            resources: {}
            terminationMessagePath: /dev/termination-log
            terminationMessagePolicy: File
          dnsPolicy: ClusterFirst
          restartPolicy: Always
          schedulerName: default-scheduler
          securityContext: {}
          terminationGracePeriodSeconds: 30
    status:
      availableReplicas: 1
      conditions:
      - lastTransitionTime: "2019-12-03T08:21:13Z"
        lastUpdateTime: "2019-12-03T08:21:13Z"
        message: Deployment has minimum availability.
        reason: MinimumReplicasAvailable
        status: "True"
        type: Available
      - lastTransitionTime: "2019-12-03T08:21:11Z"
        lastUpdateTime: "2019-12-03T08:21:13Z"
        message: ReplicaSet "nginx-demo-75466d4479" has successfully progressed.
        reason: NewReplicaSetAvailable
        status: "True"
        type: Progressing
      observedGeneration: 1
      readyReplicas: 1
      replicas: 1
      updatedReplicas: 1
    """
)


async def test_observer_on_status_update_mangled(aiohttp_server, db, config, loop):
    """Test the ``on_status_update`` method of the Kubernetes Controller in case of
    an Application mangled with the "complete" hook.

    State (0):
        the Application is created, the hook is added. This is used to update the
        Kubernetes response.
    State (1):
        the state of the resource is observed. The observer should not notify the API.
    State (2):
        the image of the Deployment changed. The observer should notify the API.
    """
    routes = web.RouteTableDef()

    actual_state = 0
    copy_deploy_mangled_response = deepcopy(deploy_mangled_response)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.Response(status=404)
        if actual_state == 1:
            return web.json_response(copy_deploy_mangled_response)
        if actual_state == 2:
            return web.json_response(updated_app)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    @routes.patch("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.json_response(updated_app)

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.Response(status=404)
        elif actual_state >= 1:
            return web.json_response(service_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__manifest=nginx_manifest,
        spec__hooks=["complete"],
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    calls_to_res_update = 0

    def update_decorator(func):
        async def on_res_update(resource):
            nonlocal calls_to_res_update, actual_state
            calls_to_res_update += 1

            if actual_state == 1:
                # Ensure that the Observer is not notifying the Controller
                assert False
            if actual_state == 2:
                await func(resource)

        return on_res_update

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(
            server_endpoint(server), worker_count=0, hooks=deepcopy(hooks_config)
        )
        controller.on_status_update = update_decorator(controller.on_status_update)
        await controller.prepare(client)

        await controller.resource_received(app, start_observer=False)
        # Remove from dict to prevent cancellation in KubernetesController.stop_observer
        observer, _ = controller.observers.pop(app.metadata.uid)

        # Modify the response of the cluster to match the Application specific token and
        # endpoint that are stored in the Observer
        first_container = get_first_container(copy_deploy_mangled_response)
        first_container["env"][0]["value"] = observer.resource.status.token
        app_container = get_first_container(observer.resource.status.manifest[0])
        first_container["env"][1]["value"] = app_container["env"][1]["value"]

        actual_state = 1

        # The observer should not call on_res_update
        await observer.observe_resource()
        assert calls_to_res_update == 0

        actual_state = 2

        # Actual resource, with container image changed
        updated_app = deepcopy(copy_deploy_mangled_response)
        first_container = get_first_container(updated_app)
        first_container["image"] = "nginx:1.6"

        await observer.observe_resource()
        assert calls_to_res_update == 1
        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert updated.spec == app.spec
        # Check that the hook is present in the stored Application
        assert "env" in get_first_container(updated.status.manifest[0])
        assert updated.metadata.created == app.metadata.created
        first_container = get_first_container(updated.status.manifest[0])
        assert first_container["image"] == "nginx:1.6"


async def check_observer_does_not_update(observer, app, db):
    """Ensure that the given observer is up-to-date with the Application on the API.

    Args:
        observer (KubernetesObserver): the observer to check.
        app (Application): the Application that the observer has to monitor. Used just
            for its references (name and namespace).
        db (krake.api.database.Session): the database session to access the API data

    Returns:
        Application: the latest version of the Application on the API.

    """
    before = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    await observer.observe_resource()
    after = await db.get(
        Application, namespace=app.metadata.namespace, name=app.metadata.name
    )
    assert after == before
    return after


async def test_observer_on_api_update(aiohttp_server, config, db, loop):
    """Test the connectivity between the Controller and Observer on update of
    a resource by the API.
    State (0):
        a Deployment and a Service are present, the Deployment has an nginx
        image with version "1.7.9"
    State (1):
        both resources are still present, but the API changed the Deployment
        image version to "1.6"
    State (2):
        the Service is deleted by the API. Only the Deployment is present, with
        the version "1.6"
    """
    routes = web.RouteTableDef()

    actual_state = 0

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in (0, 1):
            return web.json_response(service_response)
        elif actual_state == 2:
            return web.Response(status=404)

    updated_app = deepcopy(app_response)
    first_container = get_first_container(updated_app)
    first_container["image"] = "nginx:1.6"

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(app_response)
        elif actual_state >= 1:
            return web.json_response(updated_app)

    @routes.patch("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        assert actual_state in (0, 1)
        return web.json_response(updated_app)

    @routes.patch("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        assert actual_state in (0, 2)
        return web.json_response(service_response)

    @routes.delete("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        assert actual_state == 2
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))
    cluster_ref = resource_ref(cluster)

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=cluster_ref,
        status__scheduled_to=cluster_ref,
        status__manifest=deepcopy(nginx_manifest),
        spec__manifest=deepcopy(nginx_manifest),
        metadata__finalizers=["kubernetes_resources_deletion"],
    )

    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    def update_decorator(func):
        async def on_res_update(resource):
            # As the update on resources is performed by the API, the Observer should
            # never see a difference on the actual resource, and thus, the current
            # function should never be called
            assert False

        return on_res_update

    async def mock():
        # When a resource is updated, the task corresponding to the observer is stopped
        # automatically. This mock is used as a fake task to cancel
        await asyncio.sleep(1)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        controller.on_status_update = update_decorator(controller.on_status_update)

        await controller.prepare(client)

        ##
        # In state 0
        ##

        # Create actual application, starts the Observer
        # ``start_observer`` prevents starting the observer as background task
        await controller.resource_received(app, start_observer=False)

        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Observe an unmodified resource
        after_0 = await check_observer_does_not_update(obs, app, db)

        ##
        # Modify the image version on the API, and observe --> go into state 1
        ##

        actual_state = 1
        # Modify the manifest of the Application
        first_container = get_first_container(after_0.spec.manifest[0])
        first_container["image"] = "nginx:1.6"
        after_0.status.state = ApplicationState.RUNNING
        await db.put(after_0)

        # Update the actual resource
        await controller.resource_received(after_0, start_observer=False)
        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Assert the resource on the observer has been updated.
        first_container = get_first_container(obs.resource.spec.manifest[0])
        assert first_container["image"] == "nginx:1.6"

        # Status should not be updated by observer
        after_1 = await check_observer_does_not_update(obs, app, db)

        ##
        # Remove the service on the API, and observe--> go into state 2
        ##

        actual_state = 2
        # Modify the manifest of the Application
        after_1.spec.manifest = after_1.spec.manifest[:1]
        after_1.status.state = ApplicationState.RUNNING
        await db.put(after_1)

        # Update the actual resource
        await controller.resource_received(after_1, start_observer=False)
        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Status should not be updated by observer
        await check_observer_does_not_update(obs, app, db)


async def test_observer_on_delete(aiohttp_server, config, db, loop):
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        return web.json_response(service_response)

    @routes.get("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.json_response(app_response)

    @routes.delete("/apis/apps/v1/namespaces/secondary/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/secondary/services/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.post("/apis/apps/v1/namespaces/secondary/deployments")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        metadata__deleted=fake.date_time(),
        status__state=ApplicationState.RUNNING,
        status__manifest=nginx_manifest,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        metadata__finalizers=["kubernetes_resources_deletion"],
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(
            server_endpoint(server), worker_count=0, time_step=100
        )
        await controller.prepare(client)

        # Start the observer, which will not observe due to time step
        await register_observer(controller, app)
        observer, _ = controller.observers[app.metadata.uid]

        # Observe a resource actually in deletion.
        before = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        await observer.observe_resource()
        after = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert after == before

        # Clean the application resources
        await controller.resource_received(app)
        # The observer task should be cancelled
        assert app.metadata.uid not in controller.observers


def test_merge_status():
    to_update = {
        "first": "foo",
        "second": "no_change",
        "third": "not_in_newest",
        "fourth": ["list", "with", "different", "length"],
        "sixth": [{"six_1": True}, {"six_2": True}],
        "seventh": ["same", "also same"],
        "eighth": {"changing": 0, "recursive_dict": {"changing": 0, "fixed": "lorem"}},
    }
    newest = {
        "first": "bar",
        "second": "no_change",
        "fourth": ["list", "with", "different", "length", "yes"],
        "fifth": "no_in_to_update",
        "sixth": [{"six_1": True}, {"six_2": False}],
        "seventh": ["same", "different"],
        "eighth": {
            "changing": 42,
            "recursive_dict": {"changing": 42, "fixed": "lorem"},
        },
    }

    to_update_copy = deepcopy(to_update)
    newest_copy = deepcopy(newest)

    res = merge_status(to_update, newest)

    expected = {
        "first": "bar",  # value changed
        "second": "no_change",
        "third": "not_in_newest",  # value kept, even if not in newest
        "fourth": ["list", "with", "different", "length", "yes"],  # new list kept
        "sixth": [{"six_1": True}, {"six_2": False}],  # list recursively updated
        "seventh": ["same", "different"],  # simple elements in list updated
        "eighth": {  # dict recursively updated
            "changing": 42,
            "recursive_dict": {"changing": 42, "fixed": "lorem"},
        },
    }

    assert expected == res
    # The given dictionary should not be modified by the merge
    assert to_update == to_update_copy
    assert newest == newest_copy
