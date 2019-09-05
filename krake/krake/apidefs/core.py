from krake.data.core import (
    Role,
    RoleList,
    RoleBinding,
    RoleBindingList,
    Metric,
    MetricsProvider,
    MetricsProviderList,
    MetricList,
)
from .definitions import ApiDef, Scope, operation, ListQuery


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
    class List(ListQuery):
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
    class List(ListQuery):
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


@core.resource
class MetricResource:
    singular = "Metric"
    plural = "Metrics"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/metric"
        body = Metric
        response = Metric

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/metric"
        response = MetricList

    @operation
    class Read:
        method = "GET"
        path = "/core/metric/{name}"
        response = Metric

    @operation
    class Update:
        method = "PUT"
        path = "/core/metric/{name}"
        body = Metric
        response = Metric

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/metric/{name}"
        response = Metric


@core.resource
class MetricsProviderResource:
    singular = "MetricsProvider"
    plural = "MetricsProviders"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/core/metricsprovider"
        body = MetricsProvider
        response = MetricsProvider

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/metricsprovider"
        response = MetricsProviderList

    @operation
    class Read:
        method = "GET"
        path = "/core/metricsprovider/{name}"
        response = MetricsProvider

    @operation
    class Update:
        method = "PUT"
        path = "/core/metricsprovider/{name}"
        body = MetricsProvider
        response = MetricsProvider

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/metricsprovider/{name}"
        response = MetricsProvider
