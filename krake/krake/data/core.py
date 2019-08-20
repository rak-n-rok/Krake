from enum import Enum, auto
from datetime import datetime
from typing import List

from . import Key
from .serializable import Serializable


class NamespacedMetadata(Serializable):
    name: str
    namespace: str
    user: str
    uid: str


class CoreMetadata(Serializable):
    name: str
    uid: str


class ClientMetadata(Serializable):
    name: str


class Verb(Enum):
    create = auto()
    list = auto()
    get = auto()
    update = auto()
    delete = auto()


class RoleRule(Serializable):
    api: str
    resources: List[str]
    namespaces: List[str]
    verbs: List[Verb]


class RoleStatus(Serializable):
    created: datetime
    modified: datetime


class Role(Serializable):
    metadata: CoreMetadata
    status: RoleStatus
    rules: List[RoleRule]

    __metadata__ = {"key": Key("/roles/{name}", attribute="metadata")}


class RoleBindingStatus(Serializable):
    created: datetime
    modified: datetime


class RoleBinding(Serializable):
    metadata: CoreMetadata
    status: RoleBindingStatus
    users: List[str]
    roles: List[str]

    __metadata__ = {"key": Key("/rolebindings/{name}", attribute="metadata")}


class ResourceRef(Serializable):
    api: str
    namespace: str
    kind: str
    name: str


class Conflict(Serializable):
    source: ResourceRef
    conflicting: List[ResourceRef]


def resource_ref(resource):
    """Create a ResourceRef from a Serializable

    Args:
        resource (Serializable): a Serializable with a "metadata" attribute

    Returns:
        ResourceRef: The corresponding reference to the Serializable

    Raises:
        ValueError: if the Serializable has no "metadata" attribute
    """
    if not getattr(resource, "metadata"):
        raise ValueError(f"The Resource {resource!r} cannot be referenced.")

    return ResourceRef(
        api=resource.__module__.split(".")[-1],
        namespace=resource.metadata.namespace,
        kind=resource.__class__.__name__.lower(),
        name=resource.metadata.name,
    )
