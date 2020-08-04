import asyncio
import json
import yaml

from aiohttp import web
from copy import deepcopy

from krake.api.app import create_app
from krake.controller.kubernetes.hooks import (
    register_observer,
    update_last_applied_manifest_from_spec,
    update_last_applied_manifest_from_resp,
    update_last_observed_manifest_from_resp,
    generate_default_observer_schema,
)
from krake.controller.kubernetes.kubernetes import KubernetesClient
from krake.data.core import resource_ref
from krake.data.kubernetes import Application, ApplicationState
from krake.controller.kubernetes import KubernetesController, KubernetesObserver
from krake.client import Client
from krake.test_utils import server_endpoint, get_first_container, serialize_k8s_object

from tests.factories.fake import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
    ClusterFactory,
    make_kubeconfig,
)
from . import (
    deployment_manifest,
    service_manifest,
    nginx_manifest,
    custom_deployment_observer_schema,
    custom_service_observer_schema,
    custom_observer_schema,
    deployment_response,
    service_response,
    configmap_response,
    hooks_config,
    initial_last_observed_manifest_deployment,
    initial_last_observed_manifest_service,
    initial_last_observed_manifest,
)


async def test_reception_for_observer(aiohttp_server, config, db, loop):
    """Test the condition to start an Observer

    When an received application is in PENDING state, no Observer should be started.

    When an application is RUNNING, an Observer should be started.

    """
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


async def test_observer_on_poll_update(aiohttp_server, db, config, loop):
    """Test the Observer's behavior on update of a resource on the k8s cluster directly

    This test goes through the following scenario:

    State (0):
        A Deployment, a Service and a ConfigMap are present, the Deployment has an
        nginx image with version "1.7.9". The service defines 1 port using the "TCP"
        protocol. A custom observer schema is used:
        - It observes the deployment's image, initialized by the given manifest file.
        - It observes the deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
        - The presence of the ConfigMap is observed
    State (1):
        The Deployment image version changed to "1.6".
    State (2):
        The Deployment replicas count is changed to 2.
    State (3):
        The Service's first port's protocol is changed to "UDP"
    State (4):
        A second port is added to the Service.
    State (5):
        A third port is added to the Service.
    State (6):
        All ports are removed from the Service.
    State (7):
        The ConfigMap is deleted

    For each state, it is tested if the Kubernetes Observer detects the update and calls
    the ``on_res_update`` method.

    """
    routes = web.RouteTableDef()

    # When the Observer observes the application, it queries the k8s API to get the
    # current state of each of the application resources
    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0 or actual_state in range(3, 8):
            # The Deployment has not been modified on the cluster
            return web.json_response(deployment_response)

        updated_deployment_response = deepcopy(deployment_response)
        if actual_state == 1:
            # State (1): The Deployment image version changed to "1.6".
            first_container = get_first_container(updated_deployment_response)
            first_container["image"] = "nginx:1.6"

        elif actual_state == 2:
            # State (2): The Deployment replicas count is changed to 2.
            updated_deployment_response["spec"]["replicas"] = 2

        return web.json_response(updated_deployment_response)

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in (0, 1, 2, 7):
            # The Service has not been modified on the cluster
            return web.json_response(service_response)

        updated_service_response = deepcopy(service_response)
        if actual_state == 3:
            # State (3): The Service's first port's protocol is changed to "UDP"
            updated_service_response["spec"]["ports"][0]["protocol"] = "UDP"

        elif actual_state == 4:
            # State (4): A second port is added to the Service.
            updated_service_response["spec"]["ports"].append(
                {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
            )

        elif actual_state == 5:
            # State (5): A third port is added to the Service.
            updated_service_response["spec"]["ports"].append(
                {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
            )
            updated_service_response["spec"]["ports"].append(
                {"nodePort": 32568, "port": 82, "protocol": "TCP", "targetPort": 82}
            )

        elif actual_state == 6:
            # State (6): All ports are removed from the Service.
            updated_service_response["spec"]["ports"] = []

        return web.json_response(updated_service_response)

    @routes.get("/api/v1/namespaces/default/configmaps/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in range(0, 7):
            # The ConfigMap has not been modified on the cluster
            return web.json_response(configmap_response)
        elif actual_state == 7:
            # State (7): The ConfigMap is deleted
            return web.Response(status=404)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        status__mangled_observer_schema=custom_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
    )

    calls_to_res_update = 0

    async def on_res_update(resource):
        assert resource.metadata.name == app.metadata.name

        nonlocal calls_to_res_update, actual_state
        calls_to_res_update += 1
        manifests = resource.status.last_observed_manifest

        if actual_state == 0:
            # As no changes are noticed by the Observer, the res_update function will
            # not be called.
            assert False

        elif actual_state == 1:
            # State (1): The Deployment image version changed to "1.6"
            status_image = get_first_container(manifests[0])["image"]
            assert status_image == "nginx:1.6"
            # Three resources are observed
            assert len(manifests) == 3

        elif actual_state == 2:
            # State (2): The Deployment replicas count is changed to 2.
            assert manifests[0]["spec"]["replicas"] == 2

        elif actual_state == 3:
            # State (3): The Service's first port's protocol is changed to "UDP"
            # As this field is *not* observed, the ``on_res_update`` method shouldn't be
            # called.
            assert False

        elif actual_state == 4:
            # State (4): A second port is added to the Service.
            # Check the current length of the list of ports according to the Observer.
            assert (
                manifests[1]["spec"]["ports"][-1]["observer_schema_list_current_length"]
                == 2
            )

        elif actual_state == 5:
            # State (5): A third port is added to the Service.
            # Check the current length of the list of ports according to the Observer.
            assert (
                manifests[1]["spec"]["ports"][-1]["observer_schema_list_current_length"]
                == 3
            )

        elif actual_state == 6:
            # State (6): All ports are removed from the Service.
            # Check the current length of the list of ports according to the Observer.
            assert (
                manifests[1]["spec"]["ports"][-1]["observer_schema_list_current_length"]
                == 0
            )

        elif actual_state == 7:
            # State (7): The ConfigMap is deleted
            assert len(manifests) == 2

    observer = KubernetesObserver(
        cluster, app, on_res_update, KubernetesClient, time_step=-1
    )

    # Observe an unmodified resource
    # As no changes are noticed by the Observer, the res_update function will not be
    # called.
    actual_state = 0
    assert calls_to_res_update == 0

    # State (1): The Deployment image version changed to "1.6"
    actual_state = 1
    await observer.observe_resource()
    assert calls_to_res_update == 1

    # State (2): The Deployment replicas count is changed to 2.
    actual_state = 2
    await observer.observe_resource()
    assert calls_to_res_update == 2

    # State (3): The Service's first port's protocol is changed to "UDP"
    # As this field is *not* observed, the ``on_res_update`` method shouldn't be called
    actual_state = 3
    await observer.observe_resource()
    assert calls_to_res_update == 2

    # State (4): A second port is added to the Service.
    actual_state = 4
    await observer.observe_resource()
    assert calls_to_res_update == 3

    # State (5): A third port is added to the Service.
    actual_state = 5
    await observer.observe_resource()
    assert calls_to_res_update == 4

    # State (6): All ports are removed from the Service.
    actual_state = 6
    await observer.observe_resource()
    assert calls_to_res_update == 5

    # State (7): The ConfigMap is deleted
    actual_state = 7
    await observer.observe_resource()
    assert calls_to_res_update == 6


async def test_observer_on_status_update(aiohttp_server, db, config, loop):
    """Test the behavior of the ``on_status_update`` method of the Kubernetes Controller

    The status of the k8s resource changed on the cluster:
    - The container image has changed to "1.6". This field is observed.
    - The replicas count has changed to 2. This field is observed, though not
    initialized by the manifest file
    - The Service's first port's protocol has changed to "UDP". Though initialized by
    the manifest file, this field is not observed.
    - The Service's posses a second port.

    This test ensures that the Krake resource's status is updated accordingly.

    """
    routes = web.RouteTableDef()

    updated_service_response = deepcopy(service_response)
    updated_deployment_response = deepcopy(deployment_response)

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        # The Service's first port's protocol is changed to "UDP"
        updated_service_response["spec"]["ports"][0]["protocol"] = "UDP"
        # A second port is added to the Service.
        updated_service_response["spec"]["ports"].append(
            {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
        )
        return web.json_response(updated_service_response)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        first_container = get_first_container(updated_deployment_response)
        first_container["image"] = "nginx:1.6"
        updated_deployment_response["spec"]["replicas"] = 2
        return web.json_response(updated_deployment_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__mangled_observer_schema=custom_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
        spec__manifest=nginx_manifest,
    )
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesController(server_endpoint(server), worker_count=0)
        await controller.prepare(client)

        observer = KubernetesObserver(
            cluster, app, controller.on_status_update, KubernetesClient, time_step=-1
        )

        await observer.observe_resource()
        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )

        # The spec, the last_applied_manifest and the created timestamp didn't change
        assert updated.spec == app.spec
        assert updated.status.last_applied_manifest == app.status.last_applied_manifest
        assert updated.metadata.created == app.metadata.created

        # The last_observed_manifest has been updated for the observed fields only
        last_observed_manifest = updated.status.last_observed_manifest
        first_container = get_first_container(last_observed_manifest[0])
        assert first_container["image"] == "nginx:1.6"
        assert last_observed_manifest[0]["spec"]["replicas"] == 2
        assert (
            last_observed_manifest[1]["spec"]["ports"][-1][
                "observer_schema_list_current_length"
            ]
            == 2
        )

        # Protocol of first port is not observed
        assert "protocol" not in last_observed_manifest[1]["spec"]["ports"][0]
        # ConfigMap is not observed
        assert len(last_observed_manifest) == 2
        assert last_observed_manifest[0]["kind"] == "Deployment"
        assert last_observed_manifest[1]["kind"] == "Service"


deploy_mangled_response = yaml.safe_load(
    """
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      annotations:
        deployment.kubernetes.io/revision: "1"
      creationTimestamp: "2019-12-03T08:21:11Z"
      generation: 1
      name: nginx-demo
      namespace: default
      resourceVersion: "10373629"
      selfLink: /apis/apps/v1/namespaces/default/deployments/nginx-demo
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
        the Application is created, the hook is added.
    State (1):
        the complete hook token is changed on the cluster. The observer should notify
        the API.
    """
    routes = web.RouteTableDef()

    actual_state = 0
    deploy_mangled_response = deepcopy(deployment_response)

    @routes.post("/apis/apps/v1/namespaces/default/deployments")
    async def _(request):

        nonlocal deploy_mangled_response
        rd = await request.read()

        app = json.loads(rd)

        app_first_container = get_first_container(app)
        resp_first_container = get_first_container(deploy_mangled_response)
        resp_first_container["env"] = app_first_container["env"]

        return web.json_response(deploy_mangled_response)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.Response(status=404)  # needed for controller.resource_received
        if actual_state == 1:
            return web.json_response(deploy_mangled_response)
        if actual_state == 2:
            updated_deployment_response = deepcopy(deploy_mangled_response)
            first_container = get_first_container(updated_deployment_response)
            first_container["image"] = "nginx:1.6"
            return web.json_response(updated_deployment_response)

    @routes.post("/api/v1/namespaces/default/configmaps")
    async def _(request):
        return web.json_response(configmap_response)

    @routes.post("/api/v1/namespaces/default/services")
    async def _(request):
        return web.json_response(service_response)

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.Response(status=404)
        elif actual_state >= 1:
            return web.json_response(service_response)

    @routes.get("/api/v1/namespaces/default/configmaps/nginx-demo")
    async def _(request):
        return web.json_response(configmap_response)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)
    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        status__scheduled_to=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        spec__observer_schema=custom_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
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

        assert "env" in get_first_container(
            observer.resource.status.mangled_observer_schema[0]
        )

        actual_state = 1

        # The observer should not call on_res_update
        await observer.observe_resource()
        assert calls_to_res_update == 0

        actual_state = 2

        await observer.observe_resource()
        assert calls_to_res_update == 1

        updated = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert updated.spec.manifest == app.spec.manifest
        # Check that the hook is present and observed in the stored Application
        assert "env" in get_first_container(updated.status.last_observed_manifest[0])
        assert "env" in get_first_container(updated.status.mangled_observer_schema[0])
        assert updated.metadata.created == app.metadata.created
        # Check update of observed image
        first_container = get_first_container(updated.status.last_observed_manifest[0])
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
    """Test the connectivity between the Controller and Observer on update of a
    resource by the API.

    In this test, the resource is updated from the Krake API. The Observer should not
    take any actions.

    State (0):
        a Deployment and a Service are present with standard observer schema. The
        Deployment has an nginx image with version "1.7.9"
    State (1):
        both resources are still present, but the API changed the Deployment image
        version to "1.6".
    State (2):
        the Service is deleted by the API and removed from the observer schema. Only
        the Deployment is present, with the version "1.6"

    """
    routes = web.RouteTableDef()

    actual_state = 0

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state in (0, 1):
            return web.json_response(service_response)
        elif actual_state == 2:
            return web.Response(status=404)

    updated_deployment_response = deepcopy(deployment_response)
    first_container = get_first_container(updated_deployment_response)
    first_container["image"] = "nginx:1.6"

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(deployment_response)
        elif actual_state >= 1:
            return web.json_response(updated_deployment_response)

    @routes.patch("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        nonlocal actual_state
        if actual_state == 0:
            return web.json_response(deployment_response)
        elif actual_state >= 1:
            return web.json_response(updated_deployment_response)

    @routes.patch("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        assert actual_state in (0, 2)
        return web.json_response(service_response)

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
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
        spec__observer_schema=[
            custom_deployment_observer_schema,
            custom_service_observer_schema,
        ],
        status__last_observed_manifest=[
            initial_last_observed_manifest_deployment,
            initial_last_observed_manifest_service,
        ],
        spec__manifest=deepcopy([deployment_manifest, service_manifest]),
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

        # Modify the manifest and the observer_schema of the Application
        after_1.spec.manifest = after_1.spec.manifest[:1]
        after_1.spec.observer_schema = after_1.spec.observer_schema[:1]
        after_1.status.state = ApplicationState.RUNNING
        await db.put(after_1)

        # Update the actual resource
        await controller.resource_received(after_1, start_observer=False)
        obs, _ = controller.observers[app.metadata.uid]
        controller.observers[app.metadata.uid] = (obs, loop.create_task(mock()))

        # Status should not be updated by observer
        await check_observer_does_not_update(obs, app, db)


async def test_observer_on_delete(aiohttp_server, config, db, loop):
    """Test the behavior of the Kubernetes Controller and Observer when an application
    is being deleted.

    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.json_response(service_response)

    @routes.get("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.json_response(deployment_response)

    @routes.get("/api/v1/namespaces/default/configmaps/nginx-demo")
    async def _(request):
        return web.json_response(configmap_response)

    @routes.delete("/apis/apps/v1/namespaces/default/deployments/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/default/services/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    @routes.delete("/api/v1/namespaces/default/configmaps/nginx-demo")
    async def _(request):
        return web.Response(status=200)

    kubernetes_app = web.Application()
    kubernetes_app.add_routes(routes)

    kubernetes_server = await aiohttp_server(kubernetes_app)

    cluster = ClusterFactory(spec__kubeconfig=make_kubeconfig(kubernetes_server))

    app = ApplicationFactory(
        metadata__deleted=fake.date_time(),
        status__state=ApplicationState.RUNNING,
        status__mangled_observer_schema=custom_observer_schema,
        status__last_observed_manifest=initial_last_observed_manifest,
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
        await register_observer(controller, app, KubernetesClient)
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


def test_update_last_applied_manifest_from_spec():
    """Test the ``update_last_applied_manifest_from_spec`` function.

    An application containing a Deployment is created. The default observer schema is
    used.

    State (0):
        `last_applied_manifest` is empty. It should be initialized to spec.manifest

    State (1):
        The Deployment's manifest file specifies a value for the previously unset
        `revisionHistoryLimit` and `progressDeadlineSeconds`. Only the first one is
        observed.

    State (2):
        The Deployment's manifest file specifies a new value for the previously set
        `revisionHistoryLimit` and `progressDeadlineSeconds`.

    State (3):
        The Deployment's manifest doesn't specify the previously set
        `revisionHistoryLimit` and `progressDeadlineSeconds`.
    """

    app = ApplicationFactory(spec__manifest=deepcopy([deployment_manifest]))

    # State (0): last_applied_manifest` is empty. It should be initialized to
    # spec.manifest
    generate_default_observer_schema(app)
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest == app.spec.manifest

    # State (1): The Deployment's manifest file specifies a value for the previously
    # unset `revisionHistoryLimit` and `progressDeadlineSeconds`. Only the first one is
    # observed.
    app.status.mangled_observer_schema[0]["spec"]["revisionHistoryLimit"] = None
    app.spec.manifest[0]["spec"]["revisionHistoryLimit"] = 20
    app.spec.manifest[0]["spec"]["progressDeadlineSeconds"] = 300

    # Both values should be initialized
    update_last_applied_manifest_from_spec(app)
    assert (
        app.status.last_applied_manifest[0]["spec"]["revisionHistoryLimit"]
        == app.spec.manifest[0]["spec"]["revisionHistoryLimit"]
    )
    assert (
        app.status.last_applied_manifest[0]["spec"]["progressDeadlineSeconds"]
        == app.spec.manifest[0]["spec"]["progressDeadlineSeconds"]
    )

    # State (2): The Deployment's manifest file specifies a new value for previously
    # set `revisionHistoryLimit` and `progressDeadlineSeconds`.
    app.spec.manifest[0]["spec"]["revisionHistoryLimit"] = 40
    app.spec.manifest[0]["spec"]["progressDeadlineSeconds"] = 600

    # Both values should be updated
    update_last_applied_manifest_from_spec(app)
    assert (
        app.status.last_applied_manifest[0]["spec"]["revisionHistoryLimit"]
        == app.spec.manifest[0]["spec"]["revisionHistoryLimit"]
    )
    assert (
        app.status.last_applied_manifest[0]["spec"]["progressDeadlineSeconds"]
        == app.spec.manifest[0]["spec"]["progressDeadlineSeconds"]
    )

    # State (3): The Deployment's manifest doesn't specify previously set
    # `revisionHistoryLimit` and `progressDeadlineSeconds`.
    app.spec.manifest[0]["spec"].pop("revisionHistoryLimit")
    app.spec.manifest[0]["spec"].pop("progressDeadlineSeconds")

    # Only the observed field should be kept.
    update_last_applied_manifest_from_spec(app)
    assert app.status.last_applied_manifest[0]["spec"]["revisionHistoryLimit"] == 40
    assert "progressDeadlineSeconds" not in app.status.last_applied_manifest[0]["spec"]


def test_update_last_applied_manifest_from_resp(loop):
    """Test the ``update_last_applied_manifest_from_resp`` function.

    This function is called to update ``status.last_applied_manifest`` from a
    Kubernetes response. Only observed fields which are not yet initialized should be
    created by this function.

    State (0):
        A Deployment and a Service are present, the Deployment has an nginx image with
        version "1.7.9". The Service defines 1 port using the "TCP" protocol. A custom
        observer schema is used:
        - It observes the Deployment's image, initialized by the given manifest file.
        - It observes the Deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
    State (1):
        The Deployment image version changed to "1.6".
    State (2):
        The Deployment replicas count is changed to 2.
    State (3):
        The Service's first port's protocol is changed to "UDP"
    State (4):
        A second port is added to the Service.
    State (5):
        A third port is added to the Service.
    State (6):
        All ports are removed from the Service.

    """

    cluster = ClusterFactory()

    # Create an application using a custom observer schema
    # The last_applied_manifest is initialized with the `spec.manifest` as in the
    # normal workflow (taking aside mangling)
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=[deployment_manifest, service_manifest],
        spec__observer_schema=[
            custom_deployment_observer_schema,
            custom_service_observer_schema,
        ],
        status__last_applied_manifest=[deployment_manifest, service_manifest],
    )

    generate_default_observer_schema(app)

    # Create k8s objects from the k8s response
    copy_deployment_response = deepcopy(deployment_response)
    copy_service_response = deepcopy(service_response)

    deployment_object = serialize_k8s_object(copy_deployment_response, "V1Deployment")
    service_object = serialize_k8s_object(copy_service_response, "V1Service")

    # State 0: Standard response from the k8s cluster
    original_replicas_count = copy_deployment_response["spec"]["replicas"]

    # `spec.replicas` is not initialized in `nginx-manifest` but is present in the
    # `observer_schema`. It is initialized in the first call to the function.
    update_last_applied_manifest_from_resp(app, None, None, deployment_object)
    assert (
        app.status.last_applied_manifest[0]["spec"]["replicas"]
        == original_replicas_count
    )

    # State (1): Change the Deployment's image in the k8s response
    first_container_resp = get_first_container(copy_deployment_response)
    first_container_resp["image"] = "nginx:1.6"
    deployment_object = serialize_k8s_object(copy_deployment_response, "V1Deployment")

    first_container_manifest = get_first_container(nginx_manifest[0])

    # As this field is initialized in `nginx-manifest`, its value is not updated.
    update_last_applied_manifest_from_resp(app, None, None, deployment_object)
    first_container_app = get_first_container(app.status.last_applied_manifest[0])
    assert first_container_app["image"] == first_container_manifest["image"]

    # State (2): Change the Deployment's replicas count to 2
    deployment_object.spec.replicas = 2

    # The field is observed and has already been initialized. No new update to
    # `last_applied_manifest` should occur from a Kubernetes response.
    update_last_applied_manifest_from_resp(app, None, None, deployment_object)
    assert (
        app.status.last_applied_manifest[0]["spec"]["replicas"]
        == original_replicas_count
    )

    # State (3): Change the Service's first port's protocol to "UDP"
    service_object.spec.ports[0].protocol = "UDP"

    # The field is not observed is initialized by `nginx-manifest`. No update should
    # occur
    update_last_applied_manifest_from_resp(app, None, None, service_object)
    assert (
        app.status.last_applied_manifest[1]["spec"]["ports"][0]["protocol"]
        == nginx_manifest[1]["spec"]["ports"][0]["protocol"]
    )

    # State (4): A second port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
    )
    service_object = serialize_k8s_object(copy_service_response, "V1Service")

    # Only the first port is observed: No update should occur
    update_last_applied_manifest_from_resp(app, None, None, service_object)
    assert len(app.status.last_applied_manifest[1]["spec"]["ports"]) == 1

    # State (5): A third port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32568, "port": 82, "protocol": "TCP", "targetPort": 82}
    )
    service_object = serialize_k8s_object(copy_service_response, "V1Service")

    # Only the first port is observed: No update should occur
    update_last_applied_manifest_from_resp(app, None, None, service_object)
    assert len(app.status.last_applied_manifest[1]["spec"]["ports"]) == 1

    # State (6): All ports are removed from the Service.
    copy_service_response["spec"]["ports"] = []
    service_object = serialize_k8s_object(copy_service_response, "V1Service")

    # The first port is observed and initialized by `nginx_manifest`. No update should
    # occur
    update_last_applied_manifest_from_resp(app, None, None, service_object)
    assert len(app.status.last_applied_manifest[1]["spec"]["ports"]) == 1


def test_update_last_observed_manifest_from_resp(loop):
    """Test the ``update_last_observed_manifest_from_resp`` function.

    This function is called to update ``status.last_observed_manifest`` from a
    Kubernetes response. Observed fields only are present and updated.

    State (0):
        A Deployment and a Service are present, the Deployment has an nginx image with
        version "1.7.9". The service defines 1 port using the "TCP" protocol. A custom
        observer schema is used:
        - It observes the Deployment's image, initialized by the given manifest file.
        - It observes the Deployment's replicas count, initialized by k8s to 1.
        - The Service's first port's protocol, initialized in the manifest file, is
        *not* observed
        - It accepts between 0 and 2 ports.
    State (1):
        The Deployment image version changed to "1.6".
    State (2):
        The Deployment replicas count is changed to 2.
    State (3):
        The Service's first port's protocol is changed to "UDP"
    State (4):
        A second port is added to the Service.
    State (5):
        A third port is added to the Service.
    State (6):
        All ports are removed from the Service.

    """
    cluster = ClusterFactory()

    # Create an application using a custom observer schema
    # The `last_observed_manifest` is left empty, as is the normal workflow, and is
    # initialized by the first call to `update_last_observed_manifest_from_resp`
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__running_on=resource_ref(cluster),
        spec__manifest=nginx_manifest,
        spec__observer_schema=custom_observer_schema,
    )

    generate_default_observer_schema(app)

    # Create k8s object from the k8s response
    copy_deployment_response = deepcopy(deployment_response)
    copy_service_response = deepcopy(service_response)

    deployment_object = serialize_k8s_object(copy_deployment_response, "V1Deployment")
    service_object = serialize_k8s_object(copy_service_response, "V1Service")

    # State 0: Standard response from the k8s cluster, while last_observed_manifest is
    # empty

    # Update the Deployment observed manifest from the standard response.
    # app.status.last_observed_manifest.append(
    update_last_observed_manifest_from_resp(app, None, None, deployment_object)
    # )
    assert app.status.last_observed_manifest[0] == initial_last_observed_manifest[0]

    # Update the Service observed manifest from the standard response.
    # app.status.last_observed_manifest.append(
    update_last_observed_manifest_from_resp(app, None, None, service_object)
    # )
    assert app.status.last_observed_manifest[1] == initial_last_observed_manifest[1]

    # State (1): Change the Deployment's image in the k8s response
    first_container_resp = get_first_container(copy_deployment_response)
    first_container_resp["image"] = "nginx:1.6"
    deployment_object = serialize_k8s_object(copy_deployment_response, "V1Deployment")
    # This field is observed, therefore it should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, None, None, deployment_object)
    first_container_app = get_first_container(app.status.last_observed_manifest[0])
    assert first_container_app["image"] == first_container_resp["image"]

    # State (2): Change the Deployment's replicas count to 2
    deployment_object.spec.replicas = 2

    # This field is observed, therefore it should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, None, None, deployment_object)
    assert (
        app.status.last_observed_manifest[0]["spec"]["replicas"]
        == deployment_object.spec.replicas
    )

    # State (3): Change the Service's first port's protocol to "UDP"
    service_object.spec.ports[0].protocol = "UDP"

    # The field is not observed, therefore it shouldn't be present in
    # `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, None, None, service_object)
    assert "protocol" not in app.status.last_observed_manifest[1]["spec"]["ports"][0]

    # State (4): A second port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32567, "port": 81, "protocol": "TCP", "targetPort": 81}
    )
    service_object = serialize_k8s_object(copy_service_response, "V1Service")

    # The length of the list should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, None, None, service_object)
    assert (
        app.status.last_observed_manifest[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]
        == 2
    )

    # State (5): A third port is added to the Service.
    copy_service_response["spec"]["ports"].append(
        {"nodePort": 32568, "port": 82, "protocol": "TCP", "targetPort": 82}
    )
    service_object = serialize_k8s_object(copy_service_response, "V1Service")

    # The length of the list should be updated in `last_observed_manifest`
    update_last_observed_manifest_from_resp(app, None, None, service_object)
    assert (
        app.status.last_observed_manifest[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]
        == 3
    )

    # State (6): All ports are removed from the Service.
    service_object.spec.ports = []

    # The length of the list should be updated in `last_observed_manifest`
    # Also, the first port should not be present in `last_observed_manifest` anymore.
    # The list of ports only contains the special control dictionary
    update_last_observed_manifest_from_resp(app, None, None, service_object)
    assert (
        app.status.last_observed_manifest[1]["spec"]["ports"][-1][
            "observer_schema_list_current_length"
        ]
        == 0
    )
    assert len(app.status.last_observed_manifest[1]["spec"]["ports"]) == 1
