from krake.api.helpers import ListQuery
from krake.data.core import (
    Metric,
    MetricList,
    MetricsProvider,
    MetricsProviderList,
    Role,
    RoleList,
    RoleBinding,
    RoleBindingList,
)
from .definitions import ApiDef, Scope, operation


core = ApiDef("core")


@core.resource
class MetricResource:
    singular = "Metric"
    plural = "Metrics"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/metrics"
        body = Metric
        response = Metric

    @operation
    class Read:
        method = "GET"
        path = "/core/metrics/{name}"
        response = Metric

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/metrics"
        response = MetricList

    @operation
    class Update:
        method = "PUT"
        path = "/core/metrics/{name}"
        body = Metric
        response = Metric

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/metrics/{name}"
        response = Metric


@core.resource
class MetricsProviderResource:
    singular = "MetricsProvider"
    plural = "MetricsProviders"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/metricsproviders"
        body = MetricsProvider
        response = MetricsProvider

    @operation
    class Read:
        method = "GET"
        path = "/core/metricsproviders/{name}"
        response = MetricsProvider

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/metricsproviders"
        response = MetricsProviderList

    @operation
    class Update:
        method = "PUT"
        path = "/core/metricsproviders/{name}"
        body = MetricsProvider
        response = MetricsProvider

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/metricsproviders/{name}"
        response = MetricsProvider


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
