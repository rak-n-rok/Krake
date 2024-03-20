from asyncio import AbstractEventLoop
from copy import deepcopy
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
@pytest.fixture(scope='function')
def controller(loop: AbstractEventLoop) -> KubernetesApplicationController:
    cluster = ClusterFactory()

    kubernetes_api_mock: KubernetesApi = AsyncMock()
    kubernetes_api_mock.read_application.return_value = app_shutdown_hook
    kubernetes_api_mock.read_cluster.return_value = cluster
    kubernetes_api_mock.update_application_status.return_value = \
        ApplicationFactory(status__state=ApplicationState.WAITING_FOR_CLEANING)

    controller = KubernetesApplicationController(
        "http://krake.api", loop=loop
    )

    controller.kubernetes_api = kubernetes_api_mock
    return controller


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


@patch.object(KubernetesClient, 'delete_async')
@patch.object(KubernetesClient, 'shutdown_async')
async def test_shutdown_failure_give_up(
    shutdown_async: AsyncMock,
    delete_async: AsyncMock,
    app_shutdown_hook: Application,
    hooks_config: HooksConfiguration,
    controller: KubernetesApplicationController
):
    """ Enusure strategy 'give_up' calls shutdown and does not delete any ressources
    """

    hooks_config.shutdown.failure_strategy = ShutdownHookFailureStrategy.GIVE_UP.value
    hooks_config.shutdown.failure_retry_count = 0

    controller.hooks = hooks_config

    await controller._shutdown_task_async(app_shutdown_hook)
    delete_async.assert_not_called()

    shutdown_async.assert_called_once()


@patch.object(KubernetesClient, 'delete_async')
@patch.object(KubernetesClient, 'shutdown_async')
async def test_shutdown_failure_delete(
    shutdown_async: AsyncMock,
    delete_async: AsyncMock,
    app_shutdown_hook: Application,
    hooks_config: HooksConfiguration,
    controller: KubernetesApplicationController
):
    """ Enusure strategy delete calls shutdown and deletes all ressources of the
      application
      """

    hooks_config.shutdown.failure_strategy = ShutdownHookFailureStrategy.DELETE.value
    hooks_config.shutdown.failure_retry_count = 0

    controller.hooks = hooks_config

    await controller._shutdown_task_async(app_shutdown_hook)

    # check that all manifests of the application were deleted
    assert delete_async.call_count == len(nginx_manifest)

    for call_args in delete_async.call_args_list:
        call_args.args[0] in nginx_manifest

    shutdown_async.assert_called_once()
    assert app_shutdown_hook.status.state == ApplicationState.DELETING


@patch.object(KubernetesClient, 'delete_async')
@patch.object(KubernetesClient, 'shutdown_async')
async def test_shutdown_failure_retries(
    shutdown_async: AsyncMock,
    delete_async: AsyncMock,
    app_shutdown_hook: Application,
    hooks_config: HooksConfiguration,
    controller: KubernetesApplicationController
):
    """ Enusure strategy shutdown is shutdown is attempted as often as specified retry
    count
    """

    retry_count = 3
    hooks_config.shutdown.failure_strategy = ShutdownHookFailureStrategy.GIVE_UP.value
    hooks_config.shutdown.failure_retry_count = retry_count

    controller.hooks = hooks_config

    await controller._shutdown_task_async(app_shutdown_hook)
    delete_async.assert_not_called()

    assert shutdown_async.call_count == retry_count + 1


@patch.object(KubernetesClient, 'shutdown_async')
@pytest.mark.parametrize("app_state", [ApplicationState.FAILED, ApplicationState.DEGRADED])
async def test_shutdown_failed_state(
    shutdown_async: AsyncMock,
    app_state,
    app_shutdown_hook,
    hooks_config,
    controller: KubernetesApplicationController
):
    """ Ensure no shutdown request is sent to application if has failed or degraded as
    application state
    """

    app_shutdown_hook.status.state = app_state
    controller.hooks = hooks_config

    await controller._shutdown_task_async(app_shutdown_hook)

    shutdown_async.assert_not_called()

# endregion Unit tests
