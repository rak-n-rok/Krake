"""Core of the declarative REST API definition API"""
from inspect import getmembers
from dataclasses import fields
from enum import Enum, auto


class ApiDef(object):
    def __init__(self, name):
        self.name = name
        self.resources = []

    def resource(self, resource):
        self.resources.append(resource)
        return resource


def is_subresource(member):
    return isinstance(member, type) and issubclass(member, Subresource)


def find_subresources(cls):
    # Find dataclass fields marked as "subresource" and create corresponding
    # Subresource objects.
    subresources = {
        field.name: Subresource(field.type)
        for field in fields(cls.definition)
        if field.metadata.get("subresource", False)
    }

    # Load subresource attributes directory from the resource object
    subresources.update(getmembers(cls, is_subresource))

    return subresources


class Scope(Enum):
    NONE = auto()
    NAMESPACED = auto()


class Resource(object):
    def __init_subclass__(cls):
        operation_names = ["Create", "Read", "Update", "Delete"]
        cls.operations = {
            name: getattr(cls, name) for name in operation_names if hasattr(cls, name)
        }
        cls.subresources = dict(getmembers(cls, is_subresource))


class Operation(object):
    query = None
    body = None
    response = None


class Subresource(object):
    def __init_subclass__(cls):
        operation_names = ["Read", "Update"]
        cls.operations = {
            name: getattr(cls, name) for name in operation_names if hasattr(cls, name)
        }
