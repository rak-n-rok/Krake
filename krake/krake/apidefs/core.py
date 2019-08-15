from krake.data.core import Role, RoleList, RoleBinding, RoleBindingList
from .definitions import ApiDef, Resource, Operation, Scope


core = ApiDef("core")


@core.resource
class RoleResource(Resource):
    singular = "Role"
    plural = "Roles"
    scope = Scope.NONE

    class Create(Operation):
        method = "POST"
        path = "/core/roles"
        body = Role
        response = Role

    class List(Operation):
        method = "GET"
        path = "/core/roles"
        response = RoleList

    class Read(Operation):
        method = "GET"
        path = "/core/roles/{name}"
        response = Role

    class Update(Operation):
        method = "PUT"
        path = "/core/roles/{name}"
        body = Role
        response = Role

    class Delete(Operation):
        method = "DELETE"
        path = "/core/roles/{name}"
        response = Role


@core.resource
class RoleBindingResource(Resource):
    singular = "RoleBinding"
    plural = "RoleBindings"
    scope = Scope.NONE

    class Create(Operation):
        method = "POST"
        path = "/core/rolebindings"
        body = RoleBinding
        response = RoleBinding

    class List(Operation):
        method = "GET"
        path = "/core/rolebindings"
        response = RoleBindingList

    class Read(Operation):
        method = "GET"
        path = "/core/rolebindings/{name}"
        response = RoleBinding

    class Update(Operation):
        method = "PUT"
        path = "/core/rolebindings/{name}"
        body = RoleBinding
        response = RoleBinding

    class Delete(Operation):
        method = "DELETE"
        path = "/core/rolebindings/{name}"
        response = RoleBinding
