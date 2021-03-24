import re
from enum import Enum, IntEnum, auto
from datetime import datetime
from dataclasses import field
from typing import List, Dict

from marshmallow import ValidationError

from . import persistent
from .serializable import Serializable, ApiObject, PolymorphicContainer


class ResourceRef(Serializable):
    api: str
    namespace: str = field(default=None)
    kind: str
    name: str

    def __hash__(self):
        return hash((self.api, self.namespace, self.kind, self.name))

    def __repr__(self):
        message = f"{self.kind}(api='{self.api}', "
        return message + f"namespace='{self.namespace}', name='{self.name}')"


_label_key_pattern = None
_label_value_pattern = None

_label_key_regex = None
_label_value_regex = None


def _get_labels_regex():
    """Build or return the regular expressions that are used to validate the key and
    value of the labels of the Krake resources.

    The first call builds the expressions, while a second returns the already built
    ones.

    Returns:
        (re.Pattern, re.Pattern): a tuple that contains the compiled regular,
            expressions, the first element to validate the key and the second to
            validate the value.

    """
    global _label_key_pattern, _label_value_pattern
    global _label_key_regex, _label_value_regex

    if _label_key_regex and _label_value_regex:
        return _label_key_regex, _label_value_regex

    # Build the patterns only if not already built
    max_prefix_size = 253
    max_key_size = 63
    max_value_size = max_key_size

    # First and last characters must be alphanumeric. The rest of the string must be
    # alphanumeric, "-", "_" or "."
    base_alphanumeric_pattern = "\\w|(\\w[\\w\\-_.]{{0,{length}}}\\w)"

    key_pattern = base_alphanumeric_pattern.format(length=max_key_size - 2)
    value_pattern = base_alphanumeric_pattern.format(length=max_value_size - 2)
    prefix_pattern = base_alphanumeric_pattern.format(length=max_prefix_size - 2)

    # The key can be a string of length 63 with the specifications described above,
    # or have a prefix, then one "/" character, then the string of length 63 (called
    # name).
    # The prefix itself should have a max length of 253, but otherwise follows the
    # specifications described above.
    _label_key_pattern = f"^(({prefix_pattern})\\/)?({key_pattern})$"

    # The value can be a string of length 63 with the specifications described
    # above.
    _label_value_pattern = value_pattern

    _label_key_regex = re.compile(_label_key_pattern, re.ASCII)
    _label_value_regex = re.compile(_label_value_pattern, re.ASCII)

    return _label_key_regex, _label_value_regex


def validate_key(key):
    """Validate the given key against the corresponding regular expression.

    Args:
        key: the string to validate

    Raises:
        ValidationError: if the given key is not conform to the regular expression.

    """
    key_regex, _ = _get_labels_regex()
    if not key_regex.fullmatch(key):
        raise ValidationError(
            f"Label key {key!r} does not match the regex {_label_key_pattern!r}."
        )


def validate_value(value):
    """Validate the given value against the corresponding regular expression.

    Args:
        value: the string to validate

    Raises:
        ValidationError: if the given value is not conform to the regular expression.

    """
    _, value_regex = _get_labels_regex()
    if not value_regex.fullmatch(value):
        raise ValidationError(
            f"Label value {value!r} does not match"
            f" the regex {_label_value_pattern!r}."
        )


def _validate_labels(labels):
    """Check that keys and values in the given labels match against their corresponding
    regular expressions.

    Args:
        labels (dict): the different labels to validate.

    Raises:
        ValidationError: if any of the keys and labels does not match their respective
            regular expression.

    """
    for key, value in labels.items():
        validate_key(key)
        validate_value(value)


class Metadata(Serializable):
    name: str = field(metadata={"immutable": True})
    namespace: str = field(default=None, metadata={"immutable": True})
    labels: dict = field(default_factory=dict, metadata={"validate": _validate_labels})
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

    KUBERNETES_ERROR = 60

    CREATE_FAILED = 70
    RECONCILE_FAILED = 71
    DELETE_FAILED = 72

    OPENSTACK_ERROR = 80
    INVALID_CLUSTER_TEMPLATE = 81

    # Related to Metrics and Metric Provider
    INVALID_METRIC = 91
    UNREACHABLE_METRICS_PROVIDER = 92
    UNKNOWN_METRIC = 93
    UNKNOWN_METRICS_PROVIDER = 94


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


@persistent("/core/roles/{name}")
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


@persistent("/core/rolebindings/{name}")
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


@persistent("/core/metric/{name}")
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


@MetricsProviderSpec.register("kafka")
class KafkaSpec(Serializable):
    """Specifications to connect to a KSQL database, and retrieve a specific row from a
    specific table.

    Attributes:
        comparison_column (str): name of the column where the value will be compared to
            the metric name, to select the right metric.
        value_column (str): name of the column where the value of a metric is stored.
        table (str): the name of the KSQL table where the metric is defined.
        url (str): endpoint of the KSQL database.

    """

    comparison_column: str
    value_column: str
    table: str
    url: str


@MetricsProviderSpec.register("static")
class StaticSpec(Serializable):
    metrics: Dict[str, float]


@persistent("/core/metricsprovider/{name}")
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


class MetricRef(Serializable):
    name: str
    weight: float
