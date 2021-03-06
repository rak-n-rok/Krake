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
    migration: bool = True


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
        manifest (list[dict]): List of Kubernetes objects currently currently
            existing
        mangling (list[dict]): manifest augmented by additional resources
            needed to be created for the functioning of internal mechanisms,
            such as the "Complete Hook".
        token (str): Token for the identification of the "Complete Hook" request
    """

    state: ApplicationState = ApplicationState.PENDING
    kube_controller_triggered: datetime = None
    scheduled: datetime = None
    scheduled_to: ResourceRef = None
    running_on: ResourceRef = None
    services: dict = field(default_factory=dict)
    manifest: List[dict] = None
    mangling: List[dict] = None
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
