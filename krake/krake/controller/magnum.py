"""Module for Krake controller responsible for managing Magnum cluster resources and
creating their respective Kubernetes cluster. It connects to the Magnum service of the
Project on which a MagnumCluster has been scheduled.

.. code:: bash

    python -m krake.controller.magnum --help

Configuration is loaded from the ``controllers.scheduler`` section:

.. code:: yaml

    api_endpoint: http://localhost:8080
    worker_count: 5
    debounce: 1.0
    poll_interval: 30

    tls:
      enabled: false
      client_ca: tmp/pki/ca.pem
      client_cert: tmp/pki/system:magnum.pem
      client_key: tmp/pki/system:magnum-key.pem


    log:
      ...

"""
import logging
import asyncio
import pprint
import random
import re
import string
from functools import partial, wraps
from argparse import ArgumentParser
from base64 import b64encode

from OpenSSL import crypto
from aiohttp import ClientError, ClientResponseError

from keystoneauth1.identity.v3 import Password, ApplicationCredential
from keystoneauth1.session import Session
import keystoneauth1.exceptions
from krake.data.config import MagnumConfiguration
from krake.utils import KrakeArgumentFormatter
from magnumclient.v1.client import Client as MagnumV1Client
import magnumclient.exceptions

from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.client import ApiClient, CoreV1Api, Configuration

from krake import (
    search_config,
    setup_logging,
    load_yaml_config,
    ConfigurationOptionMapper,
)
from krake.client.openstack import OpenStackApi
from krake.client.kubernetes import KubernetesApi
from krake.data.core import Reason, ReasonCode, Metadata, resource_ref, ResourceRef
from krake.data.openstack import MagnumClusterState
from krake.data.kubernetes import (
    Cluster as KubernetesCluster,
    ClusterSpec as KubernetesClusterSpec,
    ClusterStatus as KubernetesClusterStatus,
)
from . import Controller, ControllerError, create_ssl_context, run, Reflector


DELETION_FINALIZER = "magnum_cluster_deletion"

logger = logging.getLogger("krake.controller.openstack")


class CreateFailed(ControllerError):
    """Raised in case the creation of a Magnum cluster failed."""

    code = ReasonCode.CREATE_FAILED


class ReconcileFailed(ControllerError):
    """Raised in case the update of a Magnum cluster failed."""

    code = ReasonCode.RECONCILE_FAILED


class DeleteFailed(ControllerError):
    """Raised in case the deletion of a Magnum cluster failed."""

    code = ReasonCode.DELETE_FAILED
    recoverable = False


class InvalidClusterTemplateType(ControllerError):
    """Raised in case the given Magnum template is not a template for a Kubernetes
    cluster.
    """

    code = ReasonCode.INVALID_CLUSTER_TEMPLATE


OPENSTACK_ERRORS = (
    magnumclient.exceptions.ClientException,
    keystoneauth1.exceptions.ClientException,
)


def format_openstack_error(error):
    """Create a more readable error message using OpenStack specific errors.

    Args:
        error (BaseException): the exception whose information is used to create a
            message.

    Returns:
        str: the generated error message.

    """
    if isinstance(error, magnumclient.exceptions.HttpError):
        return "{message} (HTTP {status}): {method} {url}".format(
            status=error.http_status,
            message=error.message,
            method=error.method,
            url=error.url,
        )
    elif isinstance(error, keystoneauth1.exceptions.HttpError):
        return "{message}: {method} {url}".format(
            message=error.message, method=error.method, url=error.url
        )
    return str(error)


class MagnumClusterController(Controller):
    """The Magnum controller receives the MagnumCluster resources from the API and acts
    on it, by creating, updating or deleting their actual cluster counterparts. It uses
    the OpenStack Magnum client for this purpose.

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
        poll_interval (float): time in second before two attempts to modify a Magnum
            cluster (creation, deletion, update, change from FAILED state...).

    """

    def __init__(self, *args, worker_count=5, poll_interval=30, **kwargs):
        super().__init__(*args, **kwargs)
        self.openstack_api = None
        self.kubernetes_api = None
        self.reflector = None
        self.worker_count = worker_count
        self.poll_interval = poll_interval

    async def prepare(self, client):
        self.client = client
        self.openstack_api = OpenStackApi(self.client)
        self.kubernetes_api = KubernetesApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.consume, name=f"worker_{i}")

        async def enqueue(cluster):
            # Always cleanup deleted clusters even if they are in FAILED
            # state.
            if cluster.metadata.deleted:
                if (
                    cluster.metadata.finalizers
                    and cluster.metadata.finalizers[-1] == DELETION_FINALIZER
                ):
                    # Safe guard for infinite looping: a failed but deleted
                    # application is enqueued after the poll interval to slow
                    # down the infinite retry loop.
                    #
                    # FIXME: Should there be a retry limit?
                    if cluster.status.state == MagnumClusterState.FAILED:
                        logger.debug(
                            "Enqueue deleted but failed %r in %ss",
                            cluster,
                            self.poll_interval,
                        )
                        await self.queue.put(
                            cluster.metadata.uid, cluster, delay=self.poll_interval
                        )
                    else:
                        logger.debug("Enqueue deleted %r", cluster)
                        await self.queue.put(cluster.metadata.uid, cluster)
                else:
                    logger.debug("Reject deleted %r without finalizer", cluster)

            # Ignore all other failed clusters
            elif cluster.status.state == MagnumClusterState.FAILED:
                logger.debug("Reject failed %r", cluster)

            # Accept scheduled clusters
            elif cluster.status.project:
                logger.debug("Enqueue scheduled %r", cluster)
                await self.queue.put(cluster.metadata.uid, cluster)
            else:
                logger.debug("Reject %r", cluster)

        self.reflector = Reflector(
            listing=self.openstack_api.list_all_magnum_clusters,
            watching=self.openstack_api.watch_all_magnum_clusters,
            on_list=enqueue,
            on_add=enqueue,
            on_update=enqueue,
            on_delete=enqueue,
            resource_plural="Magnum Clusters",
        )
        self.register_task(self.reflector, name="Reflector")

    async def cleanup(self):
        self.openstack_api = None
        self.kubernetes_api = None
        self.reflector = None

    async def consume(self, run_once=False):
        """Continuously retrieve new elements from the worker queue to be processed.

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
        """Process a Magnum cluster: if the given cluster is marked for deletion, delete
        the actual cluster. Otherwise, start the reconciliation between a Magnum cluster
        spec and its state.

        Handle any :class:`ControllerError` or the supported OpenStack error that are
        raised during the processing.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Magnum cluster to process.

        """
        try:
            logger.debug("Handle %r", cluster)

            if cluster.metadata.deleted:
                await self.delete_magnum_cluster(cluster)
            else:
                await self.reconcile_magnum_cluster(cluster)

        except ControllerError as error:
            logger.error(error)

            reason = Reason(code=error.code, message=error.message)
            cluster.status.reason = reason
            cluster.status.state = MagnumClusterState.FAILED

            await self.openstack_api.update_magnum_cluster_status(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )

        except OPENSTACK_ERRORS as error:
            message = format_openstack_error(error)
            logger.error(message)

            cluster.status.reason = Reason(
                code=ReasonCode.OPENSTACK_ERROR, message=message
            )
            cluster.status.state = MagnumClusterState.FAILED

            await self.openstack_api.update_magnum_cluster_status(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )

    async def reconcile_magnum_cluster(self, cluster):
        """Depending on the state of the given Magnum cluster, start the rapprochement
        of the wanted state of the cluster to the desired one.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the cluster whose actual state
                will be modified to match the desired one.

        """
        magnum = await self.create_magnum_client(cluster)

        # Ensure that deletion finalizer exists
        if DELETION_FINALIZER not in cluster.metadata.finalizers:
            cluster.metadata.finalizers.append(DELETION_FINALIZER)
            await self.openstack_api.update_magnum_cluster(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )

        # Simple finite state machine (FSM). Every state is handled by an
        # action. Action are methods of the controller. An action can return
        # another action ("transition"). If no action is returned, the FSM
        # terminates (terminal state).

        # Initial actions
        actions = {
            MagnumClusterState.PENDING: self.on_pending,
            MagnumClusterState.CREATING: self.on_creating,
            MagnumClusterState.RUNNING: self.on_running,
            MagnumClusterState.RECONCILING: self.on_reconciling,
        }
        action = actions.get(cluster.status.state)
        if not action:
            logger.warning(
                "Unknown reconciliation state %r for %r", cluster.status.state, cluster
            )
            return

        while action:
            action = await action(cluster, magnum)

        logger.info("Reconciliation of %r finished", cluster)

    async def on_pending(self, cluster, magnum):
        """Called when a Magnum cluster with the PENDING state needs reconciliation.

        Initiate the creation of a Magnum cluster using the registered Magnum template,
        but does not ensure that the creation succeeded.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Magnum cluster to actually
                create on its scheduled OpenStack project.
            magnum (MagnumV1Client): the Magnum client to use to connect to the Magnum
                service on the project.

        Returns:
            callable: the next function to be called, as the Magnum cluster changed its
                state. In this case, the Magnum cluster has now the CREATING state, thus
                the function returned is :meth:`on_creating`.

        """
        # Transition into "CREATING" state
        cluster.status.state = MagnumClusterState.CREATING

        # Create forward reference to Kubernetes cluster resource. The
        # resource does not exist. The reconcile loop will detect this and
        # create the resource.
        if not cluster.status.cluster:
            cluster.status.cluster = ResourceRef(
                api=KubernetesCluster.api,
                kind=KubernetesCluster.kind,
                name=f"{cluster.metadata.name}-{randstr()}",
                namespace=cluster.metadata.namespace,
            )

        await self.openstack_api.update_magnum_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

        cluster_template = await read_magnum_cluster_template(
            client=magnum, cluster=cluster
        )
        if cluster_template.coe != "kubernetes":
            raise InvalidClusterTemplateType(
                message=f"Invalid cluster template type {cluster_template.coe!r}"
            )

        # Request OpenStack to create the cluster
        response = await create_magnum_cluster(client=magnum, cluster=cluster)

        # Save ID of Magnum cluster resource
        cluster.status.cluster_id = response.uuid
        await self.openstack_api.update_magnum_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

        return self.on_creating

    async def on_creating(self, cluster, magnum):
        """Called when a Magnum cluster with the CREATING state needs reconciliation.

        Watch over a Magnum cluster currently being created on its scheduled OpenStack
        project, and updates the corresponding Kubernetes cluster created in the API.

        As the Magnum cluster is in a stable state at the end, no further processing
        method is needed to return.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Magnum cluster that needs
                to be processed.
            magnum (MagnumV1Client): the Magnum client to use to connect to the Magnum
                service on the project.

        """
        await self.wait_for_running(cluster, magnum)
        await self.reconcile_kubernetes_resource(cluster, magnum)
        return None

    async def on_running(self, cluster, magnum):
        """Called when a Magnum cluster with the RUNNING state needs reconciliation.

        If the Magnum cluster needs to be resized, initiate the resizing. Otherwise,
        updates the corresponding Kubernetes cluster created in the API.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Magnum cluster that needs
                to be processed.
            magnum (MagnumV1Client): the Magnum client to use to connect to the Magnum
                service on the project.

        Returns:
            callable: the next function to be called, as the Magnum cluster changed its
                state. In the case of resizing, the Magnum cluster has now the
                RECONCILING state, thus the function returned is :meth:`on_creating`.
                Otherwise, as the state is stable at the end, no further processing
                is needed and None is returned.

        """
        if (
            cluster.spec.node_count is not None
            and cluster.status.node_count != cluster.spec.node_count
        ):
            cluster.status.state = MagnumClusterState.RECONCILING
            await self.openstack_api.update_magnum_cluster_status(
                namespace=cluster.metadata.namespace,
                name=cluster.metadata.name,
                body=cluster,
            )
            await resize_magnum_cluster(magnum, cluster)
            return self.on_reconciling

        await self.reconcile_kubernetes_resource(cluster, magnum)
        return None

    async def on_reconciling(self, cluster, magnum):
        """Called when a Magnum cluster with the RECONCILING state needs reconciliation.

        Watch over a Magnum cluster already created on its scheduled OpenStack project,
        and updates the corresponding Kubernetes cluster created in the API.

        As the Magnum cluster is in a stable state at the end, no further processing
        method is needed to return.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Magnum cluster that needs
                to be processed.
            magnum (MagnumV1Client): the Magnum client to use to connect to the Magnum
                service on the project.

        """
        await self.wait_for_running(cluster, magnum)
        await self.reconcile_kubernetes_resource(cluster, magnum)
        return None

    async def delete_magnum_cluster(self, cluster):
        """Initiate the deletion of the actual given Magnum cluster, and wait for its
        deletion. The finalizer specific to the Magnum Controller is also removed from
        the Magnum cluster resource.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Magnum cluster that needs
                to be deleted.

        """
        # FIXME: during its deletion, a MagnumCluster is updated, and thus put into the
        #  queue again on the controller to be deleted. After deletion, the
        #  MagnumCluster is released from the active resources of the queue, and the
        #  updated resource is handled again. However, there are no actual resource
        #  anymore, as it has been deleted. To prevent this, the worker verifies that
        #  the MagnumCluster is not deleted yet before attempting to delete it.
        try:
            await self.openstack_api.read_magnum_cluster(
                namespace=cluster.metadata.namespace, name=cluster.metadata.name
            )
        except ClientResponseError as err:
            if err.status == 404:
                return
            raise

        if (
            cluster.status.project
            and cluster.status.state != MagnumClusterState.PENDING
        ):
            magnum = await self.create_magnum_client(cluster)

            if cluster.status.state != MagnumClusterState.DELETING:
                try:
                    await delete_magnum_cluster(magnum, cluster)
                except magnumclient.exceptions.NotFound:
                    pass

                cluster.status.state = MagnumClusterState.DELETING
                await self.openstack_api.update_magnum_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )

            while True:
                try:
                    response = await read_magnum_cluster(magnum, cluster)
                except magnumclient.exceptions.NotFound:
                    logger.info("The cluster has been deleted: %r", cluster)
                    break

                if response.status == "DELETE_FAILED":
                    raise DeleteFailed(message=response.status_reason)

                await asyncio.sleep(self.poll_interval)

        # Remove finalizer. The owner reference does not need to be removed
        # because the API will remove the resource if there are
        # no finalizers left no matter the owners.
        cluster.metadata.finalizers.remove(DELETION_FINALIZER)
        await self.openstack_api.update_magnum_cluster(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

    async def wait_for_running(self, cluster, magnum):
        """Await for an actual Magnum cluster to be in a stable state, that means, when
        its creation or update is finished.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Magnum cluster on which
                an operation is performed that needs to be awaited.
            magnum (MagnumV1Client): the Magnum client to use to connect to the Magnum
                service on the project.

        Raises:
            ControllerError: if the operation on the cluster failed, a corresponding
                error will be raised (for instance CreateFailed in case the creation of
                the cluster failed).

        """
        # FIXME: This should be handled by an observer. The observer
        #   periodically checks the status of the OpenStack resource and
        #   if the status of the OpenStack resource is different
        #   then the ".status.state", the observer will update the Krake
        #   resource state accordingly.
        while True:
            try:
                response = await read_magnum_cluster(magnum, cluster)
            except magnumclient.exceptions.NotFound:
                # Magnum cluster was deleted from OpenStack deployment. Clear
                # reference to deleted cluster and transition into PENDING
                # state again.
                #
                # Note: The referenced Kubernetes cluster resource is not
                #   deleted here. The controller handling the Kubernetes
                #   cluster periodically checks the status of the cluster
                #   (observer). If the cluster does not exist, it will be
                #   recognized by the observer.
                #
                cluster.status.cluster_id = None
                cluster.status.state = MagnumClusterState.PENDING

                await self.openstack_api.update_magnum_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
                return

            if response.status in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
                logger.info("Cluster %r operation complete", cluster)
                break

            if response.status == "CREATE_FAILED":
                raise CreateFailed(message=response.status_reason)

            if response.status == "UPDATE_FAILED":
                raise ReconcileFailed(message=response.status_reason)

            if response.status == "DELETE_FAILED":
                raise DeleteFailed(message=response.status_reason)

            # TODO: Handle timeout
            logger.debug("Operation on %r still in progress", cluster)
            await asyncio.sleep(self.poll_interval)

        cluster.status.node_count = response.node_count
        cluster.status.api_address = response.api_address
        cluster.status.master_addresses = response.master_addresses
        cluster.status.node_addresses = response.node_addresses

        # Transition into "RUNNING" state
        cluster.status.state = MagnumClusterState.RUNNING
        await self.openstack_api.update_magnum_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

    async def reconcile_kubernetes_resource(self, cluster, magnum):
        """Create or update the Krake resource of the Kubernetes cluster that was
        created from a given Magnum cluster.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the Kubernetes cluster will be
                created using the specifications of this Magnum cluster.
            magnum (MagnumV1Client): the Magnum client to use to connect to the Magnum
                service on the project.

        Raises:
            ClientResponseError: when checking if the Kubernetes cluster resource
                already exists, raise if any HTTP error except 404 is raised.

        """
        if cluster.status.state != MagnumClusterState.RUNNING:
            logger.debug(
                "Magnum cluster %r not running. Skip Kubernetes cluster "
                "resource reconciliation.",
                cluster,
            )
            return

        assert cluster.status.cluster, "Cluster reference not set"
        assert cluster.status.cluster_id, "Magnum cluster UUID not set"
        assert cluster.status.template, "Cluster template UUID not set"

        kube = None

        try:
            # Check if the Kubernetes cluster resource exists
            kube = await self.kubernetes_api.read_cluster(
                namespace=cluster.status.cluster.namespace,
                name=cluster.status.cluster.name,
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
        else:
            # Check if we can access the Kubernetes cluster with this
            # kubeconfig. If not, update kubeconfig with new certificates.
            loader = KubeConfigLoader(kube.spec.kubeconfig)
            config = Configuration()
            await loader.load_and_set(config)

            # If the API address is the same, check if we can access the
            # cluster. Otherwise (if the API addresses are different),
            # recreate certificates.
            if config.host == cluster.status.api_address:
                api_client = ApiClient(config)
                core_v1_api = CoreV1Api(api_client)
                try:
                    await core_v1_api.list_node()
                    return
                except ClientError:
                    pass

        # Generate kubeconfig with new certificates.
        #
        # IMPORTANT: The generated certificate has admin rights on the
        #   cluster.
        kubeconfig = await make_kubeconfig(magnum, cluster)

        if not kube:
            kube = KubernetesCluster(
                metadata=Metadata(
                    namespace=cluster.status.cluster.namespace,
                    name=cluster.status.cluster.name,
                    uid=None,
                    created=None,
                    modified=None,
                    owners=[resource_ref(cluster)],
                    # TODO: There should be support for transitive labels and
                    #   metrics in the scheduler. For now, we simply copy.
                    labels=cluster.metadata.labels.copy(),
                ),
                spec=KubernetesClusterSpec(
                    kubeconfig=kubeconfig, metrics=cluster.spec.metrics.copy()
                ),
                status=KubernetesClusterStatus(),
            )
            await self.kubernetes_api.create_cluster(
                namespace=kube.metadata.namespace, body=kube
            )
        else:
            kube.spec.kubeconfig = kubeconfig
            await self.kubernetes_api.update_cluster(
                namespace=kube.metadata.namespace, name=kube.metadata.name, body=kube
            )

    async def create_magnum_client(self, cluster):
        """Create a client to communicate with the Magnum service API for the given
        Magnum cluster. The specifications defined in the OpenStack project of the
        cluster are used to create the client.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the cluster whose project's
                specifications will be used to connect to the Magnum service.

        Returns:
            MagnumV1Client: the Magnum client to use to connect to the Magnum service on
                the project of the given Magnum cluster.

        """
        # TODO: Handle 404 errors
        project = await self.openstack_api.read_project(
            namespace=cluster.status.project.namespace, name=cluster.status.project.name
        )

        try:
            return await make_magnum_client(project)
        # FIXME: "magnum.v1.client.Client" catches every exception
        #   during endpoint discovery and transforms it into an RuntimeError
        #   ... AAAAAAAAAAAAAAAAH!!!
        except RuntimeError as error:
            # Ugly workaround to get the original exception
            if isinstance(error.__context__, keystoneauth1.exceptions.ClientException):
                raise error.__context__ from None
            raise


def concurrent(fn):
    """Decorator function to turn a synchronous function into an asynchronous coroutine
    that runs in another thread, that can be awaited and thus does not block the main
    asyncio loop. It is particularly useful for synchronous tasks which requires a long
    time to be run concurrently to the main asyncio loop.

    Example:

        .. code:: python

            @concurrent
            def my_function(args_1, arg2=value):
                # long synchronous processing...
                return result

            await my_function(value1, arg2=value2)  # function run in another thread

    Args:
        fn (callable): the function to run in parallel from the main loop.

    Returns:
        callable: decorator around the given function. The returned callable is an
            asyncio coroutine.

    """

    @wraps(fn)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        wrapped = partial(fn, *args, **kwargs)
        return await loop.run_in_executor(None, wrapped)

    return wrapper


def randstr(length=7):
    """Create a random string of lowercase and digit character of the given length.

    Args:
        length (int): specifies how many characters should be present in the returned
            string.

    Returns:
        str: the string randomly generated.

    """
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def generate_magnum_cluster_name(cluster):
    """Create a unique name for a Magnum cluster from its metadata. The name has the
    following structure: "<namespace>-<name>-<random_lowercase_digit_string>". Any
    special character that the Magnum service would see as invalid will be replaced.

    Args:
        cluster (krake.data.openstack.MagnumCluster): the cluster to use to create a
            name.

    Returns:
        str: the name generated.

    """
    raw_name = f"{cluster.metadata.namespace}-{cluster.metadata.name}-{randstr()}"
    # Replace all special characters not accepted by the Magnum service with "_".
    return re.sub("[^A-Za-z0-9_.-]+", "_", raw_name)


@concurrent
def read_magnum_cluster(client, cluster):
    """Read the actual information of the given Magnum cluster resource.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the resource whose actual
            cluster state will be read.

    Returns:
        magnumclient.v1.clusters.Cluster: the current information regarding the given
            Magnum cluster.

    """
    return client.clusters.get(cluster.status.cluster_id)


@concurrent
def create_magnum_cluster(client, cluster):
    """Create an actual Magnum cluster by connecting to the the Magnum service.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the cluster to create.

    Returns:
        magnumclient.v1.clusters.Cluster: the cluster created by the Magnum service.

    """
    extra = {}

    # None would be serialized to a string value of "None" which makes Magnum
    # fail the creation because "None" is an invalid integer value.
    if cluster.spec.master_count is not None:
        extra["master_count"] = cluster.spec.master_count

    if cluster.spec.node_count is not None:
        extra["node_count"] = cluster.spec.node_count

    return client.clusters.create(
        cluster_template_id=cluster.status.template,
        name=generate_magnum_cluster_name(cluster),
        create_timeout=60,  # Timeout for cluster creation in minutes
        **extra,
    )


@concurrent
def resize_magnum_cluster(client, cluster):
    """Update the given Magnum cluster by changing its node count.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the cluster to resize.

    Returns:
        magnumclient.v1.clusters.Cluster: the cluster updated by the Magnum service.

    """
    # TODO: How to handle ".node_count = None"?
    return client.clusters.resize(
        cluster.status.cluster_id, node_count=cluster.spec.node_count
    )


@concurrent
def delete_magnum_cluster(client, cluster):
    """Delete the actual Magnum cluster that corresponds to the given resource.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the cluster to delete.

    Returns:
        magnumclient.v1.clusters.Cluster: the cluster deleted by the Magnum service.

    """
    return client.clusters.delete(cluster.status.cluster_id)


@concurrent
def read_magnum_cluster_template(client, cluster):
    """Get the actual template associated with the one specified in the given Magnum
    cluster resource.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the template given is the one
            specified by this Magnum cluster.

    Returns:
        magnumclient.v1.cluster_templates.ClusterTemplate

    """
    return client.cluster_templates.get(cluster.status.template)


def _encode_to_64(string):
    """Compute the base 64 encoding of a string.

    Args:
        string (str): the string to encode.

    Returns:
        str: the result of the encoding.

    """
    # b64encode accepts only bytes.
    return b64encode(string.encode()).decode()


async def make_kubeconfig(client, cluster):
    """Create a kubeconfig for the Kubernetes cluster associated with the given Magnum
    cluster. For this process, it uses (non exhaustively) the name, address and
    certificates associated with it.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the Magnum cluster for which a
            kubeconfig will be created.

    Returns:
        dict: the kubeconfig created, returned as a dictionary.

    """
    client_key, csr = make_csr()

    ca = await read_ca_certificate(client, cluster)
    client_certificate = await create_client_certificate(client, cluster, csr)

    return {
        "kind": "Config",
        "apiVersion": "v1",
        "clusters": [
            {
                "cluster": {
                    "certificate-authority-data": _encode_to_64(ca),
                    "server": cluster.status.api_address,
                },
                "name": cluster.status.cluster.name,
            }
        ],
        "contexts": [
            {
                "context": {"cluster": cluster.status.cluster.name, "user": "krake"},
                "name": "admin",
            }
        ],
        "current-context": "admin",
        "preferences": {},
        "users": [
            {
                "name": "krake",
                "user": {
                    "client-certificate-data": _encode_to_64(client_certificate),
                    "client-key-data": _encode_to_64(client_key),
                },
            }
        ],
    }


def make_keystone_session(project):
    """Create an OpenStack Keystone session using the authentication information of the
    given project resource.

    Args:
        project (krake.data.openstack.Project): the OpenStack project to use for getting
            the credentials and endpoint.

    Returns:
        Session: the Keystone session created.

    """
    if project.spec.auth.type == "password":
        auth = Password(
            auth_url=project.spec.url,
            user_id=project.spec.auth.password.user.id,
            password=project.spec.auth.password.user.password,
            project_id=project.spec.auth.password.project.id,
        )
    elif project.spec.auth.type == "application_credential":
        id = project.spec.auth.application_credential.id
        secret = project.spec.auth.application_credential.secret
        auth = ApplicationCredential(
            auth_url=project.spec.url,
            application_credential_id=id,
            application_credential_secret=secret,
        )
    else:
        raise NotImplementedError(
            f"Keystone authentication '{project.spec.auth.type}' is not implemented"
        )
    return Session(auth=auth)


@concurrent
def make_magnum_client(project):
    """Create a Magnum client to connect to the given OpenStack project.

    Args:
        project (krake.data.openstack.Project): the project to connect to.

    Returns:
        MagnumV1Client: the client to connect to the Magnum service of the given
            project.

    """
    session = make_keystone_session(project)
    return MagnumV1Client(session=session)


@concurrent
def read_ca_certificate(client, cluster):
    """Get the certificate authority used by the given Magnum cluster.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the Magnum cluster for which the
            certificate authority will be retrieved.

    Returns:
        str: the certificate authority of the given cluster.

    """
    return client.certificates.get(cluster_uuid=cluster.status.cluster_id).pem


@concurrent
def create_client_certificate(client, cluster, csr):
    """Create and get a certificate for the given Magnum cluster.

    Args:
        client (MagnumV1Client): the Magnum client to use to connect to the Magnum
            service.
        cluster (krake.data.openstack.MagnumCluster): the Magnum cluster for which a
            kubeconfig file will be created.
        csr (str): the certificate signing request (CSR) to use on the Magnum service
            for the creation of the certificate.

    Returns:
        str: the generated certificate.

    """
    return client.certificates.create(
        cluster_uuid=cluster.status.cluster_id, csr=csr
    ).pem


def make_csr(key_size=4096):
    """Generates a private key and corresponding certificate and certificate
    signing request.

    Args:
        key_size (int): Length of private key in bits

    Returns:
        (str, str): private key, certificate signing request (CSR)

    """
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, key_size)

    csr = crypto.X509Req()

    # Use "admin" for Common Name and "system:masters" for Organization to get
    # admin access to the cluster.
    #
    # @see https://docs.openstack.org/releasenotes/magnum/queens.html#relnotes-6-1-1-stable-queens-upgrade-notes # noqa
    subject = csr.get_subject()
    subject.organizationName = "system:masters"
    subject.commonName = "admin"

    csr.set_pubkey(key)
    csr.sign(key, "sha256")

    return (
        crypto.dump_privatekey(crypto.FILETYPE_PEM, key).decode(),
        crypto.dump_certificate_request(crypto.FILETYPE_PEM, csr).decode(),
    )


parser = ArgumentParser(
    description="OpenStack Magnum controller", formatter_class=KrakeArgumentFormatter
)
parser.add_argument("-c", "--config", type=str, help="Path to configuration YAML file")

mapper = ConfigurationOptionMapper(MagnumConfiguration)
mapper.add_arguments(parser)


def main(config):
    setup_logging(config.log)
    logger.debug(
        "Krake Magnum Controller configuration settings:\n %s",
        pprint.pformat(config.serialize()),
    )

    tls_config = config.tls
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = MagnumClusterController(
        api_endpoint=config.api_endpoint,
        worker_count=config.worker_count,
        ssl_context=ssl_context,
        debounce=config.debounce,
        poll_interval=config.poll_interval,
    )
    run(controller)


if __name__ == "__main__":
    args = vars(parser.parse_args())

    config = load_yaml_config(args["config"] or search_config("magnum.yaml"))
    kubernetes_config = mapper.merge(config, args)

    main(kubernetes_config)
