import asyncio
from contextlib import suppress
from copy import copy

from krake.api.app import create_app

from krake.data.kubernetes import ClusterState
from krake.controller.kubernetes.cluster import (
    KubernetesClusterController,
)

from krake.controller.kubernetes.hooks import (
    KubernetesClusterObserver,
)
from krake.client import Client
from krake.test_utils import server_endpoint

from tests.factories.kubernetes import ClusterFactory


async def test_list_cluster(aiohttp_server, config):
    """Test the list_cluster method in the kubernetes controller

    After a cluster has been registered, an observer is started. By calling
    list_cluster(cluster) the controller unregisters the corresponding cluster observer
    and registers it again. The method list_cluster() is tested by manually altering the
    cluster's state before calling list_cluster(). Immediately before and after the
    call, the observer's state is stored and finally compared for inequality.

    """
    server = await aiohttp_server(create_app(config))
    controller = KubernetesClusterController(server_endpoint(server), worker_count=0)

    cluster = ClusterFactory(status__state=ClusterState.CONNECTING)
    observer = KubernetesClusterObserver(cluster, controller.handle_resource)

    # initializing the observer
    await controller.resource_received(cluster)  # needs to be called explicitly
    # the initial state of the observer should be CONNECTING
    assert observer.resource.status.state == ClusterState.CONNECTING
    # the length should be 1
    assert len(controller.observers) == 1
    # this state is saved in a variable
    observer_pre_list_cluster = copy(controller.observers)
    # manually alter the state of the cluster
    cluster.status.state = ClusterState.NOTREADY
    # needs to be set explicitly
    cluster.status.kube_controller_triggered = True
    # call list_cluster()
    await controller.list_cluster(cluster)
    # this state is saved in another variable
    observer_post_list_cluster = controller.observers
    # finally, the variables should be unequal
    assert observer_pre_list_cluster != observer_post_list_cluster


async def test_creation_of_cluster_reflector(aiohttp_server, config, loop):
    """Test the registration of a cluster_reflector in the kubernetes controller on
    controller startup, which is triggered by the prepare method.

    """
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = KubernetesClusterController(
            server_endpoint(server), worker_count=0
        )
        await controller.prepare(client)

    # the cluster_reflector should be registered, so the dictionary should not be empty
    assert controller.cluster_reflector != {}


async def test_cleanup(aiohttp_server, config, loop, db):
    """Test the registration of a cluster_reflector in the kubernetes controller on
    controller startup, which is triggered by the prepare method.

    """
    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop):

        cluster = ClusterFactory()
        await db.put(cluster)

        controller = KubernetesClusterController(
            server_endpoint(server), worker_count=0, time_step=1
        )
        await controller.resource_received(cluster)
        run_task = None
        try:
            run_task = loop.create_task(controller.run())

            # Wait for the observers to poll their resource.
            await asyncio.sleep(3)

            assert len(controller.observers) == 1
        finally:
            # Trigger the cleanup
            if run_task is not None:
                run_task.cancel()
                with suppress(asyncio.CancelledError):
                    await run_task

        assert len(controller.observers) == 0
