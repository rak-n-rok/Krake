"""Data model definitions for Kubernetes-related resources"""
from enum import Enum, auto
from dataclasses import field
from typing import List
from datetime import datetime
from marshmallow import ValidationError, fields
from marshmallow.utils import ensure_text_type
from lark import Lark, UnexpectedInput
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.config import ConfigException

from . import persistent
from .serializable import Serializable, ApiObject
from .core import Metadata, ListMetadata, Status, ResourceRef


class LabelConstraint(object):
    """A label constraint is used to filter :class:`.serializable.ApiObject`
    based on their labels.

    A very simple language for expressing label constraints is used. The
    following operations can be expressed:

    equality
        The value of a label must be equal to a specific value::

            <label> is <value>
            <label> = <value>
            <label> == <value>

    non-equality
        The value of a label must not be equal to a specific value::

            <label> is not <value>
            <label> != <value>

    inclusion
        The value of a label must be inside a set of values::

            <label> in (<value>, <value>, ...)

    exclusion
        The value of a label must not be inside a set of values::

            <label> not in (<value>, <value>, ...)

    Args:
        parsed (str, optional): Parsed string expression.

    Example:
        .. code:: python

            labels = {
                "location": "IT"
            }

            constraint = LabelConstraint.parse("location in (DE, UK)")
            constraint.match(labels)  # returns False

    """

    grammar = Lark(
        """
        start: WORD (equal | notequal | in | notin)

        equal: ("==" | "=" | "is") WORD

        notequal: ("!=" | "is" "not") WORD

        in: "in" "(" (WORD ",")* WORD* ")"

        notin: "not" "in" "(" (WORD ",")* WORD* ")"

        %ignore " "
        %ignore "\t"
        %import common.WORD
        """
    )

    def __init__(self, parsed=None):
        self.parsed = parsed

    def __eq__(self, other):
        if isinstance(other, LabelConstraint):
            # If other is also a label constraint but from a different
            # subclass, the constraints are not equal.
            if not isinstance(other, self.__class__):
                return False
        else:
            # Comparison with other types is not implemented
            return NotImplemented

        return self._as_tuple() == other._as_tuple()

    def __hash__(self, other):
        return hash(self._as_tuple())

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.__str__()}>"

    def expression(self):
        """Returns an expression representing the constraint.

        Returns:
            str: String expression of the constraint

        """
        raise NotImplementedError()

    @classmethod
    def parse(cls, expression):
        """Parse a constraint expression into its Python representation.

        Args:
            expression (str): Constraint expression

        Returns:
            LabelConstraint: An instance of the constraint class representing
            the parsed expression.

        """
        tree = cls.grammar.parse(expression)
        label = tree.children[0]
        operation = tree.children[1].data

        if operation == "equal":
            value = str(tree.children[1].children[0])
            return EqualConstraint(label, value, parsed=expression)
        elif operation == "notequal":
            value = str(tree.children[1].children[0])
            return NotEqualConstraint(label, value, parsed=expression)
        elif operation == "in":
            values = map(str, tree.children[1].children)
            return InConstraint(label, values, parsed=expression)
        elif operation == "notin":
            values = map(str, tree.children[1].children)
            return NotInConstraint(label, values, parsed=expression)
        else:
            raise ValueError(f"Unknown operation {operation!r}")

    def match(self, labels):
        """Match the constraint against a set label mapping.

        Args:
            labels (dict): Mapping of labels

        Returns:
            bool: :data:`True` of the passed labels fulfill the constraint,
            otherwise :data:`False`.

        """
        raise NotImplementedError()

    def _as_tuple(self):
        """Returns a tuple representation of the constraint.

        This tuple is used by the :meth:`__eq__` and :meth:`__hash__` methods.
        This makes constraints hashable and comparable across each other.

        Returns:
            tuple: Tuple representing the constraint
        """
        raise NotImplementedError()

    class Field(fields.Field):
        """Serializer for :class:`LabelConstraint`.

        Constraints are represented as string expressions. This field parses
        the expressions on deserialization and returns the string
        representation on serialization.
        """

        def _deserialize(self, value, attr, obj, **kwargs):
            if value is None:
                return None

            expression = ensure_text_type(value)
            try:
                return LabelConstraint.parse(expression)
            except UnexpectedInput:
                raise ValidationError("Invalid label constraint")

        def _serialize(self, value, attr, data, **kwargs):
            if not isinstance(value, LabelConstraint):
                raise self.make_error("invalid")

            if value.parsed is None:
                return str(value)

            try:
                return ensure_text_type(value.parsed)
            except UnicodeDecodeError as error:
                raise self.make_error("invalid_utf8") from error


class EqualConstraint(LabelConstraint):
    """Label constraint where the value of a label needs to match a specific
    value.

    Example:
        .. code:: python

            # The following constraints are equivalent
            LabelConstraint.parse("location is EU")
            LabelConstraint.parse("location = EU")
            LabelConstraint.parse("location == EU")

    """

    def __init__(self, label, value, parsed=None):
        super().__init__(parsed)
        self.label = label
        self.value = value

    def __str__(self):
        return f"{self.label} is {self.value}"

    def _as_tuple(self):
        return (self.label, self.value)

    def match(self, labels):
        try:
            return labels[self.label] == self.value
        except KeyError:
            return False


class NotEqualConstraint(EqualConstraint):
    """Label constraint where the value of a label must not match a specific
    value.

    Example:
        .. code:: python

            # The following constraints are equivalent
            LabelConstraint.parse("location is not UK")
            LabelConstraint.parse("location != UK")

    """

    def __str__(self):
        return f"{self.label} is not {self.value}"

    def match(self, labels):
        try:
            return labels[self.label] != self.value
        except KeyError:
            return False


class InConstraint(LabelConstraint):
    """Label constraint where the value of a label must be in a set of
    values.

    Example:
        .. code:: python

            LabelConstraint.parse("location in (DE, SK)")

    """

    def __init__(self, label, values, parsed=None):
        super().__init__(parsed)
        self.label = label
        self.values = tuple(values)

    def __str__(self):
        return f"{self.label} in ({', '.join(self.values)})"

    def _as_tuple(self):
        return (self.label, self.values)

    def match(self, labels):
        try:
            return labels[self.label] in self.values
        except KeyError:
            return False


class NotInConstraint(InConstraint):
    """Label constraint where the value of a label must not be in a set of
    values.

    Example:
        .. code:: python

            LabelConstraint.parse("location not in (DE, SK)")

    """

    def __str__(self):
        return f"{self.label} not in ({', '.join(self.values)})"

    def match(self, labels):
        try:
            return labels[self.label] not in self.values
        except KeyError:
            return False


class ClusterConstraints(Serializable):
    labels: List[LabelConstraint] = None


class Constraints(Serializable):
    cluster: ClusterConstraints = None


class ApplicationSpec(Serializable):
    manifest: List[dict]
    constraints: Constraints = None


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

    """

    state: ApplicationState = ApplicationState.PENDING
    scheduled: datetime = None
    scheduled_to: ResourceRef = None
    running_on: ResourceRef = None
    services: dict = field(default_factory=dict)
    manifest: List[dict] = None


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


class ClusterMetricRef(Serializable):
    name: str
    weight: float


class ClusterSpec(Serializable):
    kubeconfig: dict = field(metadata={"validate": _validate_kubeconfig})
    # FIXME needs further discussion how to register stand-alone kubernetes cluster as
    #  a cluster which should be processed by krake.controller.scheduler
    metrics: List[ClusterMetricRef] = field(default_factory=list)


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
