import asyncio
import copy
import logging

from aiohttp import ClientResponseError
from deepdiff import DeepDiff

from krake.data.core import Reason
from krake.data.kubernetes import ClusterState
from krake.client import InvalidResourceError as InvalidResourceClientError
from krake.client.kubernetes import KubernetesApi
from krake.client.infrastructure import InfrastructureApi

from .providers import (
    InfrastructureProvider,
    InfrastructureProviderNotFoundError,
    InfrastructureState,
    InfrastructureProviderDeleteError,
    InfrastructureProviderReconcileError,
    InfrastructureProviderRetrieveError,
    InfrastructureProviderReconfigureError,
)

from .. import Controller, Reflector, ControllerError


logger = logging.getLogger(__name__)


DELETION_FINALIZER = "infrastructure_resources_deletion"
DELETION_DELAY = 5  # s


class InfrastructureControllerError(ControllerError):
    """Base exception class for all errors related to infrastructure controller."""

    code = None


class InfrastructureController(Controller):
    """The Infrastructure controller receives the Cluster resources from
    the API and acts on them, by creating, updating or deleting their actual
    cluster counterparts. It uses various infrastructure provider
    clients (IM, Yaook, etc.) for this purpose.

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
        poll_interval (float, optional): time in second before two attempts to modify a
            cluster (creation, deletion, update, change from FAILED state...).

    """

    def __init__(
        self,
        api_endpoint,
        worker_count=5,
        loop=None,
        ssl_context=None,
        debounce=0,
        poll_interval=30,
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.kubernetes_api = None
        self.infrastructure_api = None
        self.cluster_reflector = None

        self.worker_count = worker_count
        self.poll_interval = poll_interval

    async def receive_cluster(self, cluster):
        # Always cleanup deleted clusters even if they are in FAILED
        # state.
        if cluster.metadata.deleted:
            if (
                cluster.metadata.finalizers
                and cluster.metadata.finalizers[-1] == DELETION_FINALIZER
            ):
                # Safeguard for infinite looping: deleted
                # cluster is enqueued after the poll interval to slow
                # down the infinite retry loop.
                logger.debug(
                    "Enqueue deleted but failed %r in %ss",
                    cluster,
                    self.poll_interval,
                )
                await self.queue.put(
                    cluster.metadata.uid, cluster, delay=DELETION_DELAY
                )
            else:
                logger.debug("Reject deleted %r without finalizer", cluster)

        # Ignore all other failed clusters
        elif cluster.status.state == ClusterState.FAILED:
            logger.debug("Reject failed %r", cluster)

        # Accept scheduled clusters
        elif cluster.status.scheduled_to:
            logger.debug("Enqueue scheduled %r", cluster)
            await self.queue.put(cluster.metadata.uid, cluster)
        else:
            logger.debug("Reject %r", cluster)

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.infrastructure_api = InfrastructureApi(self.client)
        self.kubernetes_api = KubernetesApi(self.client,
                                            infrastructure_api=self.infrastructure_api)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        self.cluster_reflector = Reflector(
            listing=self.kubernetes_api.list_all_clusters,
            watching=self.kubernetes_api.watch_all_clusters,
            on_list=self.receive_cluster,
            on_add=self.receive_cluster,
            on_update=self.receive_cluster,
            on_delete=self.receive_cluster,
            resource_plural="Kubernetes Clusters",
        )
        self.register_task(self.cluster_reflector, name="Cluster_Reflector")

    async def on_infrastructure_update(self, updated_cluster):
        """Propagate changed cluster infrastructure data to the Krake API

        Pushes the given cluster into the Krake Kubernetes API to update its
        infrastructure subresource.

        This method is to be called when the infrastructure of a cluster changed.
        Expected callers are observers that noticed a real world infrastructure change.

        Args:
            updated_cluster (krake.data.kubernetes.Cluster): a cluster with updated
                infrastructure data
        """
        logger.debug(
            f"Infrastructure data of cluster {updated_cluster} has to be updated,"
            " updating now.")

        cluster = await self.kubernetes_api.update_cluster_infra_data(
            namespace=updated_cluster.metadata.namespace,
            name=updated_cluster.metadata.name,
            body=updated_cluster,
        )
        return cluster

    async def cleanup(self):
        self.cluster_reflector = None
        self.kubernetes_api = None
        self.infrastructure_api = None

    async def handle_resource(self, run_once=False):
        """Infinite loop which fetches and hand over the resources to the right
        coroutine.

        Args:
            run_once (bool, optional): if True, the function only handles one resource,
                then stops. Otherwise, continue to handle each new resource on the
                queue indefinitely.

        """

        while True:
            key, cluster = await self.queue.get()
            try:
                await self.process_cluster(cluster)
            finally:
                await self.queue.done(key)
            if run_once:
                break  # Only used for tests

    async def process_cluster(self, cluster):
        """Process a Cluster: if the given cluster is marked for deletion, delete
        the actual cluster. Otherwise, start the reconciliation between a Cluster
        spec and its state.

        Args:
            cluster (krake.data.kubernetes.Cluster): the Cluster to process.

        """
        try:
            logger.debug("Handle %r", cluster)
            cloud = await self.kubernetes_api.read_cluster_obj_binding(cluster)
            infrastructure_provider = \
                await self.infrastructure_api.read_cloud_obj_binding(cloud)
            provider = InfrastructureProvider(
                session=self.client.session,
                cloud=cloud,
                infrastructure_provider=infrastructure_provider,
            )

            if cluster.metadata.deleted:
                await self.delete_cluster(cluster, provider)
            else:
                await self.reconcile_cluster(cluster, provider)

        except (ControllerError, InvalidResourceClientError) as error:
            logger.error(error)

            reason = Reason(code=error.code, message=error.message)
            cluster.status.reason = reason
            cluster.status.state = ClusterState.FAILED

            await self.kubernetes_api.update_cluster_status(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )

    async def reconcile_cluster(self, cluster, provider):
        """Depending on the state of the given cluster, start the rapprochement
        of the current state of the cluster to the desired one.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster whose actual state
                will be modified to match the desired one.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        """
        # Recursively look for all the changes between the desired state (which is
        # represented by the `cluster.spec.tosca` field) and the current state
        # (which is stored in the `cluster.status.last_applied_tosca` field)
        if DeepDiff(
            cluster.spec.tosca, cluster.status.last_applied_tosca, ignore_order=True
        ):
            logger.info("Reconciliation of %r started.", cluster)
            # Ensure that deletion finalizer exists
            if DELETION_FINALIZER not in cluster.metadata.finalizers:
                cluster.metadata.finalizers.append(DELETION_FINALIZER)
                await self.kubernetes_api.update_cluster(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )

            if not cluster.status.running_on:
                await self.on_create(cluster, provider)
            else:
                await self.on_reconcile(cluster, provider)

        # Always re-configure when the cluster state is `FAILING_RECONCILIATION`.
        elif cluster.status.state == ClusterState.FAILING_RECONCILIATION:
            logger.info("Reconfigure %r", cluster)
            await self.on_reconfigure(cluster, provider)

        # Stop reconciliation when the cluster state is `ONLINE`
        # or `CONNECTING` state.
        elif cluster.status.state in (ClusterState.ONLINE, ClusterState.CONNECTING):
            logger.info("Reconciliation of %r finished.", cluster)
            return

        # Always wait for connecting when some cluster action is in
        # progress. This ensures that the `CONNECTING` state is set
        # even in case of Infrastructure Controller failures.
        await self.wait_for_connecting(cluster, provider)
        await self.reconcile_cluster_resource(cluster, provider)

    async def on_create(self, cluster, provider):
        """Called when a cluster needs to be created.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be created.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        """
        # Transition into "CREATING" state
        cluster.status.state = ClusterState.CREATING
        await self.kubernetes_api.update_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

        infrastructure_uuid = await provider.create(cluster)

        # Save the infrastructure ID given by the provider as a cluster ID.
        cluster.status.cluster_id = infrastructure_uuid
        cluster.status.running_on = cluster.status.scheduled_to
        cluster.status.last_applied_tosca = copy.deepcopy(cluster.spec.tosca)
        await self.kubernetes_api.update_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

    async def on_reconcile(self, cluster, provider):
        """Called when a cluster needs reconciliation.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be reconciled.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        """
        # Transition into "RECONCILING" state
        cluster.status.state = ClusterState.RECONCILING
        await self.kubernetes_api.update_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

        await provider.reconcile(cluster)

        cluster.status.last_applied_tosca = copy.deepcopy(cluster.spec.tosca)
        await self.kubernetes_api.update_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

    async def on_reconfigure(self, cluster, provider):
        """Called when a cluster needs reconfiguration.

        In case of provider failures (e.g. restart) the provider may expect the
        "special" call that ensures the in-sync state of the managed cluster.
        This call is represented by the :func:`reconfigure`. The underlying
        implementation is provider specific and may or may not call a specific
        provider action.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be reconfigured.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        """
        try:
            await provider.reconfigure(cluster)
        except InfrastructureProviderReconfigureError:
            # Failed to reconfigure cluster.
            # Transition into `FAILING_RECONCILIATION` state.
            # The cluster will be enqueued again in the next controller loop.
            logger.debug("Unable to reconfigure cluster %r", cluster)
            cluster.status.state = ClusterState.FAILING_RECONCILIATION

            await self.kubernetes_api.update_cluster_status(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )
            raise
        else:
            # Transition back into `RECONCILING` state, when the
            # reconfiguration call succeeded.
            cluster.status.state = ClusterState.RECONCILING

            await self.kubernetes_api.update_cluster_status(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )

    async def wait_for_connecting(self, cluster, provider):
        """Waiting for a cluster to be in a `CONNECTING` state.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster on which
                an operation is performed that needs to be awaited.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Raises:
            InfrastructureProviderCreateError: if the creation of the cluster failed.

        """
        while True:
            try:
                state = await provider.get_state(cluster)
            except InfrastructureProviderNotFoundError:
                # Cluster was deleted from cloud. Clear reference to
                # deleted cluster, last_applied_tosca and transition
                # into `PENDING` state again.
                # If the cluster does not exist, it will be
                # created by the controller.
                cluster.status.cluster_id = None
                cluster.status.running_on = None
                cluster.status.last_applied_tosca = {}
                cluster.status.state = ClusterState.PENDING

                await self.kubernetes_api.update_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
                raise

            except InfrastructureProviderRetrieveError:
                # Failed to retrieve cluster state.
                # Transition into `FAILING_RECONCILIATION` state.
                # The cluster will be enqueued again in the next controller loop.
                # FIXME: Krake waits for infrastructure provider is
                #  being ready again infinitely. This should be improved
                #  and replaced by some clever retry and backoff logic.
                cluster.status.state = ClusterState.FAILING_RECONCILIATION

                await self.kubernetes_api.update_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
                raise InfrastructureProviderReconcileError(
                    message=("Reconciliation of the cluster failed: %r", cluster)
                )

            if state == InfrastructureState.UNCONFIGURED:
                # In case of provider failures (e.g. restart) the provider may transit
                # the managed cluster state into `UNCONFIGURED`.
                # In that case, the transition into `FAILING_RECONCILIATION` state
                # ensures that the cluster will be enqueued again in the next
                # controller loop.
                cluster.status.state = ClusterState.FAILING_RECONCILIATION

                await self.kubernetes_api.update_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
                raise InfrastructureProviderReconcileError(
                    message=("Reconciliation of the cluster failed: %r", cluster)
                )

            if state == InfrastructureState.FAILED:
                raise InfrastructureProviderReconcileError(
                    message=("Reconciliation of the cluster failed: %r", cluster)
                )

            if state == InfrastructureState.CONFIGURED:
                logger.debug("Cluster %r reconciliation complete", cluster)
                break

            logger.info("Reconciliation on %r still in progress", cluster)
            await asyncio.sleep(self.poll_interval)

        # Transition into `CONNECTING` state once the cluster in configured.
        # Note:
        #  The cluster is not transit directly into the `ONLINE` state as the
        #  Infrastructure controller does not check overall cluster health.
        #  The Kubernetes cluster controller does this job and transmits
        #  `CONNECTING` state to the `ONLINE` when the cluster is healthy.
        cluster.status.state = ClusterState.CONNECTING
        await self.kubernetes_api.update_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

    async def reconcile_cluster_resource(self, cluster, provider):
        """Update the Cluster resource.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be updated.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Raises:
            ClientResponseError: when updating the Kubernetes cluster resource,
                raise if any HTTP error except 400 is raised.

        """
        if cluster.status.state != ClusterState.CONNECTING:
            logger.debug(
                "Cluster %r not connecting. Skip cluster resource reconciliation.",
                cluster,
            )
            return

        cluster.spec.kubeconfig = await provider.get_kubeconfig(cluster)

        try:
            await self.kubernetes_api.update_cluster(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )
        except ClientResponseError as err:
            if err.status != 400:  # The body contained no update.
                raise

    async def delete_cluster(self, cluster, provider):
        """Initiate the deletion of the actual given cluster, and wait for its
        deletion. The finalizer specific to the Controller is also removed from
        the cluster resource.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be deleted.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the deletion of the cluster.

        Raises:
            InfrastructureProviderDeleteError: If the cluster deletion failed.

        """

        # FIXME: during its deletion, a Cluster is updated, and thus put into the
        #  queue again on the controller to be deleted. After deletion, the
        #  Cluster is released from the active resources of the queue, and the
        #  updated resource is handled again. However, there are no actual resource
        #  anymore, as it has been deleted. To prevent this, the worker verifies that
        #  the Cluster is not deleted yet before attempting to delete it.
        try:
            await self.kubernetes_api.read_cluster(
                namespace=cluster.metadata.namespace, name=cluster.metadata.name
            )
        except ClientResponseError as err:
            if err.status == 404:
                return
            raise

        if cluster.status.cluster_id and cluster.status.state != ClusterState.PENDING:

            if cluster.status.state != ClusterState.DELETING:
                logger.info("Delete %r", cluster)
                try:
                    await provider.delete(cluster)
                except InfrastructureProviderNotFoundError:
                    pass

                cluster.status.state = ClusterState.DELETING
                await self.kubernetes_api.update_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )

            while True:
                try:
                    state = await provider.get_state(cluster)
                except InfrastructureProviderNotFoundError:
                    logger.info("The cluster has been deleted: %r", cluster)
                    break

                if state == InfrastructureState.FAILED:
                    raise InfrastructureProviderDeleteError(
                        message=("Deletion of the cluster failed: %r", cluster)
                    )

                await asyncio.sleep(self.poll_interval)

        # Remove finalizer
        cluster.metadata.finalizers.remove(DELETION_FINALIZER)
        await self.kubernetes_api.update_cluster(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )
