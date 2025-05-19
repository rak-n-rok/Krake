from asyncio import AbstractEventLoop
import asyncio
from copy import deepcopy
from typing import List
from aiohttp import ClientResponseError
from mock import AsyncMock, MagicMock, patch
import pytest

from krake.controller.kubernetes.application.application import (
    KubernetesApplicationController,
)
from krake.controller.kubernetes.client import KubernetesClient
from krake.data.config import HooksConfiguration
from krake.data.kubernetes import Application, ApplicationState
from krake import utils
from krake.data.hooks.enums import ShutdownHookFailureStrategy
from krake.client.kubernetes import KubernetesApi
from tests.factories.kubernetes import ApplicationFactory, ClusterFactory

from tests.controller.kubernetes import (
    custom_deployment_observer_schema,
    nginx_manifest,
)


# region Arrangement
@pytest.fixture
def controller(
    loop: AbstractEventLoop, hooks_config: HooksConfiguration
) -> KubernetesApplicationController:
    cluster = ClusterFactory()

    kubernetes_api_mock: KubernetesApi = AsyncMock()
    kubernetes_api_mock.read_application.return_value = app_shutdown_hook
    kubernetes_api_mock.read_cluster.return_value = cluster
    kubernetes_api_mock.update_application_status.return_value = ApplicationFactory(
        status__state=ApplicationState.WAITING_FOR_CLEANING
    )

    controller = KubernetesApplicationController("http://krake.api", loop=loop)

    controller.kubernetes_api = kubernetes_api_mock

    hooks_config.shutdown.timeout = 0
    hooks_config.shutdown.failure_strategy = ShutdownHookFailureStrategy.GIVE_UP.value
    hooks_config.shutdown.failure_retry_count = 0

    controller.hooks = hooks_config
    return controller


@pytest.fixture
def app_shutdown_hook() -> Application:
    """creates application as specified in the nginx_manifest"""
    return ApplicationFactory(
        metadata__finalizers=["kubernetes_resources_deletion"],
        status__state=ApplicationState.WAITING_FOR_CLEANING,
        status__shutdown_grace_period=utils.now(),
        status__last_observed_manifest=deepcopy(nginx_manifest),
        spec__hooks=["shutdown"],
        spec__manifest=deepcopy(nginx_manifest),
        spec__observer_schema=[custom_deployment_observer_schema],
    )


# endregion Arrangement


# region Helper methods
def assert_application_deletion(delete_async: AsyncMock, manifest: List[dict]):
    """Asserts that all ressources of the manifest were deleted

    Args:
        delete_async (AsyncMock): Patched method of the deletion
            method of the KubernetesClient
        manifest (List[dict]): List of manifests that are part of the
            application
    """
    assert delete_async.call_count == len(manifest)

    for call_args in delete_async.call_args_list:
        call_args.args[0] in manifest


# endregion Helper methods


# region Unit tests
# region Shutdown strategies
@patch.object(KubernetesClient, KubernetesClient.delete_async.__name__)
@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__)
async def test_shutdown_failure_give_up(
    shutdown_async: AsyncMock,
    delete_async: AsyncMock,
    app_shutdown_hook: Application,
    controller: KubernetesApplicationController,
):
    """Enusure strategy 'give_up' calls shutdown and does not delete any ressources"""

    await controller._shutdown_task_async(app_shutdown_hook)
    delete_async.assert_not_called()

    shutdown_async.assert_called_once()


@patch.object(KubernetesClient, KubernetesClient.delete_async.__name__)
@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__)
async def test_shutdown_failure_delete(
    shutdown_async: AsyncMock,
    delete_async: AsyncMock,
    app_shutdown_hook: Application,
    controller: KubernetesApplicationController,
):
    """Enusure strategy delete calls shutdown and deletes all ressources of the
    application
    """

    controller.hooks.shutdown.failure_strategy = (
        ShutdownHookFailureStrategy.DELETE.value
    )

    await controller._shutdown_task_async(app_shutdown_hook)

    shutdown_async.assert_called_once()
    # check that all manifests of the application were deleted
    assert_application_deletion(delete_async, app_shutdown_hook.spec.manifest)
    assert app_shutdown_hook.status.state == ApplicationState.DELETING


@patch.object(KubernetesClient, KubernetesClient.delete_async.__name__)
@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__)
async def test_shutdown_failure_retries(
    shutdown_async: AsyncMock,
    delete_async: AsyncMock,
    app_shutdown_hook: Application,
    controller: KubernetesApplicationController,
):
    """Enusure strategy shutdown is shutdown is attempted as often as specified retry
    count
    """

    retry_count = 3
    controller.hooks.shutdown.failure_retry_count = retry_count

    await controller._shutdown_task_async(app_shutdown_hook)
    delete_async.assert_not_called()

    assert shutdown_async.call_count == retry_count + 1


@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__)
@pytest.mark.parametrize(
    "app_state", [ApplicationState.FAILED, ApplicationState.DEGRADED]
)
async def test_shutdown_failed_state(
    shutdown_async: AsyncMock,
    app_state: ApplicationState,
    app_shutdown_hook: Application,
    controller: KubernetesApplicationController,
):
    """Ensure no shutdown request is sent to application if has failed or degraded as
    application state
    """

    app_shutdown_hook.status.state = app_state

    await controller._shutdown_task_async(app_shutdown_hook)

    shutdown_async.assert_not_called()


# endregion


# region Configuration
@patch.object(asyncio, asyncio.sleep.__name__)
async def test_global_timeout_configuration(
    asnycio_sleep: AsyncMock,
    app_shutdown_hook: Application,
    controller: KubernetesApplicationController,
):
    """Ensure shutdown uses the global timeout configuration to wait
    until the check for success is executed in case no timeout for the
    app was specified
    """
    expected_sleep_duration = 42

    app_shutdown_hook.spec.shutdown_grace_time = None
    controller.hooks.shutdown.timeout = expected_sleep_duration

    with patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__):
        await controller._shutdown_task_async(app_shutdown_hook)

    asnycio_sleep.assert_called_once_with(expected_sleep_duration)


@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__, AsyncMock())
@patch.object(asyncio, asyncio.sleep.__name__)
async def test_shutdown_with_app_timeout_configuration(
    asnycio_sleep: AsyncMock,
    app_shutdown_hook: Application,
    controller: KubernetesApplicationController,
):
    """Ensure shutdown uses the apps local configuration to wait
    until the check for success is done
    """
    expected_sleep_duration = 42

    app_shutdown_hook.spec.shutdown_grace_time = expected_sleep_duration
    controller.hooks.shutdown.timeout = expected_sleep_duration - 10

    await controller._shutdown_task_async(app_shutdown_hook)

    asnycio_sleep.assert_called_once_with(expected_sleep_duration)


@patch.object(asyncio, asyncio.sleep.__name__, AsyncMock())
@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__, AsyncMock())
@patch.object(KubernetesClient, KubernetesClient.delete_async.__name__)
async def test_app_overwrites_failure_strategy(
    delete_async: AsyncMock,
    controller: KubernetesApplicationController,
    app_shutdown_hook: Application,
):
    """Ensure shutdown uses the apps local failure strategy configuration if set"""
    app_shutdown_hook.spec.shutdown_failure_strategy = (
        ShutdownHookFailureStrategy.DELETE.value
    )

    await controller._shutdown_task_async(app_shutdown_hook)

    assert_application_deletion(delete_async, app_shutdown_hook.spec.manifest)


@patch.object(KubernetesClient, KubernetesClient.delete_async.__name__)
@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__)
async def test_app_overwrites_failure_retry_count(
    shutdown_async: AsyncMock,
    app_shutdown_hook: Application,
    controller: KubernetesApplicationController,
):
    """Enusure strategy shutdown is attempted as often as specified in the retry
    count of the app instead of the global configuration
    """
    retry_count = 3

    app_shutdown_hook.spec.shutdown_retry_count = retry_count
    controller.hooks.shutdown.failure_retry_count = retry_count + 1

    await controller._shutdown_task_async(app_shutdown_hook)
    assert shutdown_async.call_count == retry_count + 1


# endregion Configuration


# region Check shutdown success
@patch.object(KubernetesClient, KubernetesClient.shutdown_async.__name__, AsyncMock())
async def test_shutdown_success_check_success(
    app_shutdown_hook: Application, controller: KubernetesApplicationController
):
    """
    Ensures that no failure strategy is executed
    if the graceful shutdown succeeded
    """
    controller._handle_shutdown_failure_async = MagicMock()

    controller.kubernetes_api.read_application_async = AsyncMock()
    controller.kubernetes_api.read_application_async.side_effect = ClientResponseError(
        status=404, request_info=None, history=None
    )
    await controller._shutdown_task_async(app_shutdown_hook)

    controller.kubernetes_api.read_application_async.assert_called_once()
    controller._handle_shutdown_failure_async.assert_not_called()


# endregion Check shutdown success

# endregion Unit tests
