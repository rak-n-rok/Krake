import asyncio
import datetime
import logging
from contextlib import suppress
from copy import deepcopy
from functools import partial
from datetime import timedelta

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

    @staticmethod
    def accept_accessible(cluster):
        """Check if a resource should be accepted or not by the Controller.

        Args:
            cluster (krake.data.kubernetes.Cluster): the Cluster to check.

        Returns:
            bool: True if the Cluster should be handled, False otherwise.

        """
        # Ignore all failed clusters
        if cluster.status.state == ClusterState.FAILED:
            logger.debug("Reject failed %r", cluster)
            return False

        # Accept accessible (registered, created or deleted) clusters
        if cluster.spec.kubeconfig:
            logger.debug("Accept accessible %r", cluster)
            return True

        logger.debug("Reject %r", cluster)
        return False

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

        await self.simple_on_receive(cluster, self.accept_accessible)

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.kubernetes_api = KubernetesApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        receive_cluster = partial(
            self.simple_on_receive, condition=self.accept_accessible
        )
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

    async def _update_retry_fields(self, cluster):
        logger.info(
            f"{cluster.metadata.name} transition to DEGRADED"
            f"remaining retries: {cluster.status.retries}"
        )
        if cluster.state.backoff_limit > 0:
            cluster.status.retries -= 1

        delay = timedelta(
            seconds=cluster.spec.backoff_delay * cluster.spec.backoff
        )
        cluster.status.scheduled_retry = now() + delay
        logger.debug(
            f"{cluster.metadata.name} scheduled retry to "
            f"{cluster.status.scheduled_retry}"
        )

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
                if cluster.status.retries is None:
                    cluster.status.retries = cluster.spec.backoff_limit
                    logger.debug(
                        f"{cluster.metadata.name} retry counter set to "
                        f"{cluster.status.retries}"
                    )
                if cluster.status.state is not ClusterState.DEGRADED or \
                        now() >= cluster.status.scheduled_retry:
                    await self.resource_received(cluster)
                    cluster.status.retries = cluster.spec.backoff_limit
                    logger.debug(
                        f"{cluster.metadata.name} retry counter reset to "
                        f"{cluster.status.retries}"
                    )
            except ApiException as error:
                cluster.status.reason = Reason(
                    code=ReasonCode.KUBERNETES_ERROR, message=str(error))

                if cluster.status.retries > 0:
                    cluster.status.state = ClusterState.DEGRADED
                    await self._update_retry_fields(cluster)
                elif cluster.spec.backoff_limit == -1:
                    cluster.status.state = ClusterState.DEGRADED
                else:
                    cluster.status.state = ClusterState.OFFLINE
                    logger.info(f"{cluster.metadata.name} transition to OFFLINE")

                await self.kubernetes_api.update_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
            except ControllerError as error:
                cluster.status.reason = Reason(code=error.code, message=error.message)

                if cluster.status.retries > 0:
                    cluster.status.state = ClusterState.DEGRADED
                    await self._update_retry_fields(cluster)
                elif cluster.spec.backoff_limit == -1:
                    cluster.status.state = ClusterState.DEGRADED
                    await self._update_retry_fields(cluster)
                else:
                    cluster.status.state = ClusterState.OFFLINE
                    logger.info(f"{cluster.metadata.name} transition to OFFLINE")

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
        logger.debug(f"{cluster.metadata.name}: handle cluster")

        copy = deepcopy(cluster)

        # Remove a cluster observer, if the cluster is going to be
        # deleted
        if isinstance(copy.metadata.deletion_state.deletion_time, datetime.datetime):
            await listen.hook(
                HookType.ClusterDeletion,
                controller=self,
                resource=copy,
            )
        # Remove a cluster observer, if the cluster creation or
        # reconciliation is in progress. The cluster will be
        # observed again after the creation or reconciliation
        # is finished and the Infrastructure controller transmits
        # cluster state to the `CONNECTING`.
        # Note:
        #  The Kubernetes cluster API could be reachable during
        #  the creation or reconciliation process and could report
        #  cluster healthy state during some short time periods.
        #  This could cause the cluster observer
        #  transmits the cluster state from `CREATING` or
        #  `RECONCILING` to `ONLINE` which could be unsafe
        #  from the application deployment point of view.
        elif copy.status.state in (
            ClusterState.CREATING,
            ClusterState.RECONCILING,
        ):
            await listen.hook(
                HookType.ClusterDeletion,
                controller=self,
                resource=copy,
            )
        # Create a cluster observer, if the cluster is not observed yet
        elif copy.metadata.uid not in self.observers:
            await listen.hook(
                HookType.ClusterCreation,
                controller=self,
                resource=copy,
                start=True,
            )
        # If copy of the received cluster is not equal to
        # the cluster saved in the corresponding cluster observer,
        # then the cluster observer will be deleted and created again
        # to sync the observer again to the saved cluster in Krake
        elif copy != self.observers[copy.metadata.uid][0].resource:
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
