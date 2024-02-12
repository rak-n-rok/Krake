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

from .hooks import (
    register_observer, unregister_observer,
    listen, HookType,
)
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
    """The controller that manages the infrastructure of and monitors clusters that are
    bound to a cloud.

    Queries and watches the Krake Kubernetes API for cluster resources utilizing a
    reflector (:class:`Reflector`) and acts on them, by creating, updating or deleting
    their actual cluster counterparts via an infrastructure provider
    (:class:`InfrastructureProvider`). Receiving and handling of resources is decoupled
    by an internal work queue :class:`WorkQueue`.

    Transitions the cluster resources between the following :class:`ClusterState`s as
    the actions on the actual cluster counterparts progress:
        - PENDING               (initial state)
        - CONNECTING            (cluster state)
        - CREATING              (cluster infra state)
        - RECONCILING           (cluster infra state)
        - DELETING              (cluster infra state)
        - FAILING_RECONCILATION (cluster infra state)
        - FAILED                (cluster infra state)

    Monitors the infrastructure of the actual cluster counterparts via an infrastructure
    provider by attaching an observer to each managed resource. Infrastructure cluster
    observers (:class:`InfrastructureClusterObserver`) trigger the controller to sync
    the cluster resources in the Krake API with the observations they made.

    Args:
        api_endpoint (str): Base URL of the Krake API
        worker_count (int, optional): The amount of workers that should handle resources
            (workers are run as background tasks)
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.
        ssl_context (ssl.SSLContext, optional): if given, this context will be
            used to communicate with the API endpoint.
        debounce (float, optional): value of the debounce for the
            :class:`WorkQueue`.
        poll_interval (float, optional): time in seconds between two attempts to modify
            a cluster (creation, deletion, update, change from FAILED state...).
        time_step (float, optional): for the Observers: the number of seconds between
            two observations of the actual resource.

    Attributes:
        loop: Same as argument. (inherited)
        queue (krake.controller.WorkQueue): The work queue of the controller in which
            received resources are put by the controller's reflector and from which
            the controller's resource handlers take resources for processing.
            (inherited)
        tasks (List[Tuple[Coroutine, str]]): A list in which the controller registers
            its tasks as tuples containing a coroutine and a name. (inherited)
        max_retry (int): Number of times a task should be retried before testing the
            brust time. Set to 3 during init. (inherited)
        burst_time (int): Maximum acceptable average time for a retried task.
            (inherited)
        ssl_context: Same as argument. (inherited)
        api_endpoint: Same as argument. (inherited)
        client: Same as argument. (inherited)
        kubernetes_api (krake.client.kubernetes.KubernetesApi): Krake Kubernetes API
            client. Set in :meth:`prepare`.
        infrastructure_api (krake.client.infrastructure.InfrastructurApi): Krake
            infrastructure API client. Set in :meth:`prepare`.
        worker_count: Same as argument.
        poll_interval: Same as argument.
        observer_time_step: Same as :arg:`time_step`.
        observers (Dict[str, Tuple[krake.controller.infrastructure.hooks.Observer,
            asyncio.Task]]): Mapping that registers an observer to a resource (uid).

    """

    def __init__(
        self,
        api_endpoint,
        worker_count=5,
        loop=None,
        ssl_context=None,
        debounce=0,
        time_step=2,
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

        self.observer_time_step = time_step
        self.observers = {}

    async def receive_cluster(self, cluster):
        """Receive a cluster into the controller

        Enqueues the given cluster into the worker queue of the controller.

        Clusters with the following properties are ignored:
        - no finalizer
        - state is FAILED
        - not scheduled

        This function is to be called by the reflector on any cluster event.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster to receive
        """

        # Always cleanup deleted clusters even if they are in FAILED state.
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

    async def list_cluster(self, cluster):
        """Receive a cluster into the controller and observe it

        Ensures that the given clusters has an observer attached and enqueues it into
        the work queue of the controller.

        This method is to be called by the reflector on listing all existing clusters at
        startup.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster to receive
        """
        if cluster.metadata.uid in self.observers:
            # If an observer was started before, stop it
            await unregister_observer(self, cluster)
        # Register an observer
        await register_observer(self, cluster)

        await self.receive_cluster(cluster)

    async def prepare(self, client):
        """Prepare the controller for operation

        Steps:
            1. Derives API clients for the Krake Kubernetes and Krake Infrastructure API
               from the given API client.
            2. Registers the set amount of handlers (worker tasks) to process resources
               from the controller's worker queue. [1]
            3. Registers a reflector (additional worker task) that feeds resources from
               the Krake API into the controller's worker queue.

        [1] :meth:`self.handle_resource` is used as resource handler

        Args:
            client (krake.client.Client): Krake API client the controller should use
        """
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
            on_list=self.list_cluster,
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
        """Cleanup the controller

        Resets the following properties to None:
        - cluster_reflector
        - kubernetes_api
        - infrastructure_api
        """
        self.cluster_reflector = None
        self.kubernetes_api = None
        self.infrastructure_api = None

    async def handle_resource(self, run_once=False):
        """Infinitly handle resources from the controller's worker queue

        Fetches resources from the controller's worker queue and hands them over to the
        the right coroutine in an infinite loop.

        Args:
            run_once (bool, optional): when set to True, only one loop is performed.
                (Handle one resource, then stop). Should only be used for testing.

        Delegates to:
            :meth:`self.process_cluster`: to process the fetched cluster resource
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
        """Process a cluster

        Performs one of the following actions:
            - Deletes the corresponding actual cluster if the given cluster it is marked
              for deletion. Runs the ClusterDeletion hook beforehand (to remove the
              observation).
            - Starts reconciliation between the spec and the state of the given cluster.
              Runs the ClusterCreation hook afterwards (to ensure correct observation).

        Args:
            cluster (krake.data.kubernetes.Cluster): the Cluster to process.

        Delegates to:
            :meth:`self.delete_cluster`: to delete the given cluster if needed
            :meth:`self.reconcile_cluster`: to reconcile the given cluster otherwise

        Raises:
            InvalidResourceError: uncaught from
                :meth:`self.infrastructure_api.get_cloud` and
                :meth:`self.infrastructure_api.get_infrastructure_provider`
        """
        cluster_copy = copy.deepcopy(cluster)

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
                # Remove a cluster observer, if the cluster is going to be deleted
                await listen.hook(
                    HookType.ClusterDeletion,
                    controller=self,
                    resource=cluster_copy,
                )
                # Remove the cluster
                await self.delete_cluster(cluster, provider)
            else:
                # Reconcile the cluster otherwise
                await self.reconcile_cluster(cluster, provider)

                # Ensure the cluster is correctly observed

                # Create an infrastructure cluster observer, if the cluster is not
                # observed yet.
                if cluster_copy.metadata.uid not in self.observers:
                    await listen.hook(
                        HookType.ClusterCreation,
                        controller=self,
                        resource=cluster_copy,
                        start=True,
                    )
                # If copy of the received cluster is not equal to
                # the cluster saved in the corresponding infrastructure cluster
                # observer, then the cluster observer will be deleted and created again
                # to sync the observer again to the saved cluster in Krake
                elif cluster_copy != \
                        self.observers[cluster_copy.metadata.uid][0].resource:
                    await listen.hook(
                        HookType.ClusterDeletion,
                        controller=self,
                        resource=cluster_copy,
                    )
                    await listen.hook(
                        HookType.ClusterCreation,
                        controller=self,
                        resource=cluster_copy,
                        start=True,
                    )

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
        """Reconcile a cluster via an infrastructure provider

        Starts the rapprochement of the current to the desired state of the given
        cluster depending on its state.
        - If the cluster is not already running, the actual cluster is created.
        - If the cluster was updated, it is reconciled.
        - If the cluster is in FAILING_RECONCILATION state, it is reconfigured.
        - If the cluster is in ONLINE or CONNECTING state, it is skipped.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster whose actual state
                will be modified to match the desired one.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Delegates to:
            :meth:`self.on_create`: to create the actual cluster for the given one
            :meth:`self.on_reconcile`: to reconcile the given cluster
            :meth:`self.on_reconfigure`: to reconfigure the given cluster
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
        """Create the actual cluster to a given cluster resource via an
        infrastructure provider

        This method is to be called when a cluster needs to be created.

        Steps:
            1. Sets the cluster's state to CREATING
            2. Creates the actual cluster via the given infrastructure provider
            3. Captures the cluster id
            4. Markes the cluster as running
            5. Saves the applied cluster TOSCA configuration
            6. Runs the ClusterCreation hook (to start observation)

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs to be
                created.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Delegates to:
            :meth:`provider.create`: to create the actual cluster
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

        # Create a cluster infrastructure observer as soon as it is created
        if cluster.metadata.uid not in self.observers:
            await listen.hook(
                HookType.ClusterCreation,
                controller=self,
                resource=copy.deepcopy(cluster),
                start=True,
            )
        else:
            logger.warning(
                f"Resource {cluster} already had an observer registered before it was"
                " actually created in the real world. Something is off.")

    async def on_reconcile(self, cluster, provider):
        """Reconcile a cluster via an infrastructure provider

        This method is to be called when a cluster needs to be reconciled.

        Steps:
            1. Sets the cluster's state to RECONCILING
            2. Reconciles the actual cluster via the given infrastructure provider
            3. Saves the applied cluster TOSCA configuration

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be reconciled.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Delegates to:
            :meth:`provider.reconcile`: to reconcile the actual cluster
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
        """Reconfigure a cluster via an infrastructure provider

        This method is to be called when a cluster needs to be reconfigured.

        In case of provider failures (e.g. restart) the provider may expect the
        "special" call that ensures the in-sync state of the managed cluster.
        This call is represented by the :func:`reconfigure`. The underlying
        implementation is provider specific and may or may not call a specific
        provider action.

        Steps:
            1. Reconfigures the actual cluster via the given infrastructure provider
            2. Sets the cluster's state ...
               - to FAILING_RECONCILATION if reconfiguration failed
               - to RECONCILING if reconfiguration succeeded

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be reconfigured.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Delegates to:
            :meth:`provider.reconfigure`: to reconfigure the actual cluster
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
        """Wait for the infrastructure of a cluster to be configured

        Continously checks the cluster's infrastructure state by polling the given
        infrastructure provider in the set poll interval until one of the following
        infrastructure states are reached:
        - cluster was deleted (InfrastructureProviderNotFoundError):
          Transitions cluster into PENDING state.
        - state cannot be retrieved (InfrastructureProviderRetrieveError):
          Reconcilation failed, transitions cluster into FAILING_RECONCILATION state and
          raises InfrastructureProviderReconcileError.
        - state is UNCONFIGURED:
          Reconcilation failed, transitions cluster into FAILING_RECONCILATION state and
          raises InfrastructureProviderReconcileError.
        - state is FAILED:
          Reconcilation failed, raises InfrastructureProviderReconcileError.
        - state is CONFIGURED:
          Reconcilation complete, transitions cluster into CONNECTING state.

        This method is to be called after cluster reconcilation is started in order to
        wait for the desired state to actually be reached.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster on which an operation
                is performed that needs to be awaited.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Raises:
            InfrastructureProviderReconcileError: when the reconcilation failed

        Delegates to:
            :meth:`provider.get_state`: to retrieve the cluster's infrastructure state
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
        """Reconcile a connecting cluster resource

        Updates the cluster resource with the kubeconfig retrieved from the given
        infrastructure provider.
        NOTE: This is required in order to connect to the cluster later on.

        This method is to be called while the cluster is in CONNECTING state after
        reconcilation.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs to be
                updated.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the operation on the cluster.

        Raises:
            ClientResponseError: when updating of the cluster in the Krake Kubernetes
                API failed with any HTTP error except 400 (body contained no update).
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
        """Delete a cluster via an infrastructure provider

        Deletes the actual cluster corresponding to the given cluster resource and waits
        for its deletion to finish (polls the infrastructure provider in the set poll
        interval).
        Also removes the controller specific finalizer from the cluster resource.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that is to be deleted.
            provider (Union[InfrastructureProvider, GlobalInfrastructureProvider]):
                infrastructure provider that performs the deletion of the cluster.

        Raises:
            ClientResponseError: when any HTTP error except 404 (not found) occurs while
                checking the Krake Kubernetes API for existance of the given cluster
                resource.
            InfrastructureProviderDeleteError: when the cluster deletion failed.
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
