import asyncio
import datetime
import logging
from contextlib import suppress
from copy import deepcopy
from functools import partial

from kubernetes_asyncio.client.rest import ApiException

from ..hooks import listen, HookType
from krake.client.kubernetes import KubernetesApi
from krake.controller import Controller, Reflector, ControllerError
from krake.controller.kubernetes.hooks import (
    register_observer,
    unregister_observer,
)
from krake.utils import now
from krake.data.core import ReasonCode, resource_ref, Reason
from krake.data.kubernetes import ClusterState

logger = logging.getLogger(__name__)


class InvalidStateError(ControllerError):
    """Kubernetes application is in an invalid state"""

    code = ReasonCode.INTERNAL_ERROR


class ModifiedResourceException(Exception):
    """Exception raised if the Kubernetes Controller detects that a resource has been
    modified.

    During the reconciliation loop, the Controller compares the observed fields of the
    last_applied_manifest and the last_observed_manifest. This Exception is used
    internally by the ResourceDelta.calculate method to notify that a modification has
    been detected.
    """


class KubernetesClusterController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Application` and
    :class:`krake.data.kubernetes.Cluster` resources. The controller manages
    Application resources in "SCHEDULED" and "DELETING" state and Clusters in any state.

    Attributes:
        kubernetes_api (KubernetesApi): Krake internal API to connect to the
            "kubernetes" API of Krake.
        cluster_reflector (Reflector): reflector for the Cluster resource of the
        "kubernetes" API of Krake.
        worker_count (int): the amount of worker function that should be run as
            background tasks.
        observer_time_step (float): for the Observers: the number of seconds between two
            observations of the actual resource.
        observers (dict[str, (Observer, Coroutine)]): mapping of all Application or
            Cluster resource' UID to their respective Observer and task responsible for
            the Observer.
            The signature is: ``<uid> --> <observer>, <reference_to_observer's_task>``.

    Args:
        api_endpoint (str): URL to the API
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.
        ssl_context (ssl.SSLContext, optional): if given, this context will be
            used to communicate with the API endpoint.
        debounce (float, optional): value of the debounce for the
            :class:`WorkQueue`.
        worker_count (int, optional): the amount of worker function that should be
            run as background tasks.
        time_step (float, optional): for the Observers: the number of seconds between
            two observations of the actual resource.

    """

    def __init__(
        self,
        api_endpoint,
        worker_count=10,
        loop=None,
        ssl_context=None,
        debounce=0,
        time_step=2,
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.kubernetes_api = None
        self.cluster_reflector = None

        self.worker_count = worker_count

        self.observer_time_step = time_step
        self.observers = {}

    async def list_cluster(self, cluster):
        """Accept the Clusters that need to be managed by the Controller on listing
        them at startup. Starts the observer for the Cluster.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster to accept or not.

        """
        if cluster.status.kube_controller_triggered:
            if cluster.metadata.uid in self.observers:
                # If an observer was started before, stop it
                await unregister_observer(self, cluster)
            # Start an observer only if an actual resource exists on a cluster
            await register_observer(self, cluster)

        await self.simple_on_receive(cluster)

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.kubernetes_api = KubernetesApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        receive_cluster = partial(self.simple_on_receive)
        self.cluster_reflector = Reflector(
            listing=self.kubernetes_api.list_all_clusters,
            watching=self.kubernetes_api.watch_all_clusters,
            on_list=self.list_cluster,
            on_add=receive_cluster,
            on_update=receive_cluster,
            resource_plural="Kubernetes Clusters",
        )
        self.register_task(self.cluster_reflector, name="Cluster_Reflector")

    async def cleanup(self):
        self.cluster_reflector = None
        self.kubernetes_api = None

        # Stop the observers
        for _, task in self.observers.values():
            task.cancel()

        for _, task in self.observers.values():
            with suppress(asyncio.CancelledError):
                await task

        self.observers = {}

    async def on_status_update(self, cluster):
        """Called when an Observer noticed a difference of the status of a resource.
        Request an update of the status on the API.

        Args:
            cluster (krake.data.kubernetes.Cluster): the Cluster whose status
            has been updated.

        Returns:
            krake.data.kubernetes.Cluster: the updated Cluster sent by the API.

        """
        logger.debug(
            "resource status for %s is different, updating status now.",
            resource_ref(cluster),
        )

        cluster.status.kube_controller_triggered = now()
        assert cluster.metadata.modified is not None

        cluster = await self.kubernetes_api.update_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )
        return cluster

    async def handle_resource(self, run_once=False):
        """Infinite loop which fetches and hand over the resources to the right
        coroutine. The specific exceptions and error handling have to be added here.

        This function is meant to be run as background task. Lock the handling of a
        resource with the :attr:`lock` attribute.

        Args:
            run_once (bool, optional): if True, the function only handles one resource,
                then stops. Otherwise, continue to handle each new resource on the
                queue indefinitely.

        """
        while True:
            key, cluster = await self.queue.get()
            try:
                await self.resource_received(cluster)
            except ApiException as error:
                cluster.status.reason = Reason(
                    code=ReasonCode.KUBERNETES_ERROR, message=str(error)
                )
                cluster.status.state = ClusterState.OFFLINE

                await self.kubernetes_api.update_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
            except ControllerError as error:
                cluster.status.reason = Reason(code=error.code, message=error.message)
                cluster.status.state = ClusterState.OFFLINE

                await self.kubernetes_api.update_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
            finally:
                await self.queue.done(key)
            if run_once:
                break  # TODO: should we keep this? Only useful for tests

    async def resource_received(self, cluster, start_observer=True):
        logger.debug("Handle %r", cluster)

        copy = deepcopy(cluster)
        if (
            copy.status.state is ClusterState.CONNECTING
            and copy.metadata.uid not in self.observers
            and copy.metadata.deleted is None
        ):
            await listen.hook(
                HookType.ClusterCreation,
                controller=self,
                resource=copy,
                start=True,
            )
        elif isinstance(copy.metadata.deleted, datetime.datetime):
            await listen.hook(
                HookType.ClusterDeletion,
                controller=self,
                resource=copy,
            )
        elif copy != self.observers[copy.metadata.uid][0].resource and not isinstance(
            copy.metadata.deleted, datetime.datetime
        ):
            await listen.hook(
                HookType.ClusterDeletion,
                controller=self,
                resource=copy,
            )
            await listen.hook(
                HookType.ClusterCreation,
                controller=self,
                resource=copy,
                start=True,
            )
