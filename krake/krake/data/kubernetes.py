from enum import Enum, auto
from datetime import datetime

from .serializable import Serializable


class ApplicationState(Enum):
    CREATED = auto()
    UPDATED = auto()
    SCHEDULED = auto()
    RUNNING = auto()
    DELETED = auto()
    FAILED = auto()


class ApplicationStatus(Serializable):
    state: ApplicationState
    created: datetime
    modified: datetime
    reason: str = None
    cluster: str = None  # ID of associated Cluster


class Application(Serializable):
    id: str
    status: ApplicationStatus
    user_id: str
    manifest: str

    __identity__ = "id"
    __namespace__ = "/k8s/apps"
    __url__ = "/kubernetes/applications"


class ClusterState(Enum):
    CREATING = auto()
    RUNNING = auto()
    FAILED = auto()


class ClusterStatus(Serializable):
    state: ClusterState
    created: datetime
    reason: str = None


class ClusterKind(Enum):
    MAGNUM = auto()


class Cluster(Serializable):
    id: str
    status: ClusterStatus
    kind: ClusterKind

    __identity__ = "id"
    __discriminator__ = "kind"
    __namespace__ = "/k8s/clusters"
    __url__ = "/kubernetes/clusters"


class MagnumCluster(Cluster):
    kind: ClusterKind = ClusterKind.MAGNUM
    master_ip: str
