"""Data model definitions for Kubernetes-related resources"""
from copy import deepcopy
from enum import Enum, auto
from dataclasses import field
from typing import List
from datetime import datetime
from marshmallow import ValidationError
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.config import ConfigException

from krake.utils import get_kubernetes_resource_idx
from . import persistent
from .serializable import Serializable, ApiObject
from .core import Metadata, ListMetadata, Status, ResourceRef, MetricRef
from .constraints import LabelConstraint


class ClusterConstraints(Serializable):
    labels: List[LabelConstraint] = None
    custom_resources: List[str] = field(default_factory=list)


class Constraints(Serializable):
    cluster: ClusterConstraints = None
    migration: bool = True


class ObserverSchemaError(Exception):
    pass


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
        observer_schema_list_max_length >= -1
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
            get_kubernetes_resource_idx(
                manifest,
                resource_observer_schema["apiVersion"],
                resource_observer_schema["kind"],
                resource_observer_schema["metadata"]["name"],
            )
        except IndexError:
            raise ObserverSchemaError("Observed resource must be in manifest")


class ApplicationSpec(Serializable):
    """Spec subresource of :class:`Application`.

    Attributes:
        manifest (list[dict]): List of Kubernetes resources to create. This attribute
            is managed by the user.
        observer_schema (list[dict], optional): List of dictionaries of fields that
            should be observed by the Kubernetes Observer. This attribute can be
            user defined or automatically initialized from :attr:`manifest`. See
            :meth:`__post_init__`
        constraints (Constraints, optional): Scheduling constraints
        hooks (list[str], optional): List of enabled hooks

    """

    manifest: List[dict]
    observer_schema: List[dict] = field(default_factory=list)
    constraints: Constraints = None
    hooks: List[str] = field(default_factory=list)

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
    MIGRATING = auto()
    DELETING = auto()
    FAILED = auto()


class ApplicationStatus(Status):
    """Status subresource of :class:`Application`.

    Attributes:
        state (ApplicationState): Current state of the application
        scheduled (datetime.datetime): Timestamp when the application was last
            scheduled.
        scheduled_to (ResourceRef): Reference to the cluster where the
            application should run.
        running_on (ResourceRef): Reference to the cluster where the
            application is currently running.
        services (dict): Mapping of Kubernetes service names to their public
            endpoints.
        last_observed_manifest (list[dict]): List of Kubernetes resources observed on
            the Kubernetes API.
        last_applied_manifest (list[dict]): List of Kubernetes resources created via
            Krake. The manifest is augmented by additional resources needed to be
            created for the functioning of internal mechanisms, such as the "Complete
            Hook".
        token (str): Token for the identification of the "Complete Hook" request
    """

    state: ApplicationState = ApplicationState.PENDING
    scheduled: datetime = None
    scheduled_to: ResourceRef = None
    running_on: ResourceRef = None
    services: dict = field(default_factory=dict)
    mangled_observer_schema: List[dict] = field(default_factory=list)
    last_observed_manifest: List[dict] = field(default_factory=list)
    last_applied_manifest: List[dict] = field(default_factory=list)
    token: str = None


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


@persistent("/kubernetes/clusters/{namespace}/{name}")
class Cluster(ApiObject):
    api: str = "kubernetes"
    kind: str = "Cluster"
    metadata: Metadata
    spec: ClusterSpec


class ClusterList(ApiObject):
    api: str = "kubernetes"
    kind: str = "ClusterList"
    metadata: ListMetadata
    items: List[Cluster]
