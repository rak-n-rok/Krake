from enum import Enum, auto
from datetime import datetime
from typing import List

from krake.api.database import Key
from .serializable import Serializable


class NamespacedMetadata(Serializable):
    name: str
    namespace: str
    user: str
    uid: str


class SystemMetadata(Serializable):
    name: str
    uid: str


class Verb(Enum):
    create = auto()
    list = auto()
    get = auto()
    update = auto()
    delete = auto()


class RoleRule(Serializable):
    resources: List[str]
    namespaces: List[str]
    verbs: List[Verb]


class RoleStatus(Serializable):
    created: datetime
    modified: datetime


class Role(Serializable):
    metadata: SystemMetadata
    status: RoleStatus
    rules: List[RoleRule]

    __metadata__ = {"key": Key("/roles/{name}", attribute="metadata")}


class RoleBindingStatus(Serializable):
    created: datetime
    modified: datetime


class RoleBinding(Serializable):
    metadata: SystemMetadata
    status: RoleBindingStatus
    users: List[str]
    roles: List[str]

    __metadata__ = {"key": Key("/rolebindings/{name}", attribute="metadata")}
