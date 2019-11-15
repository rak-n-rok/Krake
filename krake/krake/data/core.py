from enum import Enum, IntEnum, auto
from datetime import datetime
from dataclasses import field
from typing import List, Dict

from . import persistent
from .serializable import Serializable, ApiObject, PolymorphicContainer


class ResourceRef(Serializable):
    api: str
    namespace: str
    kind: str
    name: str

    def __hash__(self):
        return hash((self.api, self.namespace, self.kind, self.name))

    def __repr__(self):
        message = f"{self.kind}(api='{self.api}', "
        return message + f"namespace='{self.namespace}', name='{self.name}')"


class Metadata(Serializable):
    name: str = field(metadata={"immutable": True})
    namespace: str = field(default=None, metadata={"immutable": True})
    labels: dict = field(default_factory=dict)
    finalizers: List[str] = field(default_factory=list)

    uid: str = field(metadata={"readonly": True})
    created: datetime = field(metadata={"readonly": True})
    modified: datetime = field(metadata={"readonly": True})
    deleted: datetime = field(default=None, metadata={"readonly": True})

    owners: List[ResourceRef] = field(default_factory=list)


class CoreMetadata(Serializable):
    name: str
    uid: str


class ListMetadata(Serializable):
    pass  # TODO


class ReasonCode(IntEnum):
    INTERNAL_ERROR = 1  # Default error

    INVALID_RESOURCE = 10  # Invalid values in the Manifest
    CLUSTER_NOT_REACHABLE = 11  # Connectivity issue with the Kubernetes deployment
    NO_SUITABLE_RESOURCE = 50  # Scheduler issue

    # Codes over 100 will cause the controller to delete the resource directly
    WILL_DELETE_RESOURCE = 100

    DELETE_FAILED = 100


class Reason(Serializable):
    code: ReasonCode
    message: str


class WatchEventType(Enum):
    ADDED = auto()
    MODIFIED = auto()
    DELETED = auto()


class Status(Serializable):
    reason: Reason = None


class WatchEvent(Serializable):
    type: WatchEventType
    object: dict


class Verb(Enum):
    create = auto()
    list = auto()
    list_all = auto()
    get = auto()
    update = auto()
    delete = auto()


class RoleRule(Serializable):
    api: str
    resources: List[str]
    namespaces: List[str]
    verbs: List[Verb]


@persistent("/roles/{name}")
class Role(ApiObject):
    api: str = "core"
    kind: str = "Role"
    metadata: Metadata
    rules: List[RoleRule]


class RoleList(ApiObject):
    api: str = "core"
    kind: str = "RoleList"
    metadata: ListMetadata
    items: List[Role]


class RoleBindingStatus(Serializable):
    created: datetime
    modified: datetime


@persistent("/rolebindings/{name}")
class RoleBinding(ApiObject):
    api: str = "core"
    kind: str = "RoleBinding"
    metadata: Metadata
    users: List[str]
    roles: List[str]


class RoleBindingList(ApiObject):
    api: str = "core"
    kind: str = "RoleBindingList"
    metadata: ListMetadata
    items: List[RoleBinding]


class Conflict(Serializable):
    source: ResourceRef
    conflicting: List[ResourceRef]


def resource_ref(resource):
    """Create a :class:`ResourceRef` from a :class:`ApiObject`

    Args:
        resource (.serializable.ApiObject): API object that should be
            referenced

    Returns:
        ResourceRef: Corresponding reference to the API object

    """
    return ResourceRef(
        api=resource.api,
        kind=resource.kind,
        namespace=resource.metadata.namespace,
        name=resource.metadata.name,
    )


class MetricSpecProvider(Serializable):
    name: str
    metric: str


class MetricSpec(Serializable):
    min: float
    max: float
    provider: MetricSpecProvider


@persistent("/metric/{name}")
class Metric(ApiObject):
    api: str = "core"
    kind: str = "Metric"
    metadata: Metadata
    spec: MetricSpec


class MetricList(ApiObject):
    api: str = "core"
    kind: str = "MetricList"
    metadata: ListMetadata
    items: List[Metric]


class MetricsProviderSpec(PolymorphicContainer):
    type: str


@MetricsProviderSpec.register("prometheus")
class PrometheusSpec(Serializable):
    url: str


@MetricsProviderSpec.register("static")
class StaticSpec(Serializable):
    metrics: Dict[str, float]


@persistent("/metricsprovider/{name}")
class MetricsProvider(ApiObject):
    api: str = "core"
    kind: str = "MetricsProvider"
    metadata: Metadata
    spec: MetricsProviderSpec


class MetricsProviderList(ApiObject):
    api: str = "core"
    kind: str = "MetricsProviderList"
    metadata: ListMetadata
    items: List[MetricsProvider]
