from krake.api.helpers import ListQuery
from krake.data.core import (
    GlobalMetric,
    GlobalMetricList,
    GlobalMetricsProvider,
    GlobalMetricsProviderList,
    Role,
    RoleList,
    RoleBinding,
    RoleBindingList,
)
from .definitions import ApiDef, Scope, operation


core = ApiDef("core")


@core.resource
class GlobalMetricResource:
    singular = "GlobalMetric"
    plural = "GlobalMetrics"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/globalmetrics"
        body = GlobalMetric
        response = GlobalMetric

    @operation
    class Read:
        method = "GET"
        path = "/core/globalmetrics/{name}"
        response = GlobalMetric

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/globalmetrics"
        response = GlobalMetricList

    @operation
    class Update:
        method = "PUT"
        path = "/core/globalmetrics/{name}"
        body = GlobalMetric
        response = GlobalMetric

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/globalmetrics/{name}"
        response = GlobalMetric


@core.resource
class GlobalMetricsProviderResource:
    singular = "GlobalMetricsProvider"
    plural = "GlobalMetricsProviders"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/globalmetricsproviders"
        body = GlobalMetricsProvider
        response = GlobalMetricsProvider

    @operation
    class Read:
        method = "GET"
        path = "/core/globalmetricsproviders/{name}"
        response = GlobalMetricsProvider

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/globalmetricsproviders"
        response = GlobalMetricsProviderList

    @operation
    class Update:
        method = "PUT"
        path = "/core/globalmetricsproviders/{name}"
        body = GlobalMetricsProvider
        response = GlobalMetricsProvider

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/globalmetricsproviders/{name}"
        response = GlobalMetricsProvider


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
    class Read:
        method = "GET"
        path = "/core/roles/{name}"
        response = Role

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/roles"
        response = RoleList

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
    class Read:
        method = "GET"
        path = "/core/rolebindings/{name}"
        response = RoleBinding

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/rolebindings"
        response = RoleBindingList

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
