"""Module comprises Krake infrastructure providers abstraction.
"""
import enum
from itertools import groupby
from typing import NamedTuple
import re
from uuid import UUID

import yaml
from aiohttp import ClientResponseError, ClientError
from yarl import URL

from krake.controller import ControllerError
from krake.data.core import ReasonCode
from krake.data.infrastructure import (
    InfrastructureProviderCluster,
    InfrastructureProviderVm,
    InfrastructureProviderVmCredential
)


class InfrastructureProviderError(ControllerError):
    """Base exception class for all errors related to infrastructure providers."""

    code = None


class InfrastructureProviderCreateError(InfrastructureProviderError):
    """Raised in case the creation of an infrastructure failed."""

    code = ReasonCode.CREATE_FAILED


class InfrastructureProviderReconcileError(InfrastructureProviderError):
    """Raised in case the update of an infrastructure failed."""

    code = ReasonCode.RECONCILE_FAILED


class InfrastructureProviderReconfigureError(InfrastructureProviderError):
    """Raised in case the reconfiguration of an infrastructure failed."""

    code = ReasonCode.RECONFIGURE_FAILED


class InfrastructureProviderDeleteError(InfrastructureProviderError):
    """Raised in case the deletion of an infrastructure failed."""

    code = ReasonCode.DELETE_FAILED


class InfrastructureProviderRetrieveError(InfrastructureProviderError):
    """Raised in case the retrieval of an infrastructure failed."""

    code = ReasonCode.RETRIEVE_FAILED


class InfrastructureProviderNotFoundError(InfrastructureProviderError):
    """Raised in case an infrastructure was not found."""

    code = ReasonCode.NOT_FOUND


class InfrastructureState(enum.Enum):
    """Generic infrastructure state.

    This generic state should be mapped to
    the state retrieved from the specific
    infrastructure provider implementation
    (e.g. IM).
    """

    PENDING = enum.auto()
    CREATING = enum.auto()
    CONFIGURED = enum.auto()
    UNCONFIGURED = enum.auto()
    DELETING = enum.auto()
    FAILED = enum.auto()


class IMInfrastructureStateMapping(enum.Enum):
    """IM infrastructure states mapping to generic.

    This class maps :class:`InfrastructureState` generic infrastructure
    states to states retrieved from the IM infrastructure provider.

    Read the IM docs:
    https://imdocs.readthedocs.io/en/latest/xmlrpc.html#im-valid-states
    """

    PENDING = InfrastructureState.PENDING
    # IM marked infrastructure as running when VMs have been created,
    # hence the infrastructure is not fully configured (ready) yet.
    RUNNING = InfrastructureState.CREATING
    CONFIGURED = InfrastructureState.CONFIGURED
    DELETING = InfrastructureState.DELETING
    # IM marked infrastructure as unconfigured when VMs have not been
    # configured properly because of some issues.
    UNCONFIGURED = InfrastructureState.UNCONFIGURED
    # All below IM infrastructure states are not expected, hence marked
    # as failed.
    UNKNOWN = InfrastructureState.FAILED
    STOPPED = InfrastructureState.FAILED
    OFF = InfrastructureState.FAILED
    FAILED = InfrastructureState.FAILED


class InfrastructureProvider(object):
    """Base infrastructure provider client used as an abstract interface
    for selection of an appropriate infrastructure provider client
    based on a cloud definition.

    Subclassed infrastructure providers are stored in class
    variable :attr:`registry`. Selection is evaluated in :meth:`__new__`
    based on the :args:`infrastructure_provider`.

    Attributes:
        registry (Dict[str, type]): Subclass registry mapping the name of provider
            types to their respective provider implementation.
        type (str): Name of the provider type that this subclass implements. The
            name should have a matching provider type in
            :class:`krake.data.infrastructure.InfrastructureProviderSpec`.
    """

    registry = {}
    type = None

    def __init_subclass__(cls, **kwargs):
        """Collect the :class:`Provider` subclasses into :attr:`registry`.

        Args:
            **kwargs: Keyword arguments

        """
        super().__init_subclass__(**kwargs)
        if cls.type in cls.registry:
            raise ValueError(
                f"Infrastructure provider: {cls.type} is already registered"
            )

        cls.registry[cls.type] = cls

    def __new__(mcls, *args, **kwargs):
        """Get the Provider class depending on the given metrics provider type.

        Returns:
              Provider: the instantiated Provider client to use.

        """
        provider_type = kwargs["infrastructure_provider"].spec.type
        return object.__new__(mcls.registry[provider_type])

    async def create(self, cluster):
        """Create a cluster using an infrastructure provider."""
        raise NotImplementedError()

    async def reconcile(self, cluster):
        """Update a cluster using an infrastructure provider."""
        raise NotImplementedError()

    async def delete(self, cluster):
        """Delete a cluster using an infrastructure provider."""
        raise NotImplementedError()

    async def get_state(self, cluster):
        """Retrieve a cluster's state using an infrastructure provider."""
        raise NotImplementedError()

    async def get_kubeconfig(self, cluster):
        """Retrieve a cluster's kubeconfig using an infrastructure provider."""
        raise NotImplementedError()

    async def get(self, cluster):
        """Retrieve information about a cluster using the infrastructure provider.

        Returns:
            InfrastructureProviderCluster: data object that represents the corresponding
               cluster in the infrastructureprovider

        Raises:
            NotImplementedError: when the method is not supported by the infrastructure
                provider or was not implemented yet.
        """
        raise NotImplementedError()

    async def get_vm(self, cluster, ident):
        """Retrieve information about a cluster VM using an infrastructure provider.

        Args:
            cluster (krake.data.kubernetes.Cluster): a cluster managed by the
                infrastructure manager.
            ident (Union[UUID|int|str]): a UUID, index, number, name or similiar that
                identifies the VM in the infrastructure provider.

        Returns:
            InfrastructureProviderVm: A data object that represents an infrastructure
                manager VM with the retrieved information.

        Raises:
            NotImplementedError: when the method is not supported by the infrastructure
                provider or was not implemented yet.
        """
        raise NotImplementedError()


class IMAuthPassword(NamedTuple):
    """Container that contains data for IM service password authentication."""

    id: str
    username: str
    password: str
    type: str = "InfrastructureManager"

    def serialize(self):
        """Serialize fields to the IM format.

        IM auth format:
          Pairs of key and value should be separated
          by semicolon. The key and value should be
          separated by ” = “, that is an equals sign
          preceded and followed by one white space at least.
          https://imdocs.readthedocs.io/en/latest/client.html#auth-file

        Returns:
            str: Formatted fields.
        """
        return ";".join([f"{field} = {getattr(self, field)}" for field in self._fields])


class IMAuthToken(NamedTuple):
    """Container that contains data for IM service password authentication."""

    id: str
    token: str
    type: str = "InfrastructureManager"

    def serialize(self):
        """Serialize fields to the IM format.

        IM auth format:
          Pairs of key and value should be separated
          by semicolon. The key and value should be
          separated by ” = “, that is an equals sign
          preceded and followed by one white space at least.
          https://imdocs.readthedocs.io/en/latest/client.html#auth-file

        Returns:
            str: Formatted fields.
        """
        return ";".join([f"{field} = {getattr(self, field)}" for field in self._fields])


class CloudOpenStackAuthPassword(NamedTuple):
    """Container that contains data for OpenStack password authentication."""

    id: str
    host: str
    auth_version: str
    username: str
    password: str
    tenant: str
    type: str = "OpenStack"

    def serialize(self):
        """Serialize fields to the IM format.

        IM auth format:
          Pairs of key and value should be separated
          by semicolon. The key and value should be
          separated by ” = “, that is an equals sign
          preceded and followed by one white space at least.
          https://imdocs.readthedocs.io/en/latest/client.html#auth-file

        Note:
          IM expects that OpenStack identity API version is
          for password authentication type defined as follows:
          - 2.0_password
          - 3.x_password
          Hence the version defined in :attr:`auth_version`
          should be suffixed by `.x_password` string.

        Returns:
            str: Formatted fields.
        """
        to_serialize = []
        for field in self._fields:
            if field == "auth_version":
                to_serialize.append(f"{field} = {getattr(self, field)}.x_password")
            else:
                to_serialize.append(f"{field} = {getattr(self, field)}")

        return ";".join(to_serialize)


class InfrastructureManager(InfrastructureProvider):
    """IM infrastructure provider client.

    Implements client calls (create, retrieve, delete, update, get) of the
    IM infrastructure provider.

    Read the IM docs:
    https://imdocs.readthedocs.io
    Checkout the IM source code:
    https://github.com/grycap/im
    """

    type = "im"

    def __init__(self, session, cloud, infrastructure_provider):
        self.session = session
        self.cloud = cloud
        self.infrastructure_provider = infrastructure_provider

        self._auth_header = self._get_auth_header(infrastructure_provider, cloud)

    @staticmethod
    def _get_cloud_auth(cloud):
        """Get the cloud authentication data.

        Note:
          Currently, only OpenStack cloud and OpenStack password authentication
          is supported by this method. Could be extended as the IM supports more.

        Args:
            cloud (Union[Cloud, GlobalCloud]): Cloud from which the authentication data
                should be retrieved.

        Raises:
            NotImplementedError: If the unsupported cloud or cloud authentication method
                is used.

        Returns:
            CloudOpenStackAuthPassword: OpenStack password authentication
                data container.

        """
        if cloud.spec.type != "openstack":
            raise NotImplementedError(f"Unsupported IM cloud type: {cloud.spec.type}.")

        if cloud.spec.openstack.auth.type != "password":
            raise NotImplementedError(
                "Unsupported OpenStack authentication type:"
                f" {cloud.spec.openstack.auth.type}."
            )

        return CloudOpenStackAuthPassword(
            id=cloud.metadata.name,
            host=cloud.spec.openstack.url,
            auth_version=cloud.spec.openstack.auth.password.version,
            username=cloud.spec.openstack.auth.password.user.username,
            password=cloud.spec.openstack.auth.password.user.password,
            tenant=cloud.spec.openstack.auth.password.project.name,
        )

    @staticmethod
    def _get_im_auth(infrastructure_provider):
        """Get the IM infrastructure provider authentication data.

        Args:
            infrastructure_provider (
                Union[InfrastructureProvider, GlobalInfrastructureProvider]
            ): IM infrastructure provider from which the authentication data should
                be retrieved.

        Raises:
            NotImplementedError: If any from supported IM authentication method is used.

        Returns:
            Union[IMAuthToken, IMAuthPassword]: IM infrastructure provider
                authentication data container.

        """
        if infrastructure_provider.spec.im.token:
            return IMAuthToken(
                id=infrastructure_provider.metadata.name,
                token=infrastructure_provider.spec.im.token,
            )

        if (
            infrastructure_provider.spec.im.username
            and infrastructure_provider.spec.im.password
        ):
            return IMAuthPassword(
                id=infrastructure_provider.metadata.name,
                username=infrastructure_provider.spec.im.username,
                password=infrastructure_provider.spec.im.password,
            )

        raise NotImplementedError(
            "At least one authentication should be defined in"
            " the IM infrastructure provider spec."
        )

    def _get_auth_header(self, infrastructure_provider, cloud):
        """Get the IM infrastructure provider authorization header.

        IM auth format details:
          https://imdocs.readthedocs.io/en/latest/client.html#auth-file

        Args:
            infrastructure_provider (
                Union[InfrastructureProvider, GlobalInfrastructureProvider]
            ): IM infrastructure provider from which the authentication data should
                be retrieved.
            cloud (Union[Cloud, GlobalCloud]): Cloud from which the authentication data
                should be retrieved.

        Returns:
            str: Authorization header.

        """
        return "\\n".join(
            [
                self._get_im_auth(infrastructure_provider).serialize(),
                self._get_cloud_auth(cloud).serialize(),
            ]
        )

    async def _get_infrastructure_state(self, infrastructure_id):
        """Retrieve infrastructure state using the IM infrastructure provider.

        IM returns infrastructure state as a JSON object with two sub-elements:
        - `state`: A string with the aggregated state of the infrastructure.
           This field does not consider partially unconfigured infrastructure
           due to some IM failure during the infrastructure update, see example
        - `vm_states`: A dict indexed with the VM ID and the VM state as value.
           This field should be considered in the final infrastructure state, see
           example that shows partially unconfigured infrastructure due to some
           IM failure during the infrastructure update

        Read the IM docs:
        https://imdocs.readthedocs.io/en/latest/xmlrpc.html#im-valid-states

        Example:

            .. code:: bash
                $ curl http://im.example/infrastructures/<infrastructure-id>/state
                {
                  "state": {
                    "state": "configured",
                    "vm_states": {
                      "0": "configured",
                      "1": "configured",
                    }
                  }
                }
                $ # Update the infrastructure. IM fall into issues and the VM state
                $ # could be unconfigured, e.g.:
                $ curl http://im.example/infrastructures/<infrastructure-id>/state
                {
                   "state": {
                     "state": "running",
                     "vm_states": {
                       "0": "running",
                       "1": "unconfigured",
                       "2": "unconfigured"
                      }
                  }
                }
        Args:
            infrastructure_id (str): the infrastructure that state needs
                to be retrieved.

        Raises:
            InfrastructureProviderRetrieveError: If the infrastructure
                state retrieval failed.

        Returns:
            dict: Infrastructure state.

        """
        url = (
            URL(self.infrastructure_provider.spec.im.url)
            / "infrastructures"
            / infrastructure_id
            / "state"
        )
        headers = {
            "Authorization": self._auth_header,
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()
        except ClientError as err:
            if isinstance(err, ClientResponseError) and err.status == 404:
                raise InfrastructureProviderNotFoundError(
                    message=f"Infrastructure {infrastructure_id} not found."
                )

            raise InfrastructureProviderRetrieveError(
                message=(
                    f"Failed to retrieve infrastructure {infrastructure_id} state with"
                    f" IM provider {self.infrastructure_provider.metadata.name},"
                    f" error: {err!r}"
                )
            )

    async def create(self, cluster):
        """Create a cluster using the IM infrastructure provider.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be created.

        Raises:
            InfrastructureProviderCreateError: If the cluster creation failed.

        Returns:
            str: Infrastructure UUID.

        """
        url = (
            URL(self.infrastructure_provider.spec.im.url) / "infrastructures"
        ).with_query({"async": "true"})

        headers = {
            "Authorization": self._auth_header,
            "Content-Type": "text/yaml",
        }
        try:
            async with self.session.post(
                url, data=yaml.safe_dump(cluster.spec.tosca), headers=headers
            ) as resp:
                resp.raise_for_status()
                response = await resp.text()
        except ClientError as err:
            raise InfrastructureProviderCreateError(
                message=(
                    f"Failed to create cluster {cluster.metadata.name} with"
                    f" IM provider {self.infrastructure_provider.metadata.name},"
                    f" error: {err!r}"
                )
            )

        _, infrastructure_uuid = URL(response).path.split("infrastructures/")
        return infrastructure_uuid

    async def reconcile(self, cluster):
        """Update a cluster using the IM infrastructure provider.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be reconciled.

        Raises:
            InfrastructureProviderCreateError: If the cluster reconciliation failed.

        """
        url = (
            URL(self.infrastructure_provider.spec.im.url)
            / "infrastructures"
            / cluster.status.cluster_id
        ).with_query({"async": "true"})

        headers = {
            "Authorization": self._auth_header,
            "Content-Type": "text/yaml",
        }
        try:
            async with self.session.post(
                url, data=yaml.safe_dump(cluster.spec.tosca), headers=headers
            ) as resp:
                resp.raise_for_status()
        except ClientError as err:
            raise InfrastructureProviderReconcileError(
                message=(
                    f"Failed to reconcile cluster {cluster.metadata.name} with"
                    f" IM provider {self.infrastructure_provider.metadata.name},"
                    f" error: {err!r}"
                )
            )

    async def reconfigure(self, cluster):
        """Reconfigure a cluster using the IM infrastructure provider in case
        of IM failures.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be reconfigured.

        Raises:
            InfrastructureProviderCreateError: If the cluster reconfiguration failed.

        """
        url = (
            URL(self.infrastructure_provider.spec.im.url)
            / "infrastructures"
            / cluster.status.cluster_id
            / "reconfigure"
        )

        headers = {
            "Authorization": self._auth_header,
        }
        try:
            async with self.session.put(url, headers=headers) as resp:
                resp.raise_for_status()
        except ClientError as err:
            raise InfrastructureProviderReconfigureError(
                message=(
                    f"Failed to reconfigure cluster {cluster.metadata.name} with"
                    f" IM provider {self.infrastructure_provider.metadata.name},"
                    f" error: {err!r}"
                )
            )

    async def delete(self, cluster):
        """Delete a cluster using the IM infrastructure provider.

        Args:
            cluster (krake.data.kubernetes.Cluster): the cluster that needs
                to be deleted.

        Raises:
            InfrastructureProviderDeleteError: If the cluster deletion failed.

        """
        url = (
            URL(self.infrastructure_provider.spec.im.url)
            / "infrastructures"
            / cluster.status.cluster_id
        ).with_query({"async": "true"})

        headers = {
            "Authorization": self._auth_header,
        }
        try:
            async with self.session.delete(url, headers=headers) as resp:
                resp.raise_for_status()
        except ClientError as err:
            if isinstance(err, ClientResponseError) and err.status == 404:
                raise InfrastructureProviderNotFoundError(
                    message=f"Infrastructure {cluster.status.cluster_id} not found."
                )

            raise InfrastructureProviderDeleteError(
                message=(
                    f"Failed to delete cluster {cluster.metadata.name} with"
                    f" IM provider {self.infrastructure_provider.metadata.name},"
                    f" error: {err!r}"
                )
            )

    async def get_state(self, cluster):
        """Retrieve a cluster state using the IM infrastructure provider.

        The cluster state retrieved from the IM infrastructure provider
        is mapped to the generic infrastructure provider states defined
        in :class:`InfrastructureState`.
        Partial VM states should be considered as overall infrastructure
        states, see example in :func:`_get_infrastructure_state` docs.

        Possible IM infrastructure provider states are defined
        in :class:`IMInfrastructureStateMapping`.

        Raises:
            InfrastructureProviderRetrieveError: If the cluster state retrieval failed.

        Returns:
            InfrastructureState: Generic infrastructure state.

        """
        if not cluster.status.cluster_id:
            raise InfrastructureProviderRetrieveError(message="Missing cluster id.")

        state = await self._get_infrastructure_state(cluster.status.cluster_id)

        state_overall = state.get("state", {}).get("state")
        state_vms = state.get("state", {}).get("vm_states")
        if not state_overall:
            raise InfrastructureProviderRetrieveError(
                message=f"Empty cluster {cluster.status.cluster_id} state."
            )

        # Consider partially unconfigured infrastructure
        if state_vms and "unconfigured" in state_vms.values():
            state_overall = "unconfigured"

        try:
            return IMInfrastructureStateMapping[state_overall.upper()].value
        except KeyError:
            raise InfrastructureProviderRetrieveError(
                message=f"Unknown cluster {cluster.status.cluster_id} "
                f"state {state_overall}."
            )

    async def get_kubeconfig(self, cluster):
        """Retrieve a cluster admin kubeconfig using the IM infrastructure provider.

        The cluster admin  kubeconfig is retrieved from the infrastructure outputs.
        Outputs should be correctly defined in the TOSCA template to allow
        kubeconfig retrieval. The key `kubeconfig` is expected and should contain
        kubeconfig content as YAML.

        Example:
            .. code:: yaml

               topology_template:
                 outputs:
                   kubeconfig:
                     value: { get_attribute: [... ] }

        Raises:
            InfrastructureProviderRetrieveError: If the cluster kubeconfig
                retrieval failed.

        Returns:
            dict: Retrieved cluster admin kubeconfig.

        """
        if not cluster.status.cluster_id:
            raise InfrastructureProviderRetrieveError(message="Missing cluster id.")

        url = (
            URL(self.infrastructure_provider.spec.im.url)
            / "infrastructures"
            / cluster.status.cluster_id
            / "outputs"
        )
        headers = {
            "Authorization": self._auth_header,
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                response = await resp.json()
        except ClientError as err:
            if isinstance(err, ClientResponseError) and err.status == 404:
                raise InfrastructureProviderNotFoundError(
                    message=f"Infrastructure {cluster.status.cluster_id} not found."
                )

            raise InfrastructureProviderRetrieveError(
                message=(
                    f"Failed to retrieve cluster {cluster.metadata.name}"
                    f" kubeconfig with IM provider"
                    f" {self.infrastructure_provider.metadata.name},"
                    f" error: {err!r}"
                )
            )

        kubeconfig = response.get("outputs", {}).get("kubeconfig")
        if not kubeconfig:
            raise InfrastructureProviderRetrieveError(
                message=f"Empty cluster {cluster.status.cluster_id} kubeconfig."
            )

        try:
            return yaml.safe_load(kubeconfig)
        except yaml.YAMLError:
            raise InfrastructureProviderRetrieveError(
                message=(
                    f"Failed to load cluster {cluster.metadata.name}"
                    f" kubeconfig {kubeconfig}."
                )
            )

    async def _enumerate_cluster_nodes_by_url(self, infrastructure_id):
        """Return a list of urls that covers all VMs of the referenced infrastructure
        manager infrastructure.

        Args:
            infrastructure_id (UUID): uuid of the infrastructure

        Returns:
            List[str]: List of URLs that reference VMs in the infrastructure provider
                API.

        Raises:
            InfrastructureProviderRetrieveError: If the given infrastructure does not
                exist or cannot be retrieved.
        """
        url = (
            URL(self.infrastructure_provider.spec.im.url)
            / "infrastructures/"
            / str(infrastructure_id)
        )
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json"
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                json_response = await resp.json()
        except ClientError as err:
            if isinstance(err, ClientResponseError) and err.status == 404:
                raise InfrastructureProviderNotFoundError(
                    message=f"Infrastructure {infrastructure_id} not found."
                )

            raise InfrastructureProviderRetrieveError(
                message=(
                    f"Failed to retrieve infrastructure {infrastructure_id} with"
                    f" IM provider {self.infrastructure_provider.metadata.name},"
                    f" error: {err!r}"
                )
            )
        return [item['uri'] for item in json_response['uri-list']]

    async def _get_vm_by_url(self, url):
        """Retrieve VM information by url from the infrastructure manager

        Args:
            url (str): URL of a VM in the infrastructure manager API.

        Returns:
            InfrastructureProviderVm: A data object that represents an infrastructure
                manager VM with the retrieved information.

        Raises:
            InfrastructureProviderRetrieveError: If the given infrastructure does not
                exist or cannot be retrieved.
        """
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json"
        }
        try:
            async with self.session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                response = await resp.json()
        except ClientError as err:
            if isinstance(err, ClientResponseError) and err.status == 404:
                raise InfrastructureProviderNotFoundError(
                    message=f"Infrastructure not found at url '{url}'."
                )

            raise InfrastructureProviderRetrieveError(
                message=(
                    f"Failed to retrieve VM information from IM provider url '{url}'"
                    f" {self.infrastructure_provider.metadata.name}, error: {err!r}"
                )
            )

        # Get VM by filtering the RADL JSON response for infrastructure manager systems
        # NOTE: We expect only one system in the response
        radl_system = [x for x in response['radl'] if x['class'] == "system"][0]
        if not radl_system:
            raise InfrastructureProviderNotFoundError(
                message=f"VM not found at '{url}'."
            )

        # Get the VM's ip addresses by filtering all net_interface.*.ip keys and
        #  extracting their value
        ip_addresses = [v for k, v in radl_system.items()
                        if re.match(r'^net_interface\.[0-9]+\.ip$', k) is not None]

        # Bundle the VM's credentials
        _cred_key_prefix_regex = r'^disk\.[0-9]+\.os\.credentials\.'
        _cred_key_regex = rf'{_cred_key_prefix_regex}(username|password|private_key)$'
        # Filter all items that contain credential related data
        cred_items = \
            {k: v for k, v in radl_system.items() if re.match(_cred_key_regex, k)}
        # Group loose credential items (by prefix)
        extracted_credentials = [
            # strip group prefix from captured keys
            {re.sub(rf"^{k}", "", a): b for a, b in v}
            for k, v in groupby(
                # sort list of credential items before grouping
                sorted(cred_items.items()),
                # group key equals the *matched* key prefix
                key=lambda x: re.match(_cred_key_prefix_regex, x[0]).group(0)
            )
        ]
        # EXAMPLE: See below for an example on how the above block converts the
        #          `radl_system` dictionary into the `extracted_credentials` list.
        #
        #          radl_system = {
        #               "disk.0.os.credentials.username": "user1",
        #               "disk.0.os.credentials.password": "password1",
        #               "disk.0.image.name": "foobar",
        #               "disk.1.os.credentials.username": "user2",
        #               "disk.1.os.credentials.private_key": "privatekey2",
        #               "disk.1.os.credentials.public_key": "pubkey2",
        #               "gpu.vendor": "AMD",
        #          }
        #          extracted_credentials = [
        #               {"username": "user1", "password": "password1"},
        #               {"username": "user2", "private_key": "privatekey2"}
        #                 # "public_key" is ignored because
        #                 #  it is not matched by _cred_key_regex
        #          ]

        # Pack all extracted credentials into InfrastructureProviderVmCredential objects
        credentials = [
            InfrastructureProviderVmCredential(
                username=cred.get('username', None),
                password=cred.get('password', None),
                private_key=cred.get('private_key', None),
            )
            for cred in extracted_credentials
        ]

        return InfrastructureProviderVm(
            name=radl_system['instance_name'],
            ip_addresses=ip_addresses,
            credentials=credentials,
        )

    async def get_vm(self, cluster, ident):
        """Retrieve information about a cluster VM using the infrastructure manager.

        Args:
            cluster (krake.data.kubernetes.Cluster): a cluster managed by the
                infrastructure manager.
            ident (int): index of the VM in the infrastructure manager.

        Returns:
            InfrastructureProviderVm: A data object that represents an infrastructure
                manager VM with the retrieved information.

        Raises:
            InfrastructureProviderRetrieveError: when the VM informations cannot be
                retrieved.
            ValueError: when the given `ident` value is not an integer.
            ValueError: when the given cluster has no valid cluster id.

        Delegates to:
            :meth:`self._get_vm_by_url`: To retrieve the cluster VM information by url
        """
        if not isinstance(ident, int):
            raise ValueError(f"Given VM index (ident) is not an integer: {str(ident)}")

        try:
            infrastructure_id = UUID(cluster.status.cluster_id)
        except ValueError as e:
            raise ValueError("Given cluster has no valid `status.cluster_id`") from e

        index = str(ident)
        infrastructure_id = cluster.status.cluster_id

        url = (
            URL(self.infrastructure_provider.spec.im.url)
            / "infrastructures/"
            / infrastructure_id
            / "vms"
            / index
        )
        return await self._get_vm_by_url(url)

    async def get(self, cluster):
        """Retrieve information about a cluster using the infrastructure manager.

        Args:
            cluster (krake.data.kubernetes.Cluster): a cluster managed by the
                infrastructure manager.

        Returns:
            InfrastructureProviderCluster: data object that represents the corresponding
                real world cluster in the infrastructure manager.

        Raises:
            ValueError: when the given cluster has no valid cluster_id
                ('status.cluster_id' property).
            InfrastructureProviderRetrieveError: when the given cluster has no
                cluster_id or some non-optional information (vms) could not be collected
                from the infrastructure manager.
        """
        try:
            infrastructure_id = UUID(cluster.status.cluster_id)
        except ValueError as e:
            raise ValueError("Given cluster has no valid `status.cluster_id`") from e

        vms = [await self._get_vm_by_url(url)
               for url in await self._enumerate_cluster_nodes_by_url(infrastructure_id)]

        return InfrastructureProviderCluster(
            id=infrastructure_id,
            vms=vms,
        )
