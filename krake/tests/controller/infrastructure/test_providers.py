from aiohttp import web
from copy import deepcopy
from functools import wraps
import pytest
from unittest import mock
from random import randint
import yaml

from krake.client import Client
from krake.data.infrastructure import (
    InfrastructureProviderCluster,
    InfrastructureProviderVm,
    InfrastructureProviderVmCredential,
)
from krake.test_utils import server_endpoint

from krake.controller.infrastructure import providers

from tests.factories import fake
from tests.factories.infrastructure import (
    CloudFactory,
    GlobalCloudFactory,
    InfrastructureProviderFactory,
    GlobalInfrastructureProviderFactory,
)
from tests.factories.kubernetes import ClusterFactory


TOSCA_CLUSTER_MINIMAL = {
    "tosca_definitions_version": "tosca_simple_yaml_1_0",
    "topology_template": {"outputs": {"kubeconfig": {"value": "test"}}},
}


def record_aiohttp_requests(recorder, endpoint=None, method=None):
    """Record aiohttp requests.

    Decorator that records every request to `endpoint` by calling the given `recorder`
    object and passing the request's content to it.
    """
    context = dict()
    if endpoint is not None:
        context["endpoint"] = endpoint
    if method is not None:
        context["method"] = method

    def decorator(handler):
        @wraps(handler)
        async def wrapper(request):
            recorder(
                **context,
                content=await request.text(),
            )
            return await handler(request)
        return wrapper
    return decorator


# TODO: Test errors and InfrastructureProvider class.
# TODO: Add negative unittests


@pytest.mark.parametrize(
    "infrastructure_provider_factory,cloud_factory",
    [
        (GlobalInfrastructureProviderFactory, GlobalCloudFactory),
        (GlobalInfrastructureProviderFactory, CloudFactory),
        (InfrastructureProviderFactory, CloudFactory),
    ],
)
async def test_infra_provider_client_creation_for_openstack_cloud(
    aiohttp_server, config, db, loop, infrastructure_provider_factory, cloud_factory
):
    """Test the creation of an infrastructure provider client for an openstack client.

    Tests that the correct type of infrastructure provider client is choosen and
    successfully created for a given openstack cloud.

    Parameter sets:
        GlobalInfrastructureProviderFactory, GlobalCloudFactory
        GlobalInfrastructureProviderFactory, CloudFactory
        InfrastructureProviderFactory, CloudFactory

    Steps:
        1. Mock bare infrastructure manager server
        2. Create infrastructure provider object with the needed auth data
        3. Create an openstack cloud object with the needed auth data
        4. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object

    Asserts:
        infrastructure provider client type is :class:`krake.controller.infrastructure.
            providers.InfrastructureManager`
        infrastructure provider client attributes are correctly set
        infrastructure provider client auth header is generated correctly
    """

    # Create infrastructure manager server with no endpoints
    # NOTE: Infrastructure manager is mocked here
    #       because we are dealing with a cloud of type "openstack"
    im_app = web.Application()
    im_app.add_routes(web.RouteTableDef())
    im_server = await aiohttp_server(im_app, port=randint(30000, 50000))

    # Create the required Krake resources in the Krake database
    infra_provider = infrastructure_provider_factory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = cloud_factory(
        spec__type="openstack",
        spec__openstack__url="http://example.com/",
        spec__openstack__auth__password__version=randint(1, 9),
        spec__openstack__auth__password__user__username=fake.name(),
        spec__openstack__auth__password__user__password=fake.password(),
        spec__openstack__auth__password__project__name=fake.name(),
    )
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Assert that the correct type of client was created
        assert isinstance(infra_provider_client, providers.InfrastructureManager)

        # Assert that the client has got the correct attributes
        assert infra_provider_client.session == client.session
        assert infra_provider_client.cloud == cloud
        assert infra_provider_client.infrastructure_provider == infra_provider
        assert infra_provider_client._auth_header == (
            f"id = {infra_provider.metadata.name};"
            f"username = {infra_provider.spec.im.username};"
            f"password = {infra_provider.spec.im.password};"
            f"type = InfrastructureManager"
            f"\\n"
            f"id = {cloud.metadata.name};"
            f"host = {cloud.spec.openstack.url};"
            f"auth_version = {cloud.spec.openstack.auth.password.version}.x_password;"
            f"username = {cloud.spec.openstack.auth.password.user.username};"
            f"password = {cloud.spec.openstack.auth.password.user.password};"
            f"tenant = {cloud.spec.openstack.auth.password.project.name};"
            f"type = OpenStack"
        )


async def test_InfrastuctureManager_create(aiohttp_server, config, db, loop):
    """Test the `create` method of the `InfrastructureManager` class.

    Tests that the creation of a given cluster is correctly requested from the
    infrastructure manager (correct method, path and spec)
    and the infrastructure UUID of the created cluster is returned.

    Steps:
        1. Mock infrastructure manager server
           and inject infrastructure UUID
           and attach API request recorder
        2. Create infrastructure provider object (with credentials)
        3. Create an openstack cloud object
        4. Create a cluster
        5. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object
        6. Run the target method `create`

    Asserts:
        infrastructure manager client request (method, path, content, one call)
        return value of :meth:`krake.controller.infrastructure.providers.
            InfrastructureManager.create`
    """

    cluster_tosca = deepcopy(TOSCA_CLUSTER_MINIMAL)

    # Mock the infrastructure manager API endpoints that will be called
    # NOTE: Examples taken from real infrastructure manager API responses
    routes = web.RouteTableDef()
    im_server_port = randint(30000, 50000)
    infra_uuid = fake.uuid4()

    infra_create_recorder = mock.Mock()  # use mock object for recording

    @routes.post("/infrastructures")
    @record_aiohttp_requests(infra_create_recorder)
    async def _(request):
        return web.Response(
            content_type="text/uri-list",
            text=f"http://localhost:{im_server_port}/infrastructures/{infra_uuid}",
        )

    # Create infrastructure manager server with the mocked API endpoint
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create the required Krake resources in the Krake database
    infra_provider = InfrastructureProviderFactory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
        spec__im__username=fake.name(),
        spec__im__password=fake.password(),
    )
    cloud = CloudFactory(spec__type="openstack")
    cluster = ClusterFactory(spec__tosca=cluster_tosca)
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Assert that the correct type of client was created
        assert isinstance(infra_provider_client, providers.InfrastructureManager)

        # Run target method
        returned = await infra_provider_client.create(cluster)

    # Assert that cluster creation was correctly requested from the infra manager
    infra_create_recorder.assert_called_once_with(
        content=yaml.dump(cluster_tosca)
    )

    # Assert that the target method returned the expected infrastructure UUID
    assert returned == infra_uuid


async def test_InfrastuctureManager_reconcile(aiohttp_server, config, db, loop):
    """Test the `reconcile` method of the `InfrastructureManager` class.

    Tests that the reconcilation of a given cluster is correctly requested from the
    infrastructure manager (correct method, path and spec).

    Steps:
        1. Mock infrastructure manager server
           and inject infrastructure UUID
           and attach API request recorder
        2. Create infrastructure provider object
        3. Create an openstack cloud object
        4. Create a cluster
        5. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object
        6. Run the target method `reconcile`

    Asserts:
        infrastructure manager client request (method, path, content, one call)
        return value of :meth:`krake.controller.infrastructure.providers.
            InfrastructureManager.reconcile`
    """

    cluster_tosca = deepcopy(TOSCA_CLUSTER_MINIMAL)

    # Mock the infrastructure manager API endpoints that will be called
    routes = web.RouteTableDef()
    im_server_port = randint(30000, 50000)
    infra_uuid = fake.uuid4()

    infra_update_recorder = mock.Mock()  # use mock object for recording

    @routes.post("/infrastructures/{infra_uuid}")
    @record_aiohttp_requests(infra_update_recorder)
    async def _(request):
        return web.Response()

    # Create infrastructure manager server with the mocked API endpoint
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create the required Krake resources in the Krake database
    infra_provider = InfrastructureProviderFactory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
    )
    cloud = CloudFactory(spec__type="openstack")
    cluster = ClusterFactory(
        status__cluster_id=infra_uuid,
        spec__tosca=cluster_tosca,
    )
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Run target method
        returned = await infra_provider_client.reconcile(cluster)

    # Assert that the target method returned
    assert returned is None

    # Assert that the cluster update was correctly sent to the infra manager
    infra_update_recorder.assert_called_once_with(
        content=yaml.dump(cluster_tosca)
    )


async def test_InfrastuctureManager_reconfigure(aiohttp_server, config, db, loop):
    """Test the `reconfigure` method of the `InfrastructureManager` class.

    Tests that the reconfiguration of a given cluster is correctly requested from the
    infrastructure manager (correct method, path and spec).

    Steps:
        1. Mock infrastructure manager server
           and inject infrastructure UUID
           and attach API request recorder
        2. Create infrastructure provider object
        3. Create an openstack cloud object
        4. Create a cluster
        5. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object
        6. Run the target method `reconfigure`

    Asserts:
        infrastructure manager client request (method, path, content, one call)
        return value of :meth:`krake.controller.infrastructure.providers.
            InfrastructureManager.reconfigure`
    """

    # Mock the infrastructure manager API endpoints that will be called
    routes = web.RouteTableDef()
    im_server_port = randint(30000, 50000)
    infra_uuid = fake.uuid4()

    infra_reconfigure_recorder = mock.Mock()  # use mock object for recording

    @routes.put("/infrastructures/{infra_uuid}/reconfigure")
    @record_aiohttp_requests(infra_reconfigure_recorder)
    async def _(request):
        return web.Response()

    # Create infrastructure manager server with the mocked API endpoint
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create the required Krake resources in the Krake database
    infra_provider = InfrastructureProviderFactory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
    )
    cloud = CloudFactory(spec__type="openstack")
    cluster = ClusterFactory(
        status__cluster_id=infra_uuid,
        # no tosca spec needed for reconfiguration
    )
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Run target method
        returned = await infra_provider_client.reconfigure(cluster)

    # Assert that the target method returned
    assert returned is None

    # Assert that the cluster reconfig was correctly requested from the infra manager
    infra_reconfigure_recorder.assert_called_once_with(content="")


async def test_InfrastuctureManager_delete(aiohttp_server, config, db, loop):
    """Test the `delete` method of the `InfrastructureManager` class.

    Tests that the deletion of a given cluster is correctly requested from the
    infrastructure manager (correct method and path).

    Steps:
        1. Mock infrastructure manager server
           and inject infrastructure UUID
           and attach API request recorder
        2. Create infrastructure provider object
        3. Create an openstack cloud object
        4. Create a cluster
        5. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object
        6. Run the target method `delete`

    Asserts:
        infrastructure manager client request (method, path, content, one call)
        return value of :meth:`krake.controller.infrastructure.providers.
            InfrastructureManager.delete`
    """

    # Mock the infrastructure manager API endpoints that will be called
    routes = web.RouteTableDef()
    im_server_port = randint(30000, 50000)
    infra_uuid = fake.uuid4()

    infra_delete_recorder = mock.Mock()  # use mock object for recording

    @routes.delete("/infrastructures/{infra_uuid}")
    @record_aiohttp_requests(infra_delete_recorder)
    async def _(request):
        return web.Response()

    # Create infrastructure manager server with the mocked API endpoint
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create the required Krake resources in the Krake database
    infra_provider = InfrastructureProviderFactory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
    )
    cloud = CloudFactory(spec__type="openstack")
    cluster = ClusterFactory(
        status__cluster_id=infra_uuid,
        # no tosca spec needed for deletion
    )
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Run target method
        returned = await infra_provider_client.delete(cluster)

    # Assert that the target method returned
    assert returned is None

    # Assert that the cluster reconfig was correctly requested from the infra manager
    infra_delete_recorder.assert_called_once_with(content="")


# TODO: Implement the following test
# async def test_InfrastuctureManager_get_state(aiohttp_server, config, db, loop):
#     """Test the `get_state` method of the `InfrastructureManager` class.
#
#     Tests that the state of a given cluster is correctly retrieved from the
#     infrastructure manager.
#
#     TODO: Explain testing strategy: consideration of partial VM states, etc.
#
#     Steps:
#         TBD
#
#     Asserts:
#         TBD
#     """
#     pass


async def test_InfrastuctureManager_get_kubeconfig(aiohttp_server, config, db, loop):
    """Test the `get_kubeconfig` method of the `InfrastructureManager` class.

    Tests that the kubeconfig of a given cluster is correctly retrieved from the
    infrastructure manager (correct method, path and config).

    Steps:
        1. Mock infrastructure manager server
           and inject infrastructure UUID, kubeconfig
           and attach API request recorder
        2. Create infrastructure provider object
        3. Create an openstack cloud object
        4. Create a cluster
        5. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object
        6. Run the target method `get_kubeconfig`

    Asserts:
        infrastructure manager client request (method, path, content, one call)
        return value of :meth:`krake.controller.infrastructure.providers.
            InfrastructureManager.get_kubeconfig`
    """

    # Example serialized kubeconfig
    # taken from a real infrastructure manager API response
    serialized_kubeconfig = (
        "apiVersion: v1\n"
        "clusters:\n"
        "- cluster:\n"
        "    certificate-authority-data: LS0tCg==\n"  # value truncated
        "    server: https://example.com:6443\n"  # host modified
        "  name: kubernetes\n"
        "contexts:\n"
        "- context:\n"
        "    cluster: kubernetes\n"
        "    user: kubernetes-admin\n"
        "  name: kubernetes-admin@kubernetes\n"
        "current-context: kubernetes-admin@kubernetes\n"
        "kind: Config\n"
        "preferences: {}\n"
        "users:\n"
        "- name: kubernetes-admin\n"
        "  user:\n"
        "    client-certificate-data: LS0tCg==\n"  # value truncated
        "    client-key-data: LS0tLQo=\n"  # value truncated
    )
    kubeconfig = yaml.safe_load(serialized_kubeconfig)

    # Mock the infrastructure manager API endpoints that will be called
    routes = web.RouteTableDef()
    im_server_port = randint(30000, 50000)
    infra_uuid = fake.uuid4()

    infra_outputs_get_recorder = mock.Mock()  # use mock object for recording

    @routes.get("/infrastructures/{infra_uuid}/outputs")
    @record_aiohttp_requests(infra_outputs_get_recorder)
    async def _(request):
        return web.json_response(
            {
                "outputs": {
                    "kubeconfig": serialized_kubeconfig,
                },
            }
        )

    # Create infrastructure manager server with the mocked API endpoint
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create the required Krake resources in the Krake database
    infra_provider = InfrastructureProviderFactory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
    )
    cloud = CloudFactory(spec__type="openstack")
    cluster = ClusterFactory(status__cluster_id=infra_uuid)
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Run target method
        returned = await infra_provider_client.get_kubeconfig(cluster)

    # Assert that the target method returned the expected kubeconfig
    assert returned == kubeconfig

    # Assert that the kubeconfig was correctly requested from the infra manager
    infra_outputs_get_recorder.assert_called_once_with(content="")


async def test_InfrastuctureManager_get_vm(aiohttp_server, config, db, loop):
    """Test the `get_vm` method of the `InfrastructureManager` class.

    Tests that the VM information is correctly retrieved from the
    infrastructure manager (correct method, path and data).

    Steps:
        1. Mock infrastructure manager server
           and inject infrastructure UUID, VM information
           and attach API request recorder
        2. Create infrastructure provider object
        3. Create an openstack cloud object
        4. Create a cluster
        5. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object
        6. Run the target method `get_vm`

    Asserts:
        infrastructure manager client request (method, path, content, one call)
        return value of :meth:`krake.controller.infrastructure.providers.
            InfrastructureManager.get_vm`
    """

    # Mock the infrastructure manager API endpoints that will be called
    # NOTE: Examples taken from a real infrastructure manager API response
    #       and slightly modified
    routes = web.RouteTableDef()
    im_server_port = randint(30000, 50000)
    infra_uuid = fake.uuid4()

    vm_data_retrieval_recorder = mock.Mock()  # use mock object for recording

    @routes.get(f"/infrastructures/{infra_uuid}/vms/0")
    @record_aiohttp_requests(vm_data_retrieval_recorder)
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
                            "provider_id": f"im-{infra_uuid}-network_private",
                        },
                        {
                            "class": "network",
                            "id": "network_public",
                            "outbound": "yes",
                            "outports": "0.0.0.0/0-80/tcp-80/tcp,0.0.0.0/0-443/tcp-443/tcp",  # noqa: E501
                            "provider_id": "shared-public-IPv4",
                        },
                        {
                            "class": "system",
                            "id": "front",
                            "instance_name": "front-6e0882dc-d712-11ee-b2ec-e60cc0e9f147",  # noqa: E501
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
                            "disk.0.image.url": "ost://identity.example.com/802aecb9-7553-434d-a05c-cb8ce6103caa",  # noqa: E501
                            "disk.0.free_size": 26843545600,
                            "disk.0.os.credentials.username": "cloudadm",
                            "disk.1.os.credentials.username": "user2",
                            "provider.type": "OpenStack",
                            "provider.host": "identity.example.com",
                            "provider.port": 5000,
                            "disk.0.os.credentials.private_key": "PRIVATE_KEY-8x9Am",
                            "disk.1.os.credentials.password": "PASSWORD-3m91x",
                            "disk.1.os.credentials.private_key": "PRIVATE_KEY-d92sp",
                            "state": "running",
                            "instance_id": "5c205fb4-b1e0-4e78-ae1e-333ea18c1a27",
                            "net_interface.0.ip": "192.0.2.3",
                            "net_interface.1.ip": "203.0.113.3",
                        }
                    ]
                }
            )

    # Create infrastructure manager server with the mocked API endpoint
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create the required Krake resources in the Krake database
    infra_provider = InfrastructureProviderFactory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
    )
    cloud = CloudFactory(spec__type="openstack")
    cluster = ClusterFactory(status__cluster_id=infra_uuid)
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Run target method
        returned = await infra_provider_client.get_vm(cluster, 0)

    # Assert that the target method returned the expected vm data object
    assert returned == InfrastructureProviderVm(
        name="front-6e0882dc-d712-11ee-b2ec-e60cc0e9f147",
        ip_addresses=[
            "192.0.2.3",
            "203.0.113.3",
        ],
        credentials=[
            InfrastructureProviderVmCredential(
                username="cloudadm",
                password=None,
                private_key="PRIVATE_KEY-8x9Am",
            ),
            InfrastructureProviderVmCredential(
                username="user2",
                password="PASSWORD-3m91x",
                private_key="PRIVATE_KEY-d92sp",
            ),
        ],
    )

    # Assert that the kubeconfig was correctly requested from the infra manager
    vm_data_retrieval_recorder.assert_called_once_with(content="")


async def test_InfrastuctureManager_get(aiohttp_server, config, db, loop):
    """Test the `get` method of the `InfrastructureManager` class.

    Tests that cluster information is correctly retrieved from the
    infrastructure manager (correct calls and data).

    Steps:
        1. Mock infrastructure manager server
           and inject infrastructure UUID, VM information
           and attach API request recorder
        2. Create infrastructure provider object
        3. Create an openstack cloud object
        4. Create a cluster
        5. Create the infrastructure provider client from:
           - a client session of the infrastructure manager server
           - the openstack cloud object
           - the infrastructure provider object
        6. Run the target method `get`

    Asserts:
        infrastructure manager client requests (methods, paths, contents, call order)
        return value of :meth:`krake.controller.infrastructure.providers.
            InfrastructureManager.get`
    """

    # Mock the infrastructure provider API endpoints that will be called
    # NOTE: Examples taken from real infrastructure provider API responses and slightly
    #       altered for more variance and generality.

    routes = web.RouteTableDef()
    im_server_port = randint(30000, 50000)
    infra_uuid = fake.uuid4()

    infra_data_retrieval_recorder = mock.Mock()  # use mock object for recording

    @routes.get(f"/infrastructures/{infra_uuid}/vms/0")
    @record_aiohttp_requests(
        infra_data_retrieval_recorder,
        endpoint=f"/infrastructures/{infra_uuid}/vms/0", method="get")
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
                            "provider_id": f"im-{infra_uuid}-network_private",
                        },
                        {
                            "class": "network",
                            "id": "network_public",
                            "outbound": "yes",
                            "outports": "0.0.0.0/0-80/tcp-80/tcp,0.0.0.0/0-443/tcp-443/tcp",  # noqa: E501
                            "provider_id": "shared-public-IPv4",
                        },
                        {
                            "class": "system",
                            "id": "front",
                            "instance_name": "front-6e0882dc-d712-11ee-b2ec-e60cc0e9f147",  # noqa: E501
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
                            "disk.0.image.url": "ost://identity.example.com/802aecb9-7553-434d-a05c-cb8ce6103caa",  # noqa: E501
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

    @routes.get(f"/infrastructures/{infra_uuid}/vms/1")
    @record_aiohttp_requests(
        infra_data_retrieval_recorder,
        endpoint=f"/infrastructures/{infra_uuid}/vms/1", method="get")
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
                            "provider_id": f"im-{infra_uuid}-network_private",
                        },
                        {
                            "class": "network",
                            "id": "network_public",
                            "outbound": "yes",
                            "outports": "0.0.0.0/0-80/tcp-80/tcp,0.0.0.0/0-443/tcp-443/tcp",  # noqa: E501
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
                            "disk.0.image.url": "ost://identity.example.com/802aecb9-7553-434d-a05c-cb8ce6103caa",  # noqa: E501
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

    # Example serialized kubeconfig
    # taken from a real infrastructure manager API response
    serialized_kubeconfig = (
        "apiVersion: v1\n"
        "clusters:\n"
        "- cluster:\n"
        "    certificate-authority-data: LS0tCg==\n"  # value truncated
        "    server: https://example.com:6443\n"  # host modified
        "  name: kubernetes\n"
        "contexts:\n"
        "- context:\n"
        "    cluster: kubernetes\n"
        "    user: kubernetes-admin\n"
        "  name: kubernetes-admin@kubernetes\n"
        "current-context: kubernetes-admin@kubernetes\n"
        "kind: Config\n"
        "preferences: {}\n"
        "users:\n"
        "- name: kubernetes-admin\n"
        "  user:\n"
        "    client-certificate-data: LS0tCg==\n"  # value truncated
        "    client-key-data: LS0tLQo=\n"  # value truncated
    )
    kubeconfig = yaml.safe_load(serialized_kubeconfig)

    @routes.get("/infrastructures/{infra_uuid}/outputs")
    @record_aiohttp_requests(
        infra_data_retrieval_recorder,
        endpoint=f"/infrastructures/{infra_uuid}/outputs", method="get")
    async def _(request):
        return web.json_response(
            {
                "outputs": {
                    "kubeconfig": serialized_kubeconfig,
                },
            }
        )


    @routes.get(f"/infrastructures/{infra_uuid}")
    @record_aiohttp_requests(
        infra_data_retrieval_recorder,
        endpoint=f"/infrastructures/{infra_uuid}", method="get")
    async def _(request):
        if request.headers['Accept'] == 'application/json':
            return web.json_response(
                {
                    "uri-list": [
                        {"uri": f"http://localhost:{im_server_port}/infrastructures/{infra_uuid}/vms/0"},  # noqa: E501
                        {"uri": f"http://localhost:{im_server_port}/infrastructures/{infra_uuid}/vms/1"},  # noqa: E501
                    ]
                }
            )

    # Create infrastructure manager server with the mocked API endpoints
    # NOTE: Infrastructure manager is mocked here
    #       because we are dealing with a cloud of type "openstack"
    im_app = web.Application()
    im_app.add_routes(routes)
    im_server = await aiohttp_server(im_app, port=im_server_port)

    # Create the required Krake resources in the Krake database
    infra_provider = InfrastructureProviderFactory(
        spec__type="im",
        spec__im__url=server_endpoint(im_server),
    )
    cloud = CloudFactory(spec__type="openstack")
    cluster = ClusterFactory(status__cluster_id=infra_uuid)
    # Not creating an infrastructure provider binding as it is not needed here

    async with Client(url=server_endpoint(im_server), loop=loop) as client:
        # Create an infrastructure provider client
        infra_provider_client = providers.InfrastructureProvider(
            session=client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider
        )

        # Run target method
        returned = await infra_provider_client.get(cluster)

    # Assert that the target method returned the expected data object
    assert returned == InfrastructureProviderCluster(
        id=infra_uuid,
        vms=[
            InfrastructureProviderVm(
                name="front-6e0882dc-d712-11ee-b2ec-e60cc0e9f147",
                ip_addresses=["192.0.2.3", "203.0.113.3"],
                credentials=[
                    InfrastructureProviderVmCredential(
                        username="cloudadm",
                        password=None,
                        private_key="PRIVATE_KEY-8x9Am",
                    ),
                ],
            ),
            InfrastructureProviderVm(
                name="wn-6e04627e-d712-11ee-b5fb-e60cc0e9f147",
                ip_addresses=["192.0.2.4", "203.0.113.4"],
                credentials=[
                    InfrastructureProviderVmCredential(
                        username="user1",
                        password="PASSWORD-sl6r",
                        private_key="PRIVATE_KEY-B35r0",
                    ),
                    InfrastructureProviderVmCredential(
                        username="user2",
                        password="PASSWORD-s8c1",
                        private_key=None,
                    ),
                ],
            ),
        ],
        kubeconfig=kubeconfig,
    )

    # Assert that the cluster data was correctly requested from the infra manager
    # using the expected calls
    infra_data_retrieval_recorder.assert_has_calls(
        calls=[
            mock.call(
                endpoint=f"/infrastructures/{infra_uuid}", method="get",
                content="",
            ),
            mock.call(
                endpoint=f"/infrastructures/{infra_uuid}/vms/0", method="get",
                content="",
            ),
            mock.call(
                endpoint=f"/infrastructures/{infra_uuid}/vms/1", method="get",
                content="",
            ),
            mock.call(
                endpoint=f"/infrastructures/{infra_uuid}/outputs", method="get",
                content="",
            ),
        ],
        any_order=False,
    )
