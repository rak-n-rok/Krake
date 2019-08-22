from krake.data.core import Role, RoleList, RoleBinding, RoleBindingList
from .definitions import ApiDef, Scope, operation


core = ApiDef("core")


@core.resource
class RoleResource:
    singular = "Role"
    plural = "Roles"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/roles"
        body = Role
        response = Role

    @operation
    class List:
        number = "plural"
        method = "GET"
        path = "/core/roles"
        response = RoleList

    @operation
    class Read:
        method = "GET"
        path = "/core/roles/{name}"
        response = Role

    @operation
    class Update:
        method = "PUT"
        path = "/core/roles/{name}"
        body = Role
        response = Role

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/roles/{name}"
        response = Role


@core.resource
class RoleBindingResource:
    singular = "RoleBinding"
    plural = "RoleBindings"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/rolebindings"
        body = RoleBinding
        response = RoleBinding

    @operation
    class List:
        number = "plural"
        method = "GET"
        path = "/core/rolebindings"
        response = RoleBindingList

    @operation
    class Read:
        method = "GET"
        path = "/core/rolebindings/{name}"
        response = RoleBinding

    @operation
    class Update:
        method = "PUT"
        path = "/core/rolebindings/{name}"
        body = RoleBinding
        response = RoleBinding

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/rolebindings/{name}"
        response = RoleBinding
