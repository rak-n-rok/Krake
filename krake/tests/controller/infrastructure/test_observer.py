from aiohttp import web
from copy import deepcopy
from itertools import groupby
import pytest
from unittest import mock
from random import randint

from krake.api.app import create_app
from krake.client import Client
from krake.client.kubernetes import KubernetesApi as KrakeKubernetesApi
from krake.client.infrastructure import InfrastructureApi as KrakeInfrastructureApi
from krake.controller.infrastructure import hooks as infra_controller_hooks
from krake.data.core import resource_ref
from krake.data.infrastructure import InfrastructureProviderRef
from krake.data.kubernetes import (
    ClusterInfrastructure,
    ClusterInfrastructureData,
    InfrastructureNode,
    InfrastructureNodeCredential,
)

from krake.test_utils import server_endpoint, with_timeout
from tests.factories import fake
from tests.factories.kubernetes import ClusterFactory
from tests.factories.infrastructure import (
    InfrastructureProviderFactory,
    GlobalInfrastructureProviderFactory,
    CloudFactory,
    GlobalCloudFactory,
)


TOSCA_CLUSTER_MINIMAL = {
    "tosca_definitions_version": "tosca_simple_yaml_1_0",
    "topology_template": {"outputs": {"kubeconfig": {"value": "test"}}},
}


async def test_create_infrastructure_provider_cluster_observer(
    aiohttp_server, config, loop
):
    """Test the initialization of the :class:`InfrastructureProviderClusterObserver:`

    Asserts:
        that the initial attributes are set correctly
        that the `on_res_update` hook has not been used
    """

    server = await aiohttp_server(create_app(config))

    cluster = ClusterFactory()
    on_res_update_mock = mock.Mock()
    time_step = 2

    async with Client(url=server_endpoint(server), loop=loop) as client:
        infra_provider_cluster_observer = \
            infra_controller_hooks.InfrastructureProviderClusterObserver(
                resource=cluster,
                on_res_update=on_res_update_mock,
                client=client,
                time_step=2,
            )

    assert infra_provider_cluster_observer.resource == cluster
    assert infra_provider_cluster_observer.on_res_update == on_res_update_mock
    assert infra_provider_cluster_observer.time_step == time_step
    assert infra_provider_cluster_observer.client == client
    assert isinstance(
        infra_provider_cluster_observer.krake_kubernetes_api, KrakeKubernetesApi
    )
    assert isinstance(
        infra_provider_cluster_observer.krake_infrastructure_api, KrakeInfrastructureApi
    )
    on_res_update_mock.assert_not_called()


@pytest.mark.parametrize(
    "infrastructure_provider_factory,cloud_factory",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
@pytest.mark.parametrize("cloud_type", ["openstack"])
async def test_InfrastructureProviderClusterObserver_fetch_actual_resource(
    aiohttp_server, config, db, loop,
    infrastructure_provider_factory, cloud_factory,
    cloud_type,
):
    """Test the `fetch_actual_resource` method of the
    `InfrastructureProviderClusterObserver` class.

    Tests that the infrastructure provider cluster observer correctly fetches data for
    the monitored cluster from the associated infrastructure provider.

    Parameter sets:
        GlobalInfrastructureProviderFactory, GlobalCloudFactory
        GlobalInfrastructureProviderFactory, CloudFactory
        InfrastructureProviderFactory, CloudFactory

    Asserts:
        that the observer is able to use the information in its cluster resource object
            to create a suitable infrastructure provider client.
        that the observer retrieves the expected data from the infrastructure provider
            server.
    """

    # Mock the infrastructure provider API endpoints that will be called
    # NOTE: Examples taken from real infrastructure provider API responses and slightly
    #       altered for more variance and generality.

    routes = web.RouteTableDef()
    cluster_id = fake.uuid4()

    @routes.get(f"/infrastructures/{cluster_id}/vms/0")
    async def _(request):
        if request.headers['Accept'] == 'application/json':
            return web.json_response(
                {
                    "radl": [
                        {
                            "class": "network",
                            "id": "network_private",
                            "cidr": "10.1.1.0/24",
                            "create": "yes",
                            "provider_id": f"im-{cluster_id}-network_private",
                        },
                        {
                            "class": "network",
                            "id": "network_public",
                            "outbound": "yes",
                            "outports": "0.0.0.0/0-80/tcp-80/tcp,0.0.0.0/0-443/tcp-443/tcp",
                            "provider_id": "shared-public-IPv4",
                        },
                        {
                            "class": "system",
                            "id": "front",
                            "instance_name": "front-6e0882dc-d712-11ee-b2ec-e60cc0e9f147",
                            "disk.0.os.flavour": "ubuntu",
                            "disk.0.os.name": "linux",
                            "disk.0.os.version": "22.04",
                            "instance_type": "M",
                            "memory.size": 4294967296,
                            "cpu.count": 2,
                            "net_interface.0.dns_name": "kubeserver",
                            "net_interface.0.connection": "network_private",
                            "net_interface.1.connection": "network_public",
                            "cpu.arch": "x86_64",
                            "disk.0.image.url": "ost://identity.example.com/802aecb9-7553-434d-a05c-cb8ce6103caa",
                            "disk.0.free_size": 26843545600,
                            "disk.0.os.credentials.username": "cloudadm",
                            "provider.type": "OpenStack",
                            "provider.host": "identity.example.com",
                            "provider.port": 5000,
                            "disk.0.os.credentials.private_key": "PRIVATE_KEY-8x9Am",
                            "state": "running",
                            "instance_id": "5c205fb4-b1e0-4e78-ae1e-333ea18c1a27",
                            "net_interface.0.ip": "192.0.2.3",
                            "net_interface.1.ip": "203.0.113.3",
                        }
                    ]
                }
            )

    @routes.get(f"/infrastructures/{cluster_id}/vms/1")
    async def _(request):
        if request.headers['Accept'] == 'application/json':
            return web.json_response(
                {
                    "radl": [
                        {
                            "class": "network",
                            "id": "network_private",
                            "cidr": "10.1.1.0/24",
                            "create": "yes",
                            "provider_id": f"im-{cluster_id}-network_private",
                        },
                        {
                            "class": "network",
                            "id": "network_public",
                            "outbound": "yes",
                            "outports": "0.0.0.0/0-80/tcp-80/tcp,0.0.0.0/0-443/tcp-443/tcp",
                            "provider_id": "shared-public-IPv4",
                        },
                        {
                            "class": "system",
                            "id": "front",
                            "instance_name": "wn-6e04627e-d712-11ee-b5fb-e60cc0e9f147",
                            "disk.0.os.flavour": "ubuntu",
                            "disk.0.os.name": "linux",
                            "disk.0.os.version": "20.04",
                            "instance_type": "M",
                            "memory.size": 4294967296,
                            "cpu.count": 2,
                            "net_interface.0.dns_name": "kubeserver",
                            "net_interface.0.connection": "network_private",
                            "net_interface.1.connection": "network_public",
                            "cpu.arch": "x86_64",
                            "disk.0.image.url": "ost://identity.example.com/802aecb9-7553-434d-a05c-cb8ce6103caa",
                            "disk.0.free_size": 26843545600,
                            "disk.0.os.credentials.username": "user1",
                            "disk.1.os.credentials.username": "user2",
                            "provider.type": "OpenStack",
                            "provider.host": "identity.example.com",
                            "provider.port": 5000,
                            "disk.0.os.credentials.private_key": "PRIVATE_KEY-B35r0",
                            "disk.0.os.credentials.password": "PASSWORD-sl6r",
                            "disk.1.os.credentials.password": "PASSWORD-s8c1",
                            "state": "running",
                            "instance_id": "009f9f39-b2ef-49a2-8cb0-437abbbe328f",
                            "net_interface.0.ip": "192.0.2.4",
                            "net_interface.1.ip": "203.0.113.4",
                        }
                    ]
                }
            )

    im_server_port = randint(30000, 50000)

    @routes.get(f"/infrastructures/{cluster_id}")
    async def _(request):
        if request.headers['Accept'] == 'application/json':
            return web.json_response(
                {
                    "uri-list": [
                        {"uri": f"http://localhost:{im_server_port}/infrastructures/{cluster_id}/vms/0"},
                        {"uri": f"http://localhost:{im_server_port}/infrastructures/{cluster_id}/vms/1"},
                    ]
                }
            )

    # Create infrastructure manager server with the mocked API endpoints
    # NOTE: Infrastructure manager is mocked here
    #       because we are dealing with a cloud of type "openstack"
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create and store the required Krake resources in the Krake database
    infra_provider = infrastructure_provider_factory(
        metadata__name="im_provider",
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_factory(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(
                name="im_provider",
                namespaced=bool(infra_provider.metadata.namespace),
            ),
        }
    )
    cluster = ClusterFactory(
        status__cluster_id=cluster_id,
        status__scheduled_to=resource_ref(cloud),
        status__running_on=resource_ref(cloud),
    )
    await db.put(infra_provider)
    await db.put(cloud)
    await db.put(cluster)

    # Create observer and run target method
    api_server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        infra_provider_cluster_observer = \
            infra_controller_hooks.InfrastructureProviderClusterObserver(
                resource=cluster,
                on_res_update=mock.Mock(),
                client=client,
                time_step=1,
            )
        returned = await infra_provider_cluster_observer.fetch_actual_resource()

    # Assert that the target method returned the expected data
    assert returned == ClusterInfrastructureData(
        nodes=[
            InfrastructureNode(
                ip_addresses=["192.0.2.3", "203.0.113.3"],
                credentials=[
                    InfrastructureNodeCredential(
                        type="login",
                        username="cloudadm",
                        password=None,
                        private_key="PRIVATE_KEY-8x9Am",
                    ),
                ],
            ),
            InfrastructureNode(
                ip_addresses=["192.0.2.4", "203.0.113.4"],
                credentials=[
                    InfrastructureNodeCredential(
                        type="login",
                        username="user1",
                        password="PASSWORD-sl6r",
                        private_key="PRIVATE_KEY-B35r0",
                    ),
                    InfrastructureNodeCredential(
                        type="login",
                        username="user2",
                        password="PASSWORD-s8c1",
                        private_key=None,
                    ),
                ],
            ),
        ],
    )


async def test_InfrastructureProviderClusterObserver_check_observation(
    aiohttp_server, config, db, loop,
):
    """Test the `check_observation` method of the
    `InfrastructureProviderClusterObserver` class.

    Tests that the infrastructure provider cluster observer recognizes new observations
    in a sequence of mixed observations and correctly integrates new observations into
    its cluster resource object.

    Asserts:
        that the observer is able to recognize new observations.
        that the observer correctly integrates observations in its cluster resource
            which are completely or partially new.
    """

    # Create the required Krake resources
    cluster = ClusterFactory()
    cluster_copy = deepcopy(cluster)  # used for assertions

    # Create a few observations
    # (1) Infrastructure provider just received creation request
    observation_1 = ClusterInfrastructureData(nodes=[])
    # (2) Infrastructure provider created parts of the infrastructure
    observation_2 = ClusterInfrastructureData(
        nodes=[
            InfrastructureNode(
                credentials=[
                    InfrastructureNodeCredential(
                        type="login",
                        username="user1",
                        password="PASSWORD-sl6r",
                    ),
                ],
            ),
        ],
    )
    # (3) Infrastructure provider created the whole infrastructure
    observation_3 = ClusterInfrastructureData(
        nodes=[
            InfrastructureNode(  # added node
                ip_addresses=["192.0.2.3", "203.0.113.3"],
                credentials=[
                    InfrastructureNodeCredential(
                        type="login",
                        username="cloudadm",
                        password=None,
                        private_key="PRIVATE_KEY-8x9Am",
                    ),
                ],
            ),
            InfrastructureNode(
                ip_addresses=["192.0.2.4", "203.0.113.4"],  # added ip addresses
                credentials=[
                    InfrastructureNodeCredential(
                        type="login",
                        username="user1",
                        password="PASSWORD-sl6r",
                        private_key="PRIVATE_KEY-B35r0",  # added credential secret
                    ),
                    InfrastructureNodeCredential(  # added credential
                        type="login",
                        username="user2",
                        password="PASSWORD-s8c1",
                        private_key=None,
                    ),
                ],
            ),
        ],
    )
    # (4) Infrastructure provider updated infrastructure
    observation_4 = ClusterInfrastructureData(
        nodes=[
            InfrastructureNode(  # added node
                ip_addresses=["192.0.2.3", "203.0.113.33"],  # changed ip address
                credentials=[
                    InfrastructureNodeCredential(
                        type="login",
                        username="cloudadm",
                        password=None,
                        private_key="PRIVATE_KEY-8x9Am",
                    ),
                ],
            ),
            InfrastructureNode(
                ip_addresses=["192.0.2.4"],  # removed ip addresses
                credentials=[
                    InfrastructureNodeCredential(
                        type="login",
                        username="user1",
                        password="PASSWORD-changed",  # changed credential secret
                        private_key="PRIVATE_KEY-B35r0",
                    ),
                    # removed credential
                ],
            ),
        ],
    )

    # Create observer and run target method
    api_server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        infra_provider_cluster_observer = \
            infra_controller_hooks.InfrastructureProviderClusterObserver(
                resource=cluster,
                on_res_update=mock.Mock(),
                client=client,
                time_step=1,
            )

        # Test initial observation
        returned = \
            await infra_provider_cluster_observer.check_observation(observation_1)

        cluster_copy.infrastructure = ClusterInfrastructure(data=observation_1)
        assert returned == (True, cluster_copy)

        # Test initial observation was already made
        infra_provider_cluster_observer.resource = cluster_copy
        returned = \
            await infra_provider_cluster_observer.check_observation(observation_1)

        assert returned == (False, None)

        # Test second observation
        infra_provider_cluster_observer.resource = cluster_copy
        returned = \
            await infra_provider_cluster_observer.check_observation(observation_2)

        cluster_copy.infrastructure = ClusterInfrastructure(data=observation_2)
        assert returned == (True, cluster_copy)

        # Test third observation
        infra_provider_cluster_observer.resource = cluster_copy
        returned = \
            await infra_provider_cluster_observer.check_observation(observation_3)

        cluster_copy.infrastructure = ClusterInfrastructure(data=observation_3)
        assert returned == (True, cluster_copy)

        # Test third observation was already made
        cluster_copy.infrastructure = ClusterInfrastructure(data=observation_3)
        infra_provider_cluster_observer.resource = cluster_copy
        returned = \
            await infra_provider_cluster_observer.check_observation(observation_3)

        assert returned == (False, None)

        # Test fourth observation
        infra_provider_cluster_observer.resource = cluster_copy
        returned = \
            await infra_provider_cluster_observer.check_observation(observation_4)

        cluster_copy.infrastructure = ClusterInfrastructure(data=observation_4)
        assert returned == (True, cluster_copy)


async def test_InfrastructureProviderClusterObserver_update_resource(monkeypatch):
    """Test the `update_resource` method of the
    `InfrastructureProviderClusterObserver` class.

    Tests that the infrastructure provider cluster observer correctly triggers an update
    with a changed resource object.

    Asserts:
        that the `on_res_update` hook is called once.
        that the observer's cluster resource object is updated.
        that no other method was called.
    """

    # Create observer
    cluster = ClusterFactory()
    updated_cluster = deepcopy(cluster)
    updated_cluster.infrastructure = \
        ClusterInfrastructure(data=ClusterInfrastructureData(nodes=[]))

    on_res_update_mock = mock.AsyncMock(side_effect=lambda resource: resource)
    client_mock = mock.AsyncMock()

    infra_provider_cluster_observer = \
        infra_controller_hooks.InfrastructureProviderClusterObserver(
            resource=cluster,
            on_res_update=on_res_update_mock,
            client=client_mock,
            time_step=1,
        )

    # Mock all other observer methods
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'observe_resource', mock.AsyncMock())
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'fetch_actual_resource', mock.AsyncMock())
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'check_observation', mock.AsyncMock())

    # Run observer update
    assert infra_provider_cluster_observer.resource == cluster
    await infra_provider_cluster_observer.update_resource(updated_cluster)

    # Assert that the given update hook was called with the updated cluster
    on_res_update_mock.assert_called_once_with(updated_cluster)

    # Assert that the observer's internal resource copy was updated
    assert infra_provider_cluster_observer.resource == updated_cluster

    # Assert that none of the other observer's callables has been used
    infra_provider_cluster_observer.observe_resource.assert_not_called()
    infra_provider_cluster_observer.fetch_actual_resource.assert_not_called()
    infra_provider_cluster_observer.check_observation.assert_not_called()
    client_mock.assert_not_called()


async def test_InfrastructureProviderClusterObserver_observe_resource(monkeypatch):
    """Test the `observe_resource` method of the
    `InfrastructureProviderClusterObserver` class.

    Tests that the infrastructure provider cluster observer is able to correctly
    observe its cluster resource and recognize changes.

    Asserts:
        that the actual cluster was observed (fetch + check) continously.
        that for every actual resource change an updated cluster resource was correctly
            from the new observed data.
        that nothing else was done.
    """

    observations = [
        ClusterInfrastructureData(nodes=[]),           # new
        ClusterInfrastructureData(nodes=[]),
        ClusterInfrastructureData(nodes=[]),
        ClusterInfrastructureData(                     # new
            nodes=[
                InfrastructureNode(
                    credentials=[
                        InfrastructureNodeCredential(
                            type="login",
                            username="user1",
                            password="PASSWORD-sl6r",
                        ),
                    ],
                ),
            ],
        )
    ]
    # NOTE: To receive all observations that shall be considered NEW
    #       we squash consecutive equal observations with `groupby`
    new_observations = [o for o, _ in groupby(observations)]

    # Create observer
    cluster = ClusterFactory(infrastructure=ClusterInfrastructure())
    on_res_update_mock = mock.AsyncMock()
    client_mock = mock.AsyncMock()
    time_step = 1

    infra_provider_cluster_observer = \
        infra_controller_hooks.InfrastructureProviderClusterObserver(
            resource=cluster,
            on_res_update=on_res_update_mock,
            client=client_mock,
            time_step=time_step,
        )

    # Create a mock for the `fetch_actual_resource` method
    # that serves our predefined observations
    async def async_observation_generator():
        for observation in observations:
            yield observation

    _generated_async_observations = async_observation_generator()

    async def fetch_actual_resource_mock():
        return await anext(_generated_async_observations)

    # Mock all other observer methods
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'run',
        mock.AsyncMock())
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'update_resource',
        mock.AsyncMock())
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'fetch_actual_resource',
        # generator mock
        mock.Mock(side_effect=fetch_actual_resource_mock))
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'check_observation',
        # passthrough mock
        mock.AsyncMock(side_effect=infra_provider_cluster_observer.check_observation))

    # Run observer observation
    # NOTE: Iterate to get all NEW observations
    updated_resources = []
    observe_resource = infra_provider_cluster_observer.observe_resource()
    for _ in range(len(new_observations)):
        updated_resource = await anext(observe_resource)  # only returns
                                                          #  for new observations
        updated_resources.append(updated_resource)
        # update internal resource to check against in next cycle
        infra_provider_cluster_observer.resource = updated_resource

    # Assert that correctly updated resources were returned for every NEW observation
    expected_updated_resources = []
    for observation in new_observations:
        _cluster = deepcopy(cluster)
        _cluster.infrastructure.data = observation
        expected_updated_resources.append(_cluster)

    assert updated_resources == expected_updated_resources

    # Assert that each observation was fetched and checked
    assert infra_provider_cluster_observer.fetch_actual_resource.call_count \
        == len(observations)
    infra_provider_cluster_observer.check_observation.assert_has_calls(
        calls=[mock.call(o) for o in observations], any_order=False
    )

    # Assert that none of the other observer's callables has been used
    infra_provider_cluster_observer.run.assert_not_called()
    infra_provider_cluster_observer.update_resource.assert_not_called()
    on_res_update_mock.assert_not_called()
    client_mock.assert_not_called()


async def test_InfrastructureProviderClusterObserver_run(monkeypatch):
    """Test the `run` method of the `InfrastructureProviderClusterObserver` class.

    Tests that the infrastructure provider cluster observer runs as expected --
    monitoring a cluster and triggering an resource update when changes were observed.

    Asserts:
        that the observer triggers resource updates after the monitoring of the cluster
            has been started once and changes were observed.
    """

    # Create observer
    on_res_update_mock = mock.AsyncMock()
    client_mock = mock.AsyncMock()

    infra_provider_cluster_observer = \
        infra_controller_hooks.InfrastructureProviderClusterObserver(
            resource=mock.Mock(),
            on_res_update=on_res_update_mock,
            client=client_mock,
            time_step=1,
        )

    # Mock all observer methods
    updated_clusters = [ClusterFactory() for _ in range(5)]

    async def async_cluster_generator():
        for cluster in updated_clusters:
            yield cluster

    monkeypatch.setattr(
        infra_provider_cluster_observer, 'observe_resource',
        mock.Mock(return_value=async_cluster_generator()))
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'update_resource',
        mock.AsyncMock())
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'fetch_actual_resource',
        mock.AsyncMock())
    monkeypatch.setattr(
        infra_provider_cluster_observer, 'check_observation',
        mock.AsyncMock())

    # Run observer
    # NOTE: Because the run method should return after all 5 updated_clusters have been
    #       processed, we give it a high timeout.
    await with_timeout(20, stop=True)(infra_provider_cluster_observer.run)()

    # Assert that an observation was started once
    # and that it triggered 5 update calls with the correct cluster resources in order
    infra_provider_cluster_observer.observe_resource.assert_called_once_with()
    infra_provider_cluster_observer.update_resource.assert_has_calls(
        calls=[mock.call(cluster) for cluster in updated_clusters],
        any_order=False
    )
    # Assert that none of the other observer's callables has been used
    infra_provider_cluster_observer.fetch_actual_resource.assert_not_called()
    infra_provider_cluster_observer.check_observation.assert_not_called()
    on_res_update_mock.assert_not_called()
    client_mock.assert_not_called()
