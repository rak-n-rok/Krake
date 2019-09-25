from enum import Enum, auto
from datetime import datetime
from dataclasses import field
from typing import List

from . import persistent
from .serializable import Serializable, ApiObject


class ResourceRef(Serializable):
    api: str
    namespace: str
    kind: str
    name: str


class Metadata(Serializable):
    name: str = field(metadata={"immutable": True})
    namespace: str = field(default=None, metadata={"immutable": True})
    labels: List[dict] = field(default_factory=list)
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


class ReasonCode(Enum):
    INTERNAL_ERROR = 1  # Default error

    INVALID_RESOURCE = 10  # Invalid values in the Manifest
    CLUSTER_NOT_REACHABLE = 11  # Connectivity issue with the Kubernetes deployment
    NO_SUITABLE_RESOURCE = 50  # Scheduler issue
    MISSING_METRIC_DEFINITION = 51  # Scheduler issue
    INVALID_METRIC_VALUE = 52  # Scheduler issue

    # Codes over 100 will cause the controller to delete the resource directly
    RESOURCE_NOT_DELETED = 100


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
    kind: str = "ApiObject"
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


class MetricProviderType(Enum):

    prometheus = auto()


class MetricSpecProvider(Serializable):
    name: str
    metric: str


class MetricSpec(Serializable):
    value: float = None
    min: float
    max: float
    weight: float
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


class MetricProviderConfig(Serializable):
    url: str
    metrics: List[str]


class MetricsProviderSpec(Serializable):
    type: MetricProviderType
    config: MetricProviderConfig


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
