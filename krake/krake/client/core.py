"""This module implements the core API resources for the Krake Python API
client.
"""
from krake.data import Key
from krake.data.core import Role, RoleBinding
from .resource import Resource


class CoreAPI(object):
    """API summarizing all core resources.

    Attributes:
        role (RoleResource): Resource for managing
            :class:`krake.data.core.Role` objects
        role_binding (RoleBindingResource): Resource for managing
            :class:`krake.data.core.RoleBinding` objects
    """

    def __init__(self, session, url):
        self.role = RoleResource(session, url)
        self.role_binding = RoleBindingResource(session, url)


class RoleResource(Resource):
    """Resource for managing :class:`krake.data.core.Role` objects."""

    model = Role
    endpoints = {
        "list": Key("/core/roles"),
        "create": Key("/core/roles"),
        "get": Key("/core/roles/{name}"),
    }


class RoleBindingResource(Resource):
    """Resource for managing :class:`krake.data.core.RoleBinding` objects."""

    model = RoleBinding
    endpoints = {
        "list": Key("/core/rolebindings"),
        "create": Key("/core/rolebindings"),
        "get": Key("/core/rolebindings/{name}"),
    }
