from dataclasses import field
from enum import Enum, auto
from typing import List

from . import persistent
from .serializable import PolymorphicContainer, Serializable, ApiObject
from .core import Metadata, ListMetadata, Status, ResourceRef


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
    url: str
    auth: AuthMethod


@persistent("/openstack/projects/{namespace}/{name}")
class Project(ApiObject):
    api: str = "openstack"
    kind: str = "Project"
    metadata: Metadata
    spec: ProjectSpec


class ProjectList(ApiObject):
    api: str = "openstack"
    kind: str = "ProjectList"
    metadata: ListMetadata
    items: List[Project]


class MagnumClusterSpec(Serializable):
    template: str = field(metadata={"immutable": True})
    master_count: int = field(default=None, metadata={"immutable": True})
    node_count: int = None


class MagnumClusterState(Enum):
    PENDING = auto()
    CREATING = auto()
    RUNNING = auto()
    RECONCILING = auto()
    DELETING = auto()
    FAILED = auto()


class MagnumClusterStatus(Status):
    state: MagnumClusterState = MagnumClusterState.PENDING
    project: ResourceRef = None
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
    kind: str = "ProjectList"
    metadata: ListMetadata
    items: List[MagnumCluster]
