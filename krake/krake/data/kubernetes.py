"""Data model definitions for Kubernetes-related resources"""
from enum import Enum, auto
from dataclasses import field
from typing import List
from datetime import datetime
from marshmallow import ValidationError
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.config import ConfigException

from . import persistent
from .serializable import Serializable, ApiObject
from .core import Metadata, ListMetadata, Status, ResourceRef, MetricRef
from .constraints import LabelConstraint


class ClusterConstraints(Serializable):
    labels: List[LabelConstraint] = None
    custom_resources: List[str] = field(default_factory=list)


class Constraints(Serializable):
    cluster: ClusterConstraints = None


class ApplicationSpec(Serializable):
    manifest: List[dict]
    constraints: Constraints = None
    hooks: List[str] = field(default_factory=list)


class ApplicationState(Enum):
    PENDING = auto()
    CREATING = auto()
    RUNNING = auto()
    RECONCILING = auto()
    MIGRATING = auto()
    DELETING = auto()
    FAILED = auto()


class ResourceVersion(Serializable):
    """Holds information about the resource version of a Kubernetes Resource.

    The resource version is used by the Kubernetes Observer to detect changes in the
    real-world resource by comparing the :attr:`last_applied_resource_version` and the
    :attr:`observed_resource_version`.

    The three attributes :attr:`api_version`, :attr:`kind`, and :attr:`name` are used
    to identify a resource uniquely by crafting a :class:`ResourceID` when needed. We
    don't store the corresponding :class:`ResourceID` as it is not human readable.

    Attributes:
        api_version (str): API Version of the resource as defined in the Kubernetes
            manifest file
        kind (str): kind of the resource as defined in the Kubernetes manifest file
        name (str): Name of the resource as defined in the Kubernetes manifest file
        last_applied_resource_version (int): Resource version of the Kubernetes
            resource after the last application of the desired manifest file (create
            or update of the resource).
        observed_resource_version (int): Current resource version of the Kubernetes
            resource as observed bu the KubernetesObserver.
    """

    api_version: str
    kind: str
    name: str
    last_applied_resource_version: int
    observed_resource_version: int


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
        manifest (list[dict]): List of Kubernetes objects currently currently
            existing
        resource_versions (list[ResourceVersion]): List of resource versions of
            each resources created by Krake.

    """

    state: ApplicationState = ApplicationState.PENDING
    scheduled: datetime = None
    scheduled_to: ResourceRef = None
    running_on: ResourceRef = None
    services: dict = field(default_factory=dict)
    manifest: List[dict] = None
    mangling: List[dict] = None
    token: str = None
    resource_versions: List[ResourceVersion] = field(default_factory=list)


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
