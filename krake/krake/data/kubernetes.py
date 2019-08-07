"""Data model definitions for Kubernetes-related resources"""
from enum import Enum, auto
from datetime import datetime

from . import Key
from .serializable import Serializable
from .core import NamespacedMetadata


class ApplicationSpec(Serializable):
    manifest: str


class ApplicationState(Enum):
    PENDING = auto()
    UPDATED = auto()
    SCHEDULED = auto()
    RUNNING = auto()
    DELETING = auto()
    DELETED = auto()
    FAILED = auto()


class ApplicationStatus(Serializable):
    state: ApplicationState
    created: datetime
    modified: datetime
    reason: str = None
    cluster: str = None  # API endpoint of the Kubernetes cluster resource
    services: dict = None


class Application(Serializable):
    metadata: NamespacedMetadata
    spec: ApplicationSpec
    status: ApplicationStatus

    __metadata__ = {
        "key": Key("/kubernetes/applications/{namespace}/{name}", attribute="metadata")
    }


class ClusterBinding(Serializable):
    cluster: str  # API endpoint of the Kubernetes cluster resource


class ClusterKind(Enum):
    EXTERNAL = auto()
    MAGNUM = auto()


class ClusterSpec(Serializable):
    kind: ClusterKind = ClusterKind.EXTERNAL
    kubeconfig: dict = None

    __metadata__ = {"discriminator": "kind"}


class MagnumClusterSpec(ClusterSpec):
    kind: ClusterKind = ClusterKind.MAGNUM
    master_ip: str


class ClusterState(Enum):
    PENDING = auto()
    RUNNING = auto()
    UPDATED = auto()
    DELETING = auto()
    DELETED = auto()
    FAILED = auto()


class ClusterStatus(Serializable):
    state: ClusterState
    created: datetime
    modified: datetime
    reason: str = None


class Cluster(Serializable):
    metadata: NamespacedMetadata
    spec: ClusterSpec
    status: ClusterStatus

    __metadata__ = {
        "key": Key("/kubernetes/clusters/{namespace}/{name}", attribute="metadata")
    }
