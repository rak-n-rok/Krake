import copy
import multiprocessing
import re
import time

import sys

import pytest
import pytz
import asyncio
from asyncio.subprocess import PIPE, STDOUT

import yaml
from aiohttp import web


from typing import NamedTuple

from krake.api.app import create_app
from krake.client import Client
from krake.controller.infrastructure.infrastructure import (
    DELETION_FINALIZER,
    InfrastructureController,
)
from krake.data.infrastructure import InfrastructureProviderRef
from krake.test_utils import server_endpoint, with_timeout
from krake.data.core import resource_ref, ReasonCode, ResourceRef
from krake.data.kubernetes import Cluster, ClusterState
from krake.controller.infrastructure.__main__ import main
from tests.factories.infrastructure import (
    InfrastructureProviderFactory,
    GlobalInfrastructureProviderFactory,
    CloudFactory,
    GlobalCloudFactory,
)

from tests.factories.kubernetes import (
    ClusterFactory,
    make_kubeconfig,
)
from tests.factories import fake


TOSCA_CLUSTER_MINIMAL = {
    "tosca_definitions_version": "tosca_simple_yaml_1_0",
    "topology_template": {"outputs": {"kubeconfig": {"value": "test"}}},
}


class DummyServer(NamedTuple):
    scheme: str = "http"
    host: str = "example.com"
    port: str = "8080"


@with_timeout(3)
async def test_main_help(loop):
    """Verify that the help for the Infrastructure Controller is displayed, and contains the
    elements added by the argparse formatters (default value and expected types of the
    parameters).
    """
    command = "python -m krake.controller.infrastructure -h"
    # The loop parameter is mandatory otherwise the test fails if started with others.
    process = await asyncio.create_subprocess_exec(
        *command.split(" "), stdout=PIPE, stderr=STDOUT
    )
    stdout, _ = await process.communicate()
    output = stdout.decode()

    to_check = [
        "Infrastructure controller",
        "usage:",
        "default:",  # Present if the default value of the arguments are displayed
        "str",  # Present if the type of the arguments are displayed
        "int",
    ]
    # Because python3.10 argparse version changed 'optional arguments:' to 'options:'
    if sys.version_info < (3, 10):
        to_check.append("optional arguments:")
    else:
        to_check.append("options:")

    for expression in to_check:
        assert expression in output


@pytest.mark.slow
def test_main(infrastructure_config, log_to_file_config):
    """Test the main function of the Infrastructure Controller, and verify that it starts,
    display the right output and stops without issue.
    """
    log_config, file_path = log_to_file_config()

    infrastructure_config.api_endpoint = "http://my-krake-api:1234"
    infrastructure_config.log = log_config

    def wrapper(configuration):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        main(configuration)

    # Start the process and let it time to initialize
    process = multiprocessing.Process(target=wrapper, args=(infrastructure_config,))
    process.start()
    time.sleep(2)

    # Stop and wait for the process to finish
    process.terminate()
    process.join()

    assert not process.is_alive()
    assert process.exitcode == 0

    # Verify the output of the process
    with open(file_path, "r") as f:
        output = f.read()

    assert "Controller started" in output
    assert "Received signal, exiting..." in output
    assert "Controller stopped" in output

    # Verify that all "ERROR" lines in the output are only errors that logs the lack of
    # connectivity to the API.
    attempted_connectivity = False
    for line in output.split("\n"):
        if "ERROR" in output:
            message = (
                f"In line {line!r}, an error occurred which was different from the"
                f" error from connecting to the API."
            )
            assert "Cannot connect to host my-krake-api:1234" in output, message
            attempted_connectivity = True

    assert attempted_connectivity


async def test_resource_reception(aiohttp_server, config, db, loop):
    # The following should not be put to the WorkQueue
    # Pending, not scheduled and not registered
    pending = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=None,
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    # Registered and not scheduled
    registered = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=None,
        # cluster factory adds spec.kubeconfig
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    # Failed
    failed = ClusterFactory(
        status__state=ClusterState.FAILED,
        status__scheduled_to=None,
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    # Deleted, but without finalizer
    deleted_without_finalizer = ClusterFactory(
        status__state=ClusterState.ONLINE,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=[],
    )
    # The following should be put to the WorkQueue
    # Pending and scheduled
    scheduled = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=ResourceRef(
            api="infrastructure",
            kind="Cloud",
            name=fake.word(),
            namespace="testing",
        ),
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    deleted_with_finalizer = ClusterFactory(
        status__state=ClusterState.ONLINE,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=[DELETION_FINALIZER],
    )

    # Failed and deleted with finalizers
    deleted_and_failed_with_finalizer = ClusterFactory(
        status__state=ClusterState.FAILED,
        metadata__finalizers=[DELETION_FINALIZER],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    await db.put(pending)
    await db.put(registered)
    await db.put(failed)
    await db.put(deleted_without_finalizer)
    await db.put(scheduled)
    await db.put(deleted_with_finalizer)
    await db.put(deleted_and_failed_with_finalizer)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = InfrastructureController(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await controller.prepare(client)  # need to be called explicitly
        await controller.cluster_reflector.list_resource()

    assert pending.metadata.uid not in controller.queue.dirty
    assert registered.metadata.uid not in controller.queue.dirty
    assert failed.metadata.uid not in controller.queue.dirty
    assert deleted_without_finalizer.metadata.uid not in controller.queue.dirty
    assert scheduled.metadata.uid in controller.queue.dirty
    assert deleted_with_finalizer.metadata.uid in controller.queue.timers
    assert deleted_and_failed_with_finalizer.metadata.uid in controller.queue.timers


# Note: Stacking of `pytest.mark.parametrize` decorators produce all
#  combinations of parametrized arguments. E.g. below parametrization
#  produces 3 tests with the following arguments:
#  - openstack, GlobalInfrastructureProviderFactory, GlobalCloudFactory
#  - openstack, GlobalInfrastructureProviderFactory, CloudFactory
#  - openstack, InfrastructureProviderFactory, CloudFactory
# Note2: The arguments combination with InfrastructureProviderFactory
#   and GlobalCloudFactory is omitted, because a non-namespaced
#   `GlobalCloud` resource cannot reference the namespaced
#   `InfrastructureProvider` resource, see #499 for details
@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_unknown_cloud(
    aiohttp_server,
    config,
    db,
    loop,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the cluster process by the IM infrastructure provider
     with an unknown cloud reference.

    The Infrastructure Controller should raise the exception and update the DB.

    """
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="infrastructure_provider",
    )
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=resource_ref(
            # Reference a cloud which is not stored (registered) in Krake DB,
            # hence is unknown
            cloud_resource(
                **{
                    "metadata__name": "unknown_cloud",
                    "spec__type": cloud_type,
                    f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(  # noqa: E501
                        name="infrastructure_provider",
                        namespaced=bool(infrastructure_provider.metadata.namespace),
                    ),
                }
            )
        ),
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    await db.put(infrastructure_provider)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.INVALID_RESOURCE
    assert re.match(
        r"Unable to find bound .* unknown_cloud", stored.status.reason.message
    )
    assert not stored.metadata.finalizers
    assert not stored.spec.kubeconfig
    assert not stored.status.last_applied_tosca
    assert not stored.status.running_on
    assert not stored.status.cluster_id


@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_unknown_infrastructure_provider(
    aiohttp_server,
    config,
    db,
    loop,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the cluster process by the IM infrastructure provider with an unknown
    infrastructure provider reference.

    The Infrastructure Controller should raise the exception and update the DB.

    """
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            # Reference an infrastructure provider which is not stored
            # (registered) in Krake DB, hence is unknown
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="unknown_infrastructure_provider",
            ),
        }
    )
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=resource_ref(cloud),
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.INVALID_RESOURCE
    assert re.match(
        r"Unable to find .* unknown_infrastructure_provider .*",
        stored.status.reason.message,
    )
    assert not stored.metadata.finalizers
    assert not stored.spec.kubeconfig
    assert not stored.status.last_applied_tosca
    assert not stored.status.running_on
    assert not stored.status.cluster_id


# Test IM infrastructure provider


@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_create_by_im_provider(
    aiohttp_server,
    config,
    db,
    loop,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the creation of a cluster by the IM infrastructure provider.

    The Infrastructure Controller should create the cluster and update the DB.

    """
    routes = web.RouteTableDef()
    cluster_id = fake.uuid4()
    cluster_kubeconfig = make_kubeconfig(DummyServer())

    # As part of the reconciliation loop the infrastructure controller checks
    # the state of the infrastructure. The infrastructure is considered as
    # "ready" if the overall state is `configured`.
    @routes.get(f"/infrastructures/{cluster_id}/state")
    async def _(request):
        return web.json_response(
            {
                "state": {
                    "state": "configured",
                    "vm_states": {
                        "0": "configured",
                        "1": "configured",
                    },
                }
            }
        )

    # As part of the reconciliation loop the infrastructure controller
    # retrieves the TOSCA template outputs to get the cluster admin
    # kubeconfig file.
    @routes.get(f"/infrastructures/{cluster_id}/outputs")
    async def _(request):
        return web.json_response(
            {"outputs": {"kubeconfig": yaml.safe_dump(cluster_kubeconfig)}}
        )

    # As part of the reconciliation loop, the infrastructure controller
    # creates the Cluster.
    @routes.post("/infrastructures")
    async def _(request):
        # The IM returns the infrastructure ID in the following format:
        # http://im-server-endpoind/infrastructures/<infrastructure-id>
        # IM-server endpoint is filtered in the :meth:`InfrastructureManager.create`,
        # hence is not important to define it correctly here.
        return web.Response(text=f"http://{fake.word()}/infrastructures/{cluster_id}")

    im_app = web.Application()
    im_app.add_routes(routes)

    im_server = await aiohttp_server(im_app)
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infrastructure_provider.metadata.namespace),
            ),
        }
    )
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=resource_ref(cloud),
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    await db.put(infrastructure_provider)
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.CONNECTING
    assert stored.metadata.finalizers[-1] == DELETION_FINALIZER
    assert stored.spec.kubeconfig == cluster_kubeconfig
    assert stored.status.last_applied_tosca == TOSCA_CLUSTER_MINIMAL
    assert stored.status.running_on == cluster.status.scheduled_to
    assert stored.status.cluster_id == cluster_id


@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_create_by_im_provider_no_kubeconfig(
    aiohttp_server,
    config,
    db,
    loop,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the creation of a cluster by the IM infrastructure provider.

    Kubeconfig is not present in the IM output. This could be caused by invalid
    TOSCA template which does not define the desired outputs correctly.

    The Infrastructure Controller should update the DB.

    """
    routes = web.RouteTableDef()
    cluster_id = fake.uuid4()

    # As part of the reconciliation loop the infrastructure controller checks
    # the state of the infrastructure. The infrastructure is considered as
    # "ready" if the overall state is `configured`.
    @routes.get(f"/infrastructures/{cluster_id}/state")
    async def _(request):
        return web.json_response(
            {
                "state": {
                    "state": "configured",
                    "vm_states": {
                        "0": "configured",
                        "1": "configured",
                    },
                }
            }
        )

    # As part of the reconciliation loop the infrastructure controller
    # retrieves the TOSCA template outputs.
    @routes.get(f"/infrastructures/{cluster_id}/outputs")
    async def _(request):
        return web.json_response({"outputs": {}})  # empty outputs

    # As part of the reconciliation loop, the infrastructure controller
    # creates the Cluster.
    @routes.post("/infrastructures")
    async def _(request):
        # The IM returns the infrastructure ID in the following format:
        # http://im-server-endpoind/infrastructures/<infrastructure-id>
        # IM-server endpoint is filtered in the :meth:`InfrastructureManager.create`,
        # hence is not important to define it correctly here.
        return web.Response(text=f"http://{fake.word()}/infrastructures/{cluster_id}")

    im_app = web.Application()
    im_app.add_routes(routes)

    im_server = await aiohttp_server(im_app)
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infrastructure_provider.metadata.namespace),
            ),
        }
    )
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=resource_ref(cloud),
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    await db.put(infrastructure_provider)
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.RETRIEVE_FAILED
    assert re.match(r"Empty cluster .* kubeconfig.", stored.status.reason.message)


@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_create_by_im_provider_unreachable(
    aiohttp_server,
    config,
    db,
    loop,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the error handling of the Infrastructure Controller in the case
    of IM infrastructure provider (referenced by a cloud) is unreachable.

    The Infrastructure Controller should not create a cluster and update the DB.

    """
    routes = web.RouteTableDef()

    @routes.post("/infrastructures")
    async def _(request):
        return web.HTTPServiceUnavailable()

    im_app = web.Application()
    im_app.add_routes(routes)

    im_server = await aiohttp_server(im_app)
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infrastructure_provider.metadata.namespace),
            ),
        }
    )
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=resource_ref(cloud),
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    await db.put(infrastructure_provider)
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.CREATE_FAILED
    assert re.match(
        r".*Failed to create cluster .* with IM provider"
        r" im_provider.*Service Unavailable.*",
        stored.status.reason.message,
    )


# Note:
#  In a regular (healthy) environment
#  the update is performed on the cluster
#  with state `ONLINE`. The cluster may
#  have e.g. `NOTREADY` state in some
#  unhealthy environment and cluster
#  update could "cure" it, hence the update
#  is allowed from the multiple cluster states.
@pytest.mark.parametrize(
    "cluster_state",
    [
        ClusterState.ONLINE,
        ClusterState.OFFLINE,
        ClusterState.UNHEALTHY,
        ClusterState.NOTREADY,
    ],
)
@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_update_by_im_provider(
    aiohttp_server,
    config,
    db,
    loop,
    cluster_state,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the update of a cluster by the IM infrastructure provider.

    The Infrastructure Controller should patch the cluster and update the DB.

    """
    routes = web.RouteTableDef()
    cluster_id = fake.uuid4()
    cluster_kubeconfig = make_kubeconfig(DummyServer())

    # As part of the reconciliation loop the infrastructure controller checks
    # the state of the infrastructure. The infrastructure is considered as
    # "updated" if the overall state is `configured`.
    @routes.get(f"/infrastructures/{cluster_id}/state")
    async def _(request):
        return web.json_response(
            {
                "state": {
                    "state": "configured",
                    "vm_states": {
                        "0": "configured",
                        "1": "configured",
                    },
                }
            }
        )

    # As part of the reconciliation loop the infrastructure controller
    # retrieves the TOSCA template outputs to get the cluster admin
    # kubeconfig file.
    @routes.get(f"/infrastructures/{cluster_id}/outputs")
    async def _(request):
        return web.json_response(
            {"outputs": {"kubeconfig": yaml.safe_dump(cluster_kubeconfig)}}
        )

    # As part of the reconciliation loop, the infrastructure controller
    # updates the Cluster.
    @routes.post(f"/infrastructures/{cluster_id}")
    async def _(request):
        return web.HTTPOk()

    im_app = web.Application()
    im_app.add_routes(routes)

    im_server = await aiohttp_server(im_app)
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infrastructure_provider.metadata.namespace),
            ),
        }
    )
    tosca_update = copy.deepcopy(TOSCA_CLUSTER_MINIMAL)
    tosca_update.update({"description": "TOSCA template update"})
    cluster = ClusterFactory(
        status__state=cluster_state,
        status__cluster_id=cluster_id,
        status__running_on=resource_ref(cloud),
        status__scheduled_to=resource_ref(cloud),
        status__last_applied_tosca=TOSCA_CLUSTER_MINIMAL,
        spec__kubeconfig=cluster_kubeconfig,
        spec__tosca=tosca_update,
    )
    await db.put(infrastructure_provider)
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.CONNECTING
    assert stored.metadata.finalizers[-1] == DELETION_FINALIZER
    assert stored.spec.kubeconfig == cluster_kubeconfig
    assert stored.status.last_applied_tosca == tosca_update
    assert stored.status.running_on == cluster.status.scheduled_to
    assert stored.status.cluster_id == cluster_id


@pytest.mark.parametrize(
    "cluster_state",
    [
        ClusterState.ONLINE,
        ClusterState.OFFLINE,
        ClusterState.UNHEALTHY,
        ClusterState.NOTREADY,
    ],
)
@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_update_by_im_provider_unreachable(
    aiohttp_server,
    config,
    db,
    loop,
    cluster_state,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the error handling of the Infrastructure Controller in the case
    of IM infrastructure provider (referenced by a cloud) is unreachable.

    The Infrastructure Controller should not update a cluster and update the DB.

    """
    routes = web.RouteTableDef()
    cluster_id = fake.uuid4()
    cluster_kubeconfig = make_kubeconfig(DummyServer())

    @routes.post(f"/infrastructures/{cluster_id}")
    async def _(request):
        return web.HTTPServiceUnavailable()

    im_app = web.Application()
    im_app.add_routes(routes)

    im_server = await aiohttp_server(im_app)
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infrastructure_provider.metadata.namespace),
            ),
        }
    )
    tosca_update = copy.deepcopy(TOSCA_CLUSTER_MINIMAL)
    tosca_update.update({"description": "TOSCA template update"})
    cluster = ClusterFactory(
        status__state=cluster_state,
        status__cluster_id=cluster_id,
        status__running_on=resource_ref(cloud),
        status__scheduled_to=resource_ref(cloud),
        status__last_applied_tosca=TOSCA_CLUSTER_MINIMAL,
        spec__kubeconfig=cluster_kubeconfig,
        spec__tosca=tosca_update,
    )
    await db.put(infrastructure_provider)
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.RECONCILE_FAILED
    assert re.match(
        r".*Failed to reconcile cluster .* with IM provider"
        r" im_provider.*Service Unavailable.*",
        stored.status.reason.message,
    )


@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_delete_by_im_provider(
    aiohttp_server,
    config,
    db,
    loop,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the deletion of a cluster by the IM infrastructure provider.

    The Infrastructure Controller should delete the cluster and update the DB.

    """
    routes = web.RouteTableDef()
    cluster_id = fake.uuid4()
    cluster_kubeconfig = make_kubeconfig(DummyServer())

    # As part of the reconciliation loop the infrastructure controller checks
    # the state of the infrastructure. The infrastructure is considered as
    # "deleted" if the GET call response with 404 (not found)`.
    @routes.get(f"/infrastructures/{cluster_id}/state")
    async def _(request):
        return web.HTTPNotFound()

    # As part of the reconciliation loop, the infrastructure controller
    # deletes the Cluster.
    @routes.delete(f"/infrastructures/{cluster_id}")
    async def _(request):
        return web.HTTPOk()

    im_app = web.Application()
    im_app.add_routes(routes)

    im_server = await aiohttp_server(im_app)
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infrastructure_provider.metadata.namespace),
            ),
        }
    )

    cluster = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=[DELETION_FINALIZER],
        status__state=ClusterState.ONLINE,
        status__cluster_id=cluster_id,
        status__running_on=resource_ref(cloud),
        status__scheduled_to=resource_ref(cloud),
        status__last_applied_tosca=TOSCA_CLUSTER_MINIMAL,
        spec__kubeconfig=cluster_kubeconfig,
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    await db.put(infrastructure_provider)
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored is None


@pytest.mark.parametrize(
    "infrastructure_provider_resource,cloud_resource",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_cluster_delete_by_im_provider_unreachable(
    aiohttp_server,
    config,
    db,
    loop,
    infrastructure_provider_resource,
    cloud_resource,
    cloud_type,
):
    """Test the deletion of a cluster by the IM infrastructure provider.

    The Infrastructure Controller should delete the cluster and update the DB.

    """
    routes = web.RouteTableDef()
    cluster_id = fake.uuid4()
    cluster_kubeconfig = make_kubeconfig(DummyServer())

    @routes.delete(f"/infrastructures/{cluster_id}")
    async def _(request):
        return web.HTTPServiceUnavailable()

    im_app = web.Application()
    im_app.add_routes(routes)

    im_server = await aiohttp_server(im_app)
    infrastructure_provider = infrastructure_provider_resource(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infrastructure_provider.metadata.namespace),
            ),
        }
    )

    cluster = ClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=[DELETION_FINALIZER],
        status__state=ClusterState.ONLINE,
        status__cluster_id=cluster_id,
        status__running_on=resource_ref(cloud),
        status__scheduled_to=resource_ref(cloud),
        status__last_applied_tosca=TOSCA_CLUSTER_MINIMAL,
        spec__kubeconfig=cluster_kubeconfig,
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    await db.put(infrastructure_provider)
    await db.put(cloud)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = InfrastructureController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == ClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.DELETE_FAILED
    assert re.match(
        r".*Failed to delete cluster .* with IM provider"
        r" im_provider.*Service Unavailable.*",
        stored.status.reason.message,
    )
