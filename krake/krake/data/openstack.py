from dataclasses import field
from enum import Enum, auto
from typing import List, Dict

from . import persistent
from .serializable import PolymorphicContainer, Serializable, ApiObject
from .core import Metadata, ListMetadata, Status, ResourceRef, MetricRef, Reason
from .constraints import LabelConstraint


class AuthMethod(PolymorphicContainer):
    """Container for the different authentication strategies of OpenStack
    Identity service (Keystone).
    """


class UserReference(Serializable):
    """Reference to the OpenStack user that is used by the :class:`Password`
    authentication strategy.

    Attributes:
        id (str): UUID of the OpenStack user
        password (str): Password of the OpenStack user
        comment (str, optional): Arbitrary string for user-defined
            information, e.g. semantic names

    """

    id: str
    password: str
    comment: str = None


class ProjectReference(Serializable):
    """Reference to the OpenStack project that is used by the :class:`Password`
    authentication strategy.

    Attributes:
        id (str): UUID of the OpenStack project
        comment (str, optional): Arbitrary string for user-defined
            information, e.g. semantic names

    """

    id: str
    comment: str = None


@AuthMethod.register("password")
class Password(Serializable):
    """Data for the password authentication strategy of the OpenStack
    identity service (Keystone).

    Attributes:
        user (UserReference): OpenStack user that will used for authentication
        project (ProjectReference): OpenStack project that will be used by Krake

    """

    user: UserReference
    project: ProjectReference


@AuthMethod.register("application_credential")
class ApplicationCredential(Serializable):
    """Data for the application credential authentication strategy of the
    OpenStack identity service (Keystone).

    Attributes:
        id (str): UUID of the OpenStack application crendetial resource
        secret (str): Secret of the application credential

    """

    id: str
    secret: str


class ProjectSpec(Serializable):
    """Specification of OpenStack projects

    Attributes:
        url (str): URL to OpenStack identity service (Keystone)
        auth (AuthMethod): Authentication method for this project
        template (str): UUID of OpenStack Magnum cluster template

    """

    url: str
    auth: AuthMethod
    template: str
    metrics: List[MetricRef] = field(default_factory=list)


class ProjectState(Enum):
    ONLINE = auto()
    FAILING_METRICS = auto()


class ProjectStatus(Serializable):
    """Status subresource of :class:`Project`.

    Attributes:
        state (ProjectState): Current state of the project.
        metrics_reasons (dict[str, Reason]): mapping of the name of the metrics for
            which an error occurred to the reason for which it occurred.

    """

    state: ProjectState = ProjectState.ONLINE
    metrics_reasons: Dict[str, Reason] = field(default_factory=dict)


@persistent("/openstack/projects/{namespace}/{name}")
class Project(ApiObject):
    api: str = "openstack"
    kind: str = "Project"
    metadata: Metadata
    spec: ProjectSpec
    status: ProjectStatus = field(metadata={"subresource": True})


class ProjectList(ApiObject):
    api: str = "openstack"
    kind: str = "ProjectList"
    metadata: ListMetadata
    items: List[Project]


class ProjectConstraints(Serializable):
    """Constraints for the :class:`Project` to which this cluster is
    scheduled.
    """

    labels: List[LabelConstraint] = None


class Constraints(Serializable):
    """Constraints restricting the scheduling decision for a
    :class:`MagnumCluster`.
    """

    project: ProjectConstraints = None


class MagnumClusterSpec(Serializable):
    """Specification of OpenStack Magnum clusters.

    Attributes:
        master_count (int, optional): Number of master nodes
        node_count (int, optional): Number of worker nodes
        metrics (List[MetricRef]): Metrics describing the state of the Magnum
            cluster.

    """

    master_count: int = field(default=None, metadata={"immutable": True})
    node_count: int = None
    metrics: List[MetricRef] = field(default_factory=list)
    constraints: Constraints = None


class MagnumClusterState(Enum):
    PENDING = auto()
    CREATING = auto()
    RUNNING = auto()
    RECONCILING = auto()
    DELETING = auto()
    FAILED = auto()


class MagnumClusterStatus(Status):
    """Status of a OpenStack Magnum cluster

    Attributes:
        state (MagnumClusterState): State of the cluster
        project (.core.ResourceRef): OpenStack project which hosts this
            Magnum cluster.
        template (str): UUID of the OpenStack Magnum cluster template that
            is used to create the cluster.
        cluster_id (str): UUID of the cluster inside the OpenStack
            Magnum service.
        node_count (int, optional): Current number of worker nodes
        api_address (str): URL to access the API of the cluster
        master_addresses (List[str]): IP addresses of the master nodes
        node_addresses (List[str]): IP addresses of the worker nodes
        cluster (.core.ResourceRef): Kubernetes cluster resource created
            for this Magnum cluster.

    """

    state: MagnumClusterState = MagnumClusterState.PENDING
    project: ResourceRef = None
    template: str = field(default=None, metadata={"immutable": True})
    cluster_id: str = None
    node_count: int = None
    api_address: str = None
    master_addresses: List[str] = None
    node_addresses: List[str] = None
    cluster: ResourceRef = None


@persistent("/openstack/magnumclusters/{namespace}/{name}")
class MagnumCluster(ApiObject):
    api: str = "openstack"
    kind: str = "MagnumCluster"
    metadata: Metadata
    spec: MagnumClusterSpec
    status: MagnumClusterStatus = field(metadata={"subresource": True})


class MagnumClusterList(ApiObject):
    api: str = "openstack"
    kind: str = "MagnumClusterList"
    metadata: ListMetadata
    items: List[MagnumCluster]


class MagnumClusterBinding(ApiObject):
    """Binding object for Magnum clusters.

    This resource is used to assign a :class:`Project` to
    :attr:`MagnumCluster.status.project`.

    Attributes:
        project (.core.ResourceRef): Reference to the :class:`Project` to which
            the Magnum cluster will be bound
        template (str): UUID of the Magnum cluster template that should be used
            to create the cluster

    """

    api: str = "openstack"
    kind: str = "MagnumClusterBinding"
    project: ResourceRef
    template: str
