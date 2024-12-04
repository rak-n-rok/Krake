"""Infrastructure controller specific hooks

Provides the hooks specific to infrastructure controllers.
"""

from copy import deepcopy
import logging
from enum import Enum, auto

from krake.client.infrastructure import InfrastructureApi as KrakeInfrastructureApi
from krake.client.kubernetes import KubernetesApi as KrakeKubernetesApi
from krake.controller.hooks import (
    HookDispatcher,
    # these are just customizable base hooks
    register_observer as _register_observer,
    unregister_observer as _unregister_observer,
)
from krake.data.kubernetes import (
    Cluster,
    ClusterInfrastructure,
    ClusterInfrastructureData,
    InfrastructureNode,
    InfrastructureNodeCredential,
)
from krake.controller import Observer

from .providers import InfrastructureProvider

logger = logging.getLogger(__name__)


class HookType(Enum):
    ClusterCreation = auto()
    ClusterDeletion = auto()


listen = HookDispatcher()


class InfrastructureProviderClusterObserver(Observer):
    """Observer specific for Kubernetes clusters managed by the
    :class:`InfrastructureController`

    One observer is created for each Cluster managed by the controller.

    The observer gets the actual status of the cluster using the infrastructure provider
    API (not the Krake infrastructure API) and compares it to the status stored in the
    Krake infrastructure API.

    The observer should be:
        - started at initial cluster resource creation in the controller.
        - deleted on resource deletion.

    Args:
        resource (krake.data.kubernetes.Cluster): the cluster which will be observed.
        on_res_update (coroutine): a coroutine called when a resource's actual state
            differs from the desired state in the Krake API. Its signature is
            ``(resource) -> updated_resource``. ``updated_resource`` is the instance of
            the resource that is up-to-date with the Krake API. The Observer internal
            instance of the resource to observe will be updated. If the API cannot be
            contacted, ``None`` can be returned. In this case the internal instance of
            the Observer will not be updated.
        client (krake.client.Client): The Krake API client the observer should use.
        time_step (int, optional): the interval the Observer should watch the actual
            status of the resources in. (default: 2)

    Attributes:
        resource: Same as argument. (inherited)
        on_res_update: Same as argument. (inherited)
        time_step: Same as argument. (inherited)
        client: Same as argument.
        krake_kubernetes_api (krake.client.kubernetes.KubernetesApi):
            The Krake Kubernetes API client derived from :attr:`client`.
        krake_infrastructure_api (krake.client.infrastructure.InfrastructureApi):
            The Krake infrastructure API client derived from :attr:`client`.
    """

    def __init__(self, resource, on_res_update, client, time_step=2):
        super().__init__(resource, on_res_update, time_step)
        self.client = client
        self.krake_kubernetes_api = KrakeKubernetesApi(self.client)
        self.krake_infrastructure_api = KrakeInfrastructureApi(self.client)

    async def fetch_actual_resource(self):
        """Fetch the current state of the registered cluster's real world infrastructure

        Steps:
            1. Determines the applicable infrastructure provider for the cluster's cloud
            2. Retrieves infrastructure data about the cluster from the determined
               infratructure provider
            3. Formats the retrieved information to be Krake Kubernetes API compliant.

        Returns:
            krake.data.kubernetes.ClusterInfrastructureData: the data object created
                using information from the real world cluster infrastructure.

        Raises:
            InvalidResourceError: uncaught from
                :meth:`self.krake_infrastructure_api.read_cluster_obj_binding` and
                :meth:`self.krake_infrastructure_api.read_cloud_obj_binding`
        """

        cluster = self.resource

        # Get the applicable infrastructure provider that manages the cluster's
        # infrastructure
        # FIXME: The infrastructure provider responsible for a cluster should be cached
        #        to reduce needless recurring requests to the Krake API. This is not
        #        implemented because the Krake API currently does not return an cache
        #        directives (e.g. in the `Cache-Control` header) in its responses (see
        #        RFC 9111, "Storing Responses in Caches")
        cloud = await self.krake_kubernetes_api.read_cluster_obj_binding(cluster)
        infra_provider_spec = (
            await self.krake_infrastructure_api.read_cloud_obj_binding(cloud)
        )
        infra_provider = InfrastructureProvider(
            session=self.client.session,
            cloud=cloud,
            infrastructure_provider=infra_provider_spec,
        )

        # Retrieve the current infrastructure cluster state from the infrastructure
        #  provider API
        infra_provider_cluster = await infra_provider.get(cluster)

        # Derive an Krake API compliant ClusterInfrastructureData object from the
        # received InfrastructureProviderCluster.
        # NOTE: This can be viewed as the adapter between infrastructure provider API
        #       and Krake API.
        cluster_infra_data = ClusterInfrastructureData(
            nodes=[
                InfrastructureNode(
                    ip_addresses=[str(ip) for ip in vm.ip_addresses],
                    credentials=[
                        InfrastructureNodeCredential(
                            # FIXME: All InfrastructureProviderVmCredentials are treated
                            #        as login credentials
                            type="login",
                            username=str(cred.username),
                            password=(
                                str(cred.password)
                                if cred.password is not None
                                else None
                            ),
                            private_key=(
                                str(cred.private_key)
                                if cred.private_key is not None
                                else None
                            ),
                        )
                        for cred in vm.credentials
                    ],
                )
                for vm in infra_provider_cluster.vms
            ],
        )

        return cluster_infra_data

    async def check_observation(self, observation):
        """Check and apply an observation if it has not already been made

        Compares the given observation against the registered cluster resource and
        reports the outcome. In case there is a difference applies the observation to a
        copy of the registered resource and returns that additionally.

        Args:
            observation (Union[krake.data.kubernetes.ClusterInfrastructureData]): an
                observed cluster infrastructure state.

        Returns:
            Tuple[True, krake.data.kubernetes.Cluster]: (when the observation is new)
                the fact that a change was observed and an updated copy of registered
                cluster resource.
            Tuple[False, None]: (when the observation is not new) only the fact that no
                change was observed.

        Raises:
            ValueError: when the given observation is not a cluster infrastructure
                state.
        """

        changed, to_update = False, None

        # Discriminate by observation type
        # NOTE: Currently we only need to support :class:`ClusterInfrastructureData`.
        if isinstance(observation, ClusterInfrastructureData):

            def _check_and_update():
                nonlocal changed, to_update
                if self.resource.infrastructure.data != observation:
                    changed = True
                    to_update = deepcopy(self.resource)
                    to_update.infrastructure.data = observation

            try:
                _check_and_update()
            except AttributeError as e:
                if e.name == "data":
                    # Create cluster infrastructure subresource if not present
                    # (probably because this is the first observation ever)
                    self.resource.infrastructure = ClusterInfrastructure()
                    changed, to_update = True, deepcopy(self.resource)

                    # ... and retry
                    _check_and_update()
                else:
                    raise e  # should never happen

        else:
            raise ValueError(
                f"Received unsupported observation of type '{type(observation)}'"
                f" for the observed resource {self.resource}"
            )

        return (True, to_update) if changed else (False, None)


@listen.on(HookType.ClusterCreation)
async def register_observer(controller, *args, **kwargs):
    """Create, start and register an observer for a cluster

    Creates a suitable observer for the given cluster resource and registers it in the
    infrastructure controller. Unless `start=False` is given starts the created observer
    as a background task.

    Args:
        controller (InfrastructureController]): the infrastructure controller in which
            the observer shall be registered.
        resource (krake.data.kubernetes.Cluster): the cluster to observe.
        start (bool, optional): whether the observer shall be started or not.

    Registered under the following hooks:
        - ClusterCreation

    Partial of :func:`krake.controller.hooks.register_observer`
    """

    def get_observer(resource):
        """Get a new observer for a resource

        Creates an returns a suitable observer for the given resource.

        Args:
            resource (krake.data.kubernetes.Cluster): the cluster to create an observer
                for.

        Returns:
            krake.krake.controller.infrastructure.InfrastructureProviderClusterObserver:
                an infrastructure provider cluster observer instance when the given
                resource is a cluster.

        Raises:
            ValueError: when the given resource kind is not supported.
        """
        if resource.kind == Cluster.kind:
            return InfrastructureProviderClusterObserver(
                resource=resource,
                on_res_update=controller.on_infrastructure_update,
                client=controller.client,
                time_step=controller.observer_time_step,
            )
        else:
            raise ValueError(
                f"Wrong resource kind '{resource.kind}' of resource"
                f" {resource}. Must be '{Cluster.kind}'."
            )

    # Call base hook customized with the `get_observer` argument
    await _register_observer(controller, *args, get_observer=get_observer, **kwargs)


@listen.on(HookType.ClusterDeletion)
async def unregister_observer(*args, **kwargs):
    """Unregister and stop an observer for a cluster

    Removes the observer for the given cluster from the infrastructure controller. Does
    nothing, if no such observer is registered.

    Args:
        controller (InfrastructureController): the infrastructure controller from which
            the observer shall be removed.
        resource (krake.data.kubernetes.Cluster): the cluster whose observer shall be
            stopped.

    Registered under the following hooks:
        - ClusterDeletion

    Partial of :func:`krake.controller.hooks.unregister_observer`
    """

    await _unregister_observer(*args, **kwargs)
