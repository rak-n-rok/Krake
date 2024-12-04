"""Data model definitions for Kubernetes-related resources"""

import logging
from enum import Enum, auto
from dataclasses import field
from typing import List, Dict, Union
from datetime import datetime
from marshmallow import ValidationError
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.config import ConfigException
from toscaparser.tosca_template import ToscaTemplate, log
from toscaparser.common.exception import TOSCAException

from krake.utils import get_kubernetes_resource_idx, cache_non_hashable
from . import persistent
from .serializable import Serializable, ApiObject
from .core import Metadata, ListMetadata, Status, ResourceRef, MetricRef, Reason
from .constraints import LabelConstraint, MetricConstraint


# Set `toscaparser` logger to the WARNING level.
# The default INFO level does not log any important logs so far.
log.setLevel(logging.WARNING)


class CloudConstraints(Serializable):
    """Constraints for the :class:`Cloud` to which this cluster is
    scheduled.
    """

    labels: List[LabelConstraint] = None
    metrics: List[MetricConstraint] = None


class ClusterCloudConstraints(Serializable):
    """Constraints restricting the scheduling decision for a
    :class:`Cluster`.
    """

    cloud: CloudConstraints


class ClusterConstraints(Serializable):
    labels: List[LabelConstraint] = None
    custom_resources: List[str] = field(default_factory=list)
    metrics: List[MetricConstraint] = None


class Constraints(Serializable):
    cluster: ClusterConstraints
    migration: bool = True


def _validate_manifest(manifest):
    """Validate the content of a manifest provided as a list.

    Resources without API version, kind, metadata
    or name are considered invalid.

    Args:
        manifest (list): manifest to validate.

    Raises:
        ValidationError: if any error occurred in any resource inside the manifest. The
            message is a list with one list per resource. This list contains all errors
            for the current resource.

    Returns:
        bool: True if no validation error occurred or if manifest is empty.

    """
    if not manifest:
        return True

    errors = []
    # For each resource, create a list of errors:
    for index, resource in enumerate(manifest):
        resource_errors = []

        msg_fmt = "Field '{field}' not found in resource"
        msg_fmt += f" at index {index}"
        name = resource.get("metadata", {}).get("name")
        if name:
            msg_fmt += f" (metadata.name: {name!r})"
        else:
            resource_errors.append(msg_fmt.format(field="metadata.name"))

        for attribute in ["apiVersion", "kind", "metadata"]:
            if attribute not in resource:
                resource_errors.append(msg_fmt.format(field=attribute))

        errors.extend(resource_errors)

    if any(errors):
        raise ValidationError(errors)

    return True


@cache_non_hashable(maxsize=1024)
def _validate_tosca_dict(tosca):
    """Validate the content of a TOSCA template provided as a dict.

     If a TOSCA template does not pass the
     :class:`toscaparser.tosca_template.ToscaTemplate` validation,
     it is considered invalid.

     The :func:`_validate_tosca` is cached by the :func:`hashable_lru` decorator.
     It saves resources, because the instance of :class:`Application` is created
     multiple times during app creation or update. Then the Tosca parser
     has to parse and validate the same TOSCA template multiple times, which may
     take some time.

    Note regarding memory complexity:
         The current :func:`cache_non_hashable` maxsize is set to 1024. We consider this
         number safe from the memory footprint point of view. The assumption was done
         based on the following:
         - The cache size of the TOSCA template which contains 10 jobs has a memory
           footprint of approx. 3400B. So the total memory footprint may be
           3400B*1024~=3.5MB, counted by https://code.activestate.com/recipes/577504/
         - The above is acceptable even when the total memory footprint is
           multiplied by 10 or more
     Note regarding time complexity:
         The parsing and validation of a simple TOSCA template that
         contains only a single k8s job take approx. 0.56s (based on the basic
         measurement of elapsed time from 1000 runs). The same test with caching
         (which includes serialization of parameters) takes approx. 0.0008s.

     Args:
         tosca (dict): TOSCA template to validate.

     Raises:
         ValidationError: if any error occurred in TOSCA parser validation.

     Returns:
         bool: True if no validation error occurred.

    """
    try:
        ToscaTemplate(yaml_dict_tpl=tosca)
    except TOSCAException:
        raise ValidationError("Invalid TOSCA template content.")

    return True


def _validate_tosca_url(tosca):
    """Validate the suffix of a TOSCA template provided as a URL.

    The TOSCA template URL should have a `.yaml` or `.yml` suffix.

    Note:
      It is possible to pass the provided URL to the
      :class:`toscaparser.tosca_template.ToscaTemplate` and
      validate the content of the TOSCA template as well.
      Keep in mind, that the `toscaparser` has to download
      and parse the TOSCA template from the given URL, and then
      validate it. This could be a time-consuming action,
      not suitable for validation. Caching is also not an option
      here, because the TOSCA template could be updated on the
      remote server, but the URL could be the same.
      Therefore, only the suffix of the provided URL is validated here.

    Args:
        tosca (str): TOSCA URL to validate.

     Raises:
         ValidationError: if the TOSCA URL does not have the requested suffix.

     Returns:
         bool: True if no validation error occurred.

    """
    if not tosca.endswith((".yaml", ".yml")):
        raise ValidationError("Invalid TOSCA template URL.")

    return True


def _validate_tosca_cluster(tosca):
    """Validate the TOSCA template provided as a dict.

    The Cluster admin  kubeconfig is retrieved from the
    TOSCA template outputs. Hence, outputs should be correctly
    defined in the TOSCA template to allow kubeconfig retrieval.
    The key `kubeconfig` is required.

    Example:
        .. code:: yaml

           topology_template:
             outputs:
               kubeconfig:
                 value: { get_attribute: [... ] }

    Args:
        tosca (dict): the TOSCA template to validate.

     Raises:
         ValidationError: if the TOSCA template is considered invalid.

     Returns:
         bool: True if no validation error occurred or :args:`tosca` is empty.

    """
    if not tosca:
        return True

    if not tosca.get("topology_template", {}).get("outputs", {}).get("kubeconfig"):
        raise ValidationError(
            "Invalid TOSCA template content. The output `kubeconfig` is missing."
        )

    return _validate_tosca_dict(tosca)


def _validate_tosca(tosca):
    """Validate the TOSCA template provided as a dict or URL.

    Args:
        tosca (Union[dict, str]): the TOSCA template dict or URL to validate.

     Raises:
         ValidationError: if the TOSCA template is considered invalid.

     Returns:
         bool: True if no validation error occurred or :args:`tosca` is empty.

    """
    if not tosca:
        return True

    if isinstance(tosca, dict):
        return _validate_tosca_dict(tosca)

    if isinstance(tosca, str):
        return _validate_tosca_url(tosca)

    raise ValidationError("Invalid TOSCA template type.")


def _validate_csar(csar):
    """Validate the suffix of a CSAR archive provided as a URL.

    A CSAR archive URL should have a `.csar` or `.zip` suffix.

    Note:
      It is possible to pass the provided URL to the
      :class:`toscaparser.tosca_template.ToscaTemplate` and
      validate the content of the CSAR archive as well.
      Keep in mind, that the `toscaparser` has to download
      and parse the CSAR archive from the given URL and then
      validate it. This could be a time-consuming action,
      not suitable for validation. Caching is also not an option
      here, because the CSAR archive could be updated on the
      remote server, but the URL could be the same.
      Therefore, only the suffix of a provided URL is validated here.

    Args:
        csar (str): CSAR URL to validate.

     Raises:
         ValidationError: if CSAR URL does not have the requested suffix.

     Returns:
         bool: True if no validation error occurred.

    """
    if not csar.endswith((".csar", ".zip")):
        raise ValidationError("Invalid CSAR archive URL.")

    return True


class ObserverSchemaError(Exception):
    """Custom exception raised if the validation of the observer_schema fails"""


def _validate_observer_schema_dict(
    partial_schema, first_level=False, is_metadata=False
):
    """Together with :func:`_validate_observer_schema_list``, this function
    is called recursively to validate a partial ``observer_schema``.

    Args:
        partial_schema (dict): Partial observer_schema to validate
        first_level (bool, optional): Boolean to indicate if the validation is performed
            on the first level dictionary of the resource, as additional checks should
            then be performed

    Raises:
        ValueError: If the partial observer_schema is not valid
        TypeError: If the partial observer_schema is not valid
            (value of key metadata is not of type dictionary)

    In case of ``first_level`` dictionary (i.e. complete ``observer_schema`` for a
    resource), the keys necessary for identifying the resource have to be present.

    """
    if first_level:
        for key_name in ["apiVersion", "kind"]:
            if partial_schema.get(key_name, None) is None:
                raise ValueError(f"{key_name} is not defined")

        metadata = partial_schema.get("metadata", None)
        if metadata is None:
            raise ValueError("metadata dictionary is not defined")
        if not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary")
        if metadata.get("name", None) is None:
            raise ValueError("name is not defined in the metadata dictionary")

        _validate_observer_schema_dict(metadata, is_metadata=True)

    for key, value in partial_schema.items():
        # skip already validated items
        if (
            first_level
            and key in ["apiVersion", "kind", "metadata"]
            or is_metadata
            and key == "name"
        ):
            continue

        if isinstance(value, dict):
            _validate_observer_schema_dict(value)

        elif isinstance(value, list):
            _validate_observer_schema_list(value)

        elif value is not None:
            raise ValueError(f"Value of '{key}' is not 'None'")


def _validate_observer_schema_list(partial_schema):
    """Together with :func:`_validate_observer_schema_dict``, this function is called
    recursively to validate a partial ``observer_schema``.

    Args:
        partial_schema (list): Partial observer_schema to validate

    Raises:
        ValueError: If the partial observer_schema is not valid

    Especially, this function checks that the list control dictionary is present and
    well-formed.

    """
    if not isinstance(partial_schema[-1], dict):
        raise ValueError("Special list control dictionary not found")
    if (
        "observer_schema_list_min_length" not in partial_schema[-1]
        or "observer_schema_list_max_length" not in partial_schema[-1]
    ):
        raise ValueError("Special list control dictionary malformed")

    observer_schema_list_min_length = partial_schema[-1][
        "observer_schema_list_min_length"
    ]
    observer_schema_list_max_length = partial_schema[-1][
        "observer_schema_list_max_length"
    ]

    if not isinstance(observer_schema_list_min_length, int):
        raise ValueError("observer_schema_list_min_length should be an integer")
    if not isinstance(observer_schema_list_max_length, int):
        raise ValueError("observer_schema_list_max_length should be an integer")

    if observer_schema_list_min_length < 0:
        raise ValueError("Invalid value for observer_schema_list_min_length")
    if observer_schema_list_max_length < 0:
        raise ValueError("Invalid value for observer_schema_list_max_length")

    if observer_schema_list_max_length != 0:
        if observer_schema_list_max_length < observer_schema_list_min_length:
            raise ValueError(
                "observer_schema_list_max_length is inferior to "
                "observer_schema_list_min_length"
            )

        if observer_schema_list_max_length < len(partial_schema[:-1]):
            raise ValueError(
                "observer_schema_list_max_length is inferior to the number of observed "
                "elements"
            )

    for value in partial_schema[:-1]:

        if isinstance(value, dict):
            _validate_observer_schema_dict(value)

        elif isinstance(value, list):
            _validate_observer_schema_list(value)

        else:
            if value is not None:
                raise ValueError("Element of a list is not 'None'")


def _validate_observer_schema(observer_schema, manifest):
    """Validation method for observer_schema

    Args:
        observer_schema (list[dict]): List of dictionaries of fields that should be
            observed by the Kubernetes Observer.

    Raises:
        ObserverSchemaError: If the observer_schema is not valid

    """

    for resource_observer_schema in observer_schema:

        try:
            _validate_observer_schema_dict(resource_observer_schema, first_level=True)
        except (ValueError, TypeError) as e:
            raise ObserverSchemaError(e)
        try:
            get_kubernetes_resource_idx(manifest, resource_observer_schema)
        except IndexError:
            raise ObserverSchemaError("Observed resource must be in manifest")


class ApplicationSpec(Serializable):
    """Spec subresource of :class:`Application`.

    Attributes:
        manifest (list[dict]): List of Kubernetes resources to create. This attribute
            is managed by the user.
        tosca (Union[dict, str], optional): The to be created TOSCA template.
            A TOSCA template should be defined as a python dict or with the
            URL, where the template is located.
            This attribute is managed by the user.
        csar (str, optional): The to be created CSAR archive.
            A CSAR file should be defined with the URL, where the
            archive is located.
            This attribute is managed by the user.
        observer_schema (list[dict], optional): List of dictionaries of fields that
            should be observed by the Kubernetes Observer. This attribute is
            managed by the user. Using this attribute as a basis, the Kubernetes
            Controller generates the ``status.mangled_observer_schema``.
        constraints (Constraints, optional): Scheduling constraints
        hooks (list[str], optional): List of enabled hooks
        shutdown_grace_time (int): timeout in seconds for the shutdown hook
        backoff (field, optional): multiplier applied to backoff_delay between attempts.
            default: 1 (no backoff)
        backoff_delay (field, optional): delay [s] between attempts. default: 1
        backoff_limit (field, optional):  a maximal number of attempts,
            default: -1 (infinite)
        auto_cluster_create (bool): flag to show if automatic cluster creation
            is allowed
    """

    manifest: List[dict] = field(metadata={"validate": _validate_manifest})
    tosca: Union[dict, str] = field(
        metadata={"validate": _validate_tosca}, default_factory=dict
    )
    csar: str = field(metadata={"validate": _validate_csar}, default=None)
    observer_schema: List[dict] = field(default_factory=list)
    constraints: Constraints
    hooks: List[str] = field(default_factory=list)
    shutdown_grace_time: int = 30
    backoff: int = field(default=1)
    backoff_delay: int = field(default=1)
    backoff_limit: int = field(default=-1)
    storage_migration: str = "none"
    auto_cluster_create: bool = False

    def __post_init__(self):
        """Method automatically ran at the end of the :meth:`__init__` method, used to
        validate dependent attributes.

        Validations:
        1. At least one of the attributes from the following should be defined:
        - :attr:`manifest`
        - :attr:`tosca`
        - :attr:`csar`
        If the user specified multiple attributes at once, the :attr:`manifest`
        has the highest priority, after that :attr:`tosca` and :attr:`csar`.

        2. If a custom :attr:`observer_schema` and :attr:`manifest` are specified
        by the user, the :attr:`observer_schema` needs to be validated, i.e. verified
        that resources are correctly identified and refer to resources defined in
        :attr:`manifest`, that fields are correctly identified and that all special
        control dictionaries are correctly defined.

        Note: These validations cannot be achieved directly using the ``validate``
         metadata, since ``validate`` must be a zero-argument callable, with
         no access to the other attributes of the dataclass.

        """
        if not any([self.manifest, self.tosca, self.csar]):
            raise ValidationError(
                "The application should be defined by a manifest file,"
                " a TOSCA template or a CSAR file."
            )

        if self.manifest:
            _validate_observer_schema(self.observer_schema, self.manifest)


class ApplicationState(Enum):
    PENDING = auto()
    CREATING = auto()
    RUNNING = auto()
    RECONCILING = auto()
    TRANSLATING = auto()
    RETRYING = auto()
    RESTARTING = auto()
    WAITING_FOR_CLEANING = auto()
    READY_FOR_ACTION = auto()
    MIGRATING = auto()
    WAITING_FOR_CLUSTER_CREATION = auto()
    DELETING = auto()
    DELETED = auto()
    DEGRADED = auto()
    FAILED = auto()
    COMPLETED = auto()

    def equals(self, string):
        return self.name == string.upper()


class ContainerHealth(Serializable):
    desired_pods: int = 0
    running_pods: int = 0
    completed_pods: int = 0
    failed_pods: int = 0


class ApplicationStatus(Status):
    """Status subresource of :class:`Application`.

    Attributes:
        state (ApplicationState): Current state of the application
        container_health (ContainerHealth): Specific details of the application
        kube_controller_triggered (datetime.datetime): Timestamp that represents the
            last time the current version of the Application was scheduled (version here
            meaning the Application after an update). It is only updated after the
            update of the Application led to a rescheduling, or at the first scheduling.
            It is used to keep a strict workflow between the Scheduler and
            Kubernetes Controller: the first one should always handle an Application
            creation or update before the latter. Only after this field has been updated
            by the Scheduler to be higher than the modified timestamp can the
            Kubernetes Controller handle the Application.
        scheduled (datetime.datetime): Timestamp that represents the last time the
            application was scheduled to a different cluster, in other words when
            ``scheduled_to`` was modified. Thus, it is updated at the first binding to a
            cluster, or during the binding with a different cluster. This represents the
            timestamp when the current Application was scheduled to its current cluster,
            even if it has been updated in the meantime.
        scheduled_to (ResourceRef): Reference to the cluster where the
            application should run.
        running_on (ResourceRef): Reference to the cluster where the
            application is currently running.
        services (dict): Mapping of Kubernetes service names to their public
            endpoints.
        mangled_observer_schema(list[dict]): Actual observer schema used by the
            Kubernetes Observer, generated from the user inputs ``spec.observer_schema``
        last_observed_manifest (list[dict]): List of Kubernetes resources observed on
            the Kubernetes API.
        last_applied_manifest (list[dict]): List of Kubernetes resources created via
            Krake. The manifest is augmented by additional resources needed to be
            created for the functioning of internal mechanisms, such as the "Complete
            Hook".
        complete_token (str): Token to identify the "Complete Hook" request
        complete_cert (str): certificate for the identification of the "Complete Hook".
        complete_key (str): key for the certificate of the "Complete Hook"
            identification.
        shutdown_token (str): Token to identify the "Shutdown Hook" request
        shutdown_cert (str): certificate for the identification of the "Shutdown Hook".
        shutdown_key (str): key for the certificate of the "Shutdown Hook"
            identification.
        shutdown_grace_period (datetime): time period the shutdown method waits on after
            the shutdown command was issued to an object
        auto_cluster_create_started (str): flag that shows if the automatic cluster
            creation process was already started
        migration_retries (int): number of retries for this migration
        migration_timeout (int):
            timestamp until the timeout for migration of this app ends
    """

    state: ApplicationState = ApplicationState.PENDING
    container_health: ContainerHealth = ContainerHealth
    kube_controller_triggered: datetime = None
    scheduled: datetime = None
    scheduled_to: ResourceRef = None
    running_on: ResourceRef = None
    retries: int = None
    scheduled_retry: datetime = None
    services: dict = field(default_factory=dict)
    mangled_observer_schema: List[dict] = field(default_factory=list)
    last_observed_manifest: List[dict] = field(default_factory=list)
    last_applied_manifest: List[dict] = field(default_factory=list)
    complete_token: str = None
    complete_cert: str = None
    complete_key: str = None
    shutdown_token: str = None
    shutdown_cert: str = None
    shutdown_key: str = None
    shutdown_grace_period: datetime = None
    auto_cluster_create_started: str = None
    migration_retries: int = 0
    migration_timeout: int = 0


@persistent("/kubernetes/applications/{namespace}/{name}")
class Application(ApiObject):
    api: str = "kubernetes"
    kind: str = "Application"
    metadata: Metadata
    spec: ApplicationSpec
    status: ApplicationStatus = field(metadata={"subresource": True})


class ApplicationList(ApiObject):
    api: str = "kubernetes"
    kind: str = "ApplicationList"
    metadata: ListMetadata
    items: List[Application]


class ApplicationComplete(ApiObject):
    api: str = "kubernetes"
    kind: str = "Complete"
    token: str = None


class ApplicationShutdown(ApiObject):
    api: str = "kubernetes"
    kind: str = "Shutdown"
    token: str = None


class ClusterBinding(ApiObject):
    api: str = "kubernetes"
    kind: str = "ClusterBinding"
    cluster: ResourceRef


def _validate_kubeconfig(kubeconfig):
    if not kubeconfig:
        return True

    try:
        KubeConfigLoader(kubeconfig)
    except ConfigException as err:
        raise ValidationError(str(err))

    if len(kubeconfig["contexts"]) != 1:
        raise ValidationError("Only one context is allowed")

    if len(kubeconfig["users"]) != 1:
        raise ValidationError("Only one user is allowed")

    if len(kubeconfig["clusters"]) != 1:
        raise ValidationError("Only one cluster is allowed")

    return True


class ClusterSpec(Serializable):
    """Spec subresource of :class:`Cluster`

    Attributes:
        kubeconfig (dict): path to the kubeconfig file for the cluster to
            register.
        custom_resources (list): name of all custom resources that are available on
            the current cluster.
        metrics (list): metrics used on the cluster.
        backoff (field, optional): multiplier applied to backoff_delay between attempts.
            default: 1 (no backoff)
        backoff_delay (field, optional): delay [s] between attempts. default: 1
        backoff_limit (field, optional):  a maximal number of attempts,
            default: -1 (infinite)
        auto_generated (boolean, optional): flag to show if the cluster was
            automatically generated
    """

    kubeconfig: dict = field(
        metadata={"validate": _validate_kubeconfig}, default_factory=dict
    )
    tosca: dict = field(
        metadata={"validate": _validate_tosca_cluster}, default_factory=dict
    )
    custom_resources: List[str] = field(default_factory=list)
    constraints: ClusterCloudConstraints
    # FIXME needs further discussion how to register stand-alone kubernetes cluster as
    #  a cluster which should be processed by krake.controller.scheduler
    metrics: List[MetricRef] = field(default_factory=list)
    inherit_metrics: bool = field(default=False)
    backoff: int = field(default=1)
    backoff_delay: int = field(default=1)
    backoff_limit: int = field(default=-1)
    auto_generated: bool = False

    def __post_init__(self):
        """Method automatically ran at the end of the :meth:`__init__` method, used to
        validate dependent attributes.

        Validations:
        - At least one of the attributes from the following should be defined:
          - :attr:`kubeconfig`
          - :attr:`tosca`

        Note: This validation cannot be achieved directly using the ``validate``
         metadata, since ``validate`` must be a zero-argument callable, with
         no access to the other attributes of the dataclass.

        """
        if not any([self.kubeconfig, self.tosca]):
            raise ValidationError(
                "The cluster should be defined by a kubeconfig file or"
                " a TOSCA template."
            )


class ClusterState(Enum):
    # Initial state
    PENDING = auto()
    # Cluster states
    ONLINE = auto()
    CONNECTING = auto()
    OFFLINE = auto()
    UNHEALTHY = auto()
    NOTREADY = auto()
    FAILING_METRICS = auto()
    # Cluster infrastructure states
    CREATING = auto()
    RECONCILING = auto()
    DELETING = auto()
    FAILING_RECONCILIATION = auto()
    FAILED = auto()
    DEGRADED = auto()


class ClusterNodeCondition(Serializable):
    """Cluster node condition subresource of :class:`ClusterNodeStatus`.

    Attributes:
        message (str): Human readable message indicating details about last transition.
        reason (str): A brief reason for the condition's last transition.
        status (str): Status of the condition, one of "True", "False", "Unknown".
        type (str): Type of node condition.

    """

    message: str
    reason: str
    status: str
    type: str


class ClusterNodeStatus(Serializable):
    """Cluster node status subresource of :class:`ClusterNode`.

    Attributes:
        conditions (list[ClusterNodeCondition]): List of current observed
            node conditions.

    """

    conditions: List[ClusterNodeCondition]


class ClusterNodeMetadata(Serializable):
    """Cluster node metadata subresource of :class:`ClusterNode`.

    Attributes:
        name (str): Name of the cluster node.

    """

    name: str


class InfrastructureNodeCredential(Serializable):
    """Cluster node credential subresource of :class:`ClusterNode`.

    Holds the type and data of a single cluster node credential.

    Attributes:
        type (str): Type of the credential (one of: "login")
        username (str): Name of the login user.
        password (str, optional): Password of the login user. Is suppressed in repr.
        private_key (str, optional): SSH key whose public part is registered for the
            login user. Is suppressed in repr.

    One of password or private_key should be specified.
    """

    _types = ["login"]  # Supported credential types

    type: str
    username: str
    password: str = field(default=None, repr=False)
    private_key: str = field(default=None, repr=False)

    def __post_init__(self):
        # Allow only supported credential types
        if self.type not in self._types:
            raise ValidationError(
                f"""Invalid credential type '{self.type}', must be one of"""
                f""" {', '.join([f"'{t}'" for t in self._types])}."""
            )


class InfrastructureNode(Serializable):
    """A data object representing a real world node belonging to a cluster

    Usually corresponds to a VM/node/etc. reported by an infrastructure provider.

    Attributes:
        ip_addresses (list[str], optional): Current IP addresses of the cluster node.
        credentials (List[ClusterNodeCredential]): Current credentials of the cluster
            node.
    """

    ip_addresses: List[str] = None
    credentials: List[InfrastructureNodeCredential] = field(default_factory=list)


class ClusterInfrastructureData(Serializable):
    """A data object holding data about the real world infrastructure of a cluster

    Usually holds all data that was collected from an infrastructure provider.

    Attributes:
        nodes (list[InfrastructureNode]): List of infrastructure nodes on which the
            cluster is running.
        kubeconfig (dict): Admin kubeconfig of the cluster that an infrastructure
            provider reported.
    """

    nodes: List[InfrastructureNode] = field(default_factory=list)
    kubeconfig: dict = None


class ClusterInfrastructure(Serializable):
    """Cluster infrastructure subresource of :class:`Cluster`

    Attributes:
        updated (datetime): Time when the cluster infrastructure data was last updated.
        data (ClusterInfrastructureData): Data about the real world infrastructure of
            the cluster that was retrieved from an infrastructure provider and is not
            status or metric, e.g. credentials, specs.
    """

    updated: datetime = None
    data: ClusterInfrastructureData = None


class ClusterNode(Serializable):
    """Cluster node subresource of :class:`ClusterStatus`.

    Attributes:
        api (str, optional): Api version if the resource.
        kind (str, optional): Kind of the resource.
        status (ClusterNodeStatus, optional): Current status of the cluster node.

    """

    api: str = "kubernetes"
    kind: str = "ClusterNode"
    metadata: ClusterNodeMetadata
    status: ClusterNodeStatus = None


class ClusterStatus(Status):
    """Status subresource of :class:`Cluster`.

    Attributes:
        kube_controller_triggered (datetime): Time when the Kubernetes controller was
        triggered. This is used to handle cluster state transitions.
        state (ClusterState): Current state of the cluster.
        metrics_reasons (dict[str, Reason]): mapping of the name of the metrics for
            which an error occurred to the reason for which it occurred.
        last_applied_tosca (dict): TOSCA template applied via Krake.
        nodes (list[ClusterNode]): list of cluster nodes.
        cluster_id (str): UUID or name of the cluster (infrastructure) given by the
            infrastructure provider
        scheduled (datetime.datetime): Timestamp that represents the last time the
            cluster was scheduled to a cloud.
        scheduled_to (ResourceRef): Reference to the cloud where the cluster should run.
        running_on (ResourceRef): Reference to the cloud where the cluster is running.
        retries (int): Count of remaining retries to access the cluster. Is set
            via the Attribute backoff in the ClusterSpec.
    """

    kube_controller_triggered: datetime = None
    state: ClusterState = ClusterState.PENDING
    metrics_reasons: Dict[str, Reason] = field(default_factory=dict)
    last_applied_tosca: dict = field(default_factory=dict)
    nodes: List[ClusterNode] = field(default_factory=list)
    cluster_id: str = None
    scheduled: datetime = None
    scheduled_to: ResourceRef = None
    running_on: ResourceRef = None
    retries: int = field(default_factory=int)


@persistent("/kubernetes/clusters/{namespace}/{name}")
class Cluster(ApiObject):
    """An API object that represents a cluster

    Attributes:
        api (str, optional): The name of the Krake API the object belongs to
        kind (str, optional): Type of the API object
        metadata (Metadata): Metadata about the API object
        spec (ClusterSpec): The specification of the cluster
        status (ClusterStatus): The status of the cluster (subresource)
        infrastructure (ClusterInfrastructure): The infrastructure data of the cluster
            (subresource). `None` means that no infrastructure data is available or has
            been supplied yet.
    """

    api: str = "kubernetes"
    kind: str = "Cluster"
    metadata: Metadata
    spec: ClusterSpec
    status: ClusterStatus = field(metadata={"subresource": True})
    infrastructure: ClusterInfrastructure = field(
        metadata={"subresource": True}, default=None
    )
    #   NOTE: `None` has been choosen to mean no data availabe or supplied yet instead
    #   of an empty ClusterInfrastructure object which would mean that the cluster is
    #   backed by no actual infrastructure which is impossible or that its
    #   infrastructure is just getting created.


class ClusterList(ApiObject):
    """An API object that holds a list of clusters

    Attributes:
        api (str, optional): The name of the Krake API the object belongs to
        kind (str, optional): Type of the API object
        metadata (ListMetadata): Metadata about the API object
        items (List[Cluster]): A list of cluster API objects
    """

    api: str = "kubernetes"
    kind: str = "ClusterList"
    metadata: ListMetadata
    items: List[Cluster]
