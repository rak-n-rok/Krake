from aiohttp import web
from copy import deepcopy
from functools import wraps
import pytest
from unittest import mock
from random import randint
import yaml

from krake.client import Client
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
