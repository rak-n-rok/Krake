"""Data model definitions for Kubernetes-related resources"""
from enum import Enum, auto
from datetime import datetime
from typing import NamedTuple

from .serializable import Serializable, serializable


class ApplicationState(Enum):
    PENDING = auto()
    UPDATED = auto()
    SCHEDULED = auto()
    RUNNING = auto()
    DELETING = auto()
    DELETED = auto()
    FAILED = auto()


@serializable
class ClusterRef(NamedTuple):
    """Reference to a cluster

    Attributes:
        user (str): Username of the cluster owner
        name (str): Cluster name
    """

    user: str
    name: str

    @classmethod
    def from_cluster(cls, cluster):
        return cls(user=cluster.user, name=cluster.name)


class ApplicationStatus(Serializable):
    state: ApplicationState
    created: datetime
    modified: datetime
    reason: str = None
    cluster: ClusterRef = None


class Application(Serializable):
    name: str
    user: str
    uid: str
    manifest: str
    status: ApplicationStatus

    __identity__ = ("user", "name")
    __namespace__ = "/k8s/apps"
    __url__ = "/kubernetes/applications"


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
    reason: str = None


class ClusterKind(Enum):
    MAGNUM = auto()


class Cluster(Serializable):
    name: str
    user: str
    kind: ClusterKind
    kubeconfig: dict = None
    uid: str
    status: ClusterStatus

    __identity__ = ("user", "name")
    __discriminator__ = "kind"
    __namespace__ = "/k8s/clusters"
    __url__ = "/kubernetes/clusters"


class MagnumCluster(Cluster):
    kind: ClusterKind = ClusterKind.MAGNUM
    master_ip: str
