from copy import deepcopy
from typing import Any
from unittest.mock import Mock
from mock import AsyncMock, patch
import pytest

from krake.controller.kubernetes.application.application \
    import KubernetesApplicationController
from krake.controller.kubernetes.client import KubernetesClient
from krake.data.config import HooksConfiguration
from krake.data.kubernetes import Application, ApplicationState
from krake import utils
from krake.data.hooks.enums import ShutdownHookFailureStrategy
from krake.api.kubernetes import KubernetesApi
from tests.factories.kubernetes import ApplicationFactory, ClusterFactory

from tests.controller.kubernetes import (
    custom_deployment_observer_schema,
    nginx_manifest
)

# region Arrangement
@pytest.fixture
def app_shutdown_hook() -> Application:
    """ creates application as specified in the nginx_manifest
    """
    return ApplicationFactory(
        metadata__finalizers=['kubernetes_resources_deletion'],
        status__state=ApplicationState.WAITING_FOR_CLEANING,
        status__shutdown_grace_period=utils.now(),
        status__last_observed_manifest=deepcopy(nginx_manifest),
        spec__hooks=["shutdown"],
        spec__manifest=deepcopy(nginx_manifest),
        spec__observer_schema=[custom_deployment_observer_schema],
        spec__shutdown_grace_time=0
    )

def get_delete_async_patch():
    return patch("krake.controller.kubernetes.client.KubernetesClient.delete_async")
# endregion Arrangement

# region Unit tests
async def test_shutdown_failure_give_up(
        app_shutdown_hook: Application,
        hooks_config: HooksConfiguration,
        ):
    """ Enusure strategy 'give_up' calls shutdown and does not delete any ressources
    """

    hooks_config.shutdown.failure_strategy = ShutdownHookFailureStrategy.GIVE_UP.value
    hooks_config.shutdown.failure_retry_count = 0
    controller = KubernetesApplicationController("http://krake.api", hooks=hooks_config)

    kubernetes_client_mock : KubernetesClient = Mock()
    with get_delete_async_patch() as delete_async_patch:
        await controller._run_app_shutdown_strategy_async(kubernetes_client_mock,
                                                              app_shutdown_hook)
        delete_async_patch.assert_not_called()

    kubernetes_client_mock.shutdown_async.assert_called_once()


async def test_shutdown_failure_delete(
    app_shutdown_hook: Application,
    hooks_config: HooksConfiguration
):
    """ Enusure strategy delete calls shutdown and deletes all ressources of the
      application
      """
    
    hooks_config.shutdown.failure_strategy = ShutdownHookFailureStrategy.DELETE.value
    hooks_config.shutdown.failure_retry_count = 0
    
    kubernetes_client_mock: KubernetesClient = AsyncMock()

    cluster = ClusterFactory()

    kubernetes_api_mock: KubernetesApi = AsyncMock()
    kubernetes_api_mock.read_application.return_value = app_shutdown_hook
    kubernetes_api_mock.read_cluster.return_value = cluster
    kubernetes_api_mock.update_application_status.return_value = \
        ApplicationFactory(status__state=ApplicationState.WAITING_FOR_CLEANING)


    controller = KubernetesApplicationController(
        "http://krake.api",
        hooks=hooks_config,
    )

    controller.kubernetes_api = kubernetes_api_mock

    with get_delete_async_patch() as delete_async_patch:
        await controller._run_app_shutdown_strategy_async(
            kubernetes_client_mock,
            app_shutdown_hook)
        
        # check that all manifests of the application were deleted
        assert delete_async_patch.call_count == len(nginx_manifest)

        for call_args in delete_async_patch.call_args_list:
            call_args.args[0] in nginx_manifest

    
    kubernetes_client_mock.shutdown_async.assert_called_once()
    assert app_shutdown_hook.status.state == ApplicationState.DELETING


async def test_shutdown_failure_retries(
        app_shutdown_hook: Application,
        hooks_config: HooksConfiguration,
        ):
    """ Enusure strategy shutdown is shutdown is attempted as often as specified retry count
    """
    
    retry_count = 3
    hooks_config.shutdown.failure_strategy = ShutdownHookFailureStrategy.GIVE_UP.value
    hooks_config.shutdown.failure_retry_count = retry_count

    controller = KubernetesApplicationController("http://krake.api", hooks=hooks_config)

    kubernetes_client_mock : KubernetesClient = Mock()
    with get_delete_async_patch() as delete_async_patch:
        await controller._run_app_shutdown_strategy_async(kubernetes_client_mock,
                                                              app_shutdown_hook)
        delete_async_patch.assert_not_called()

    assert kubernetes_client_mock.shutdown_async.call_count == retry_count + 1
# endregion Unit tests
    
