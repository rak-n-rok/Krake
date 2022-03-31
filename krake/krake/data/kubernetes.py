"""Data model definitions for Kubernetes-related resources"""
from copy import deepcopy
from enum import Enum, auto
from dataclasses import field
from typing import List, Dict
from datetime import datetime
from marshmallow import ValidationError
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.config import ConfigException

from krake.utils import get_kubernetes_resource_idx
from . import persistent
from .serializable import Serializable, ApiObject
from .core import Metadata, ListMetadata, Status, ResourceRef, MetricRef, Reason
from .constraints import LabelConstraint


class ClusterConstraints(Serializable):
    labels: List[LabelConstraint] = None
    custom_resources: List[str] = field(default_factory=list)


class Constraints(Serializable):
    cluster: ClusterConstraints
    migration: bool = True


def _validate_manifest(manifest):
    """Validate the content of a manifest provided as dictionary. Empty manifests,
    resources inside without API version, kind, metadata or name are considered invalid.

    Args:
        manifest (dict): manifest to validate.

    Raises:
        ValidationError: if any error occurred in any resource inside the manifest. The
            message is a list with one list per resource. This list contains all errors
            for the current resource.

    Returns:
        bool: True if no validation error occurred.

    """
    if not manifest:
        raise ValidationError("The manifest file must not be empty.")

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


class ObserverSchemaError(Exception):
    """Custom exception raised if the validation of the observer_schema fails"""


def _validate_observer_schema_dict(partial_schema, first_level=False):
    """Together with :func:`_validate_observer_schema_list``, this function is
    called recursively to validate a partial ``observer_schema``.

    Args:
        partial_schema (dict): Partial observer_schema to validate
        first_level (bool, optional): Boolean to indicate if the validation is performed
            on the first level dictionary of the resource, as additional checks should
            then be performed

    Raises:
        AssertionError: If the partial observer_schema is not valid

    In case of ``first_level`` dictionary (i.e. complete ``observer_schema`` for a
    resource), the keys necessary for identifying the resource have to be present.

    """
    if first_level:
        try:
            partial_schema.pop("apiVersion")
        except KeyError:
            raise AssertionError("apiVersion is not defined")

        try:
            partial_schema.pop("kind")
        except KeyError:
            raise AssertionError("kind is not defined")

        try:
            metadata = partial_schema.pop("metadata")
            assert isinstance(metadata, dict)
        except (KeyError, AssertionError):
            raise AssertionError("metadata dictionary is not defined")

        try:
            metadata.pop("name")
        except KeyError:
            raise AssertionError("name is not defined in the metadata dictionary")

        _validate_observer_schema_dict(metadata)

    for key, value in partial_schema.items():

        if isinstance(value, dict):
            _validate_observer_schema_dict(value)

        elif isinstance(value, list):
            _validate_observer_schema_list(value)

        else:
            assert value is None, f"Value of '{key}' is not 'None'"


def _validate_observer_schema_list(partial_schema):
    """Together with :func:`_validate_observer_schema_dict``, this function is called
    recursively to validate a partial ``observer_schema``.

    Args:
        partial_schema (list): Partial observer_schema to validate

    Raises:
        AssertionError: If the partial observer_schema is not valid

    Especially, this function checks that the list control dictionary is present and
    well-formed.

    """
    assert isinstance(
        partial_schema[-1], dict
    ), "Special list control dictionary not found"
    assert (
        "observer_schema_list_min_length" in partial_schema[-1]
        and "observer_schema_list_max_length" in partial_schema[-1]
    ), "Special list control dictionary malformed"

    observer_schema_list_min_length = partial_schema[-1][
        "observer_schema_list_min_length"
    ]
    observer_schema_list_max_length = partial_schema[-1][
        "observer_schema_list_max_length"
    ]

    assert isinstance(
        observer_schema_list_min_length, int
    ), "observer_schema_list_min_length should be an integer"
    assert isinstance(
        observer_schema_list_max_length, int
    ), "observer_schema_list_max_length should be an integer"

    assert (
        observer_schema_list_min_length >= 0
    ), "Invalid value for observer_schema_list_min_length"
    assert (
        observer_schema_list_max_length >= 0
    ), "Invalid value for observer_schema_list_max_length"

    if observer_schema_list_max_length != 0:
        assert observer_schema_list_max_length >= observer_schema_list_min_length, (
            "observer_schema_list_max_length is inferior to "
            "observer_schema_list_min_length"
        )
        assert observer_schema_list_max_length >= len(partial_schema[:-1]), (
            "observer_schema_list_max_length is inferior to the number of observed "
            "elements"
        )

    for value in partial_schema[:-1]:

        if isinstance(value, dict):
            _validate_observer_schema_dict(value)

        elif isinstance(value, list):
            _validate_observer_schema_list(value)

        else:
            assert value is None, "Element of a list is not 'None'"


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
            _validate_observer_schema_dict(
                deepcopy(resource_observer_schema), first_level=True
            )
        except AssertionError as e:
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
        observer_schema (list[dict], optional): List of dictionaries of fields that
            should be observed by the Kubernetes Observer. This attribute is managed by
            the user. Using this attribute as a basis, the Kubernetes Controller
            generates the ``status.mangled_observer_schema``.
        constraints (Constraints, optional): Scheduling constraints
        hooks (list[str], optional): List of enabled hooks
        shutdown_grace_time (int): timeout in seconds for the shutdown hook
    """

    manifest: List[dict] = field(metadata={"validate": _validate_manifest})
    observer_schema: List[dict] = field(default_factory=list)
    constraints: Constraints
    hooks: List[str] = field(default_factory=list)
    shutdown_grace_time: int = 30

    def __post_init__(self):
        """Method automatically ran at the end of the :meth:`__init__` method, used to
        validate :attr:`observer_schema`.

        If a custom :attr:`observer_schema` is specified by the user, it needs to be
        validated, i.e. verify that resources are correctly identified and refer to
        resources defined in :attr:`manifest`, that fields are correctly identified and
        that all special control dictionary are correctly defined.

        This validation cannot be achieved directly using a ``validate`` metadata, as
        ``validate`` must be a zero-argument callable, with no access to the other
        attributes of the dataclass.

        """
        _validate_observer_schema(self.observer_schema, self.manifest)


class ApplicationState(Enum):
    PENDING = auto()
    CREATING = auto()
    RUNNING = auto()
    RECONCILING = auto()
    RETRYING = auto()
    WAITING_FOR_CLEANING = auto()
    READY_FOR_ACTION = auto()
    MIGRATING = auto()
    DELETING = auto()
    DELETED = auto()
    DEGRADED = auto()
    FAILED = auto()

    def equals(self, string):
        return self.name == string.upper()


class ApplicationStatus(Status):
    """Status subresource of :class:`Application`.

    Attributes:
        state (ApplicationState): Current state of the application
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
    """

    state: ApplicationState = ApplicationState.PENDING
    kube_controller_triggered: datetime = None
    scheduled: datetime = None
    scheduled_to: ResourceRef = None
    running_on: ResourceRef = None
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
    kubeconfig: dict = field(metadata={"validate": _validate_kubeconfig})
    custom_resources: List[str] = field(default_factory=list)
    # FIXME needs further discussion how to register stand-alone kubernetes cluster as
    #  a cluster which should be processed by krake.controller.scheduler
    metrics: List[MetricRef] = field(default_factory=list)


class ClusterState(Enum):
    ONLINE = auto()
    CONNECTING = auto()
    OFFLINE = auto()
    UNHEALTHY = auto()
    NOTREADY = auto()
    FAILING_METRICS = auto()


class ClusterStatus(Serializable):
    """Status subresource of :class:`Cluster`.

    Attributes:
        kube_controller_triggered (datetime): Time when the Kubernetes controller was
        triggered. This is used to handle cluster state transitions.
        state (ClusterState): Current state of the cluster.
        metrics_reasons (dict[str, Reason]): mapping of the name of the metrics for
            which an error occurred to the reason for which it occurred.

    """

    kube_controller_triggered: datetime = None
    state: ClusterState = ClusterState.CONNECTING
    metrics_reasons: Dict[str, Reason] = field(default_factory=dict)


@persistent("/kubernetes/clusters/{namespace}/{name}")
class Cluster(ApiObject):
    api: str = "kubernetes"
    kind: str = "Cluster"
    metadata: Metadata
    spec: ClusterSpec
    status: ClusterStatus = field(metadata={"subresource": True})


class ClusterList(ApiObject):
    api: str = "kubernetes"
    kind: str = "ClusterList"
    metadata: ListMetadata
    items: List[Cluster]
