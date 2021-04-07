from krake.api.helpers import ListQuery
from krake.data.core import (
    Role,
    RoleList,
    RoleBinding,
    RoleBindingList,
    GlobalMetric,
    GlobalMetricsProvider,
    GlobalMetricsProviderList,
    GlobalMetricList,
    Metric,
    MetricsProvider,
    MetricsProviderList,
    MetricList,
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


@core.resource
class MetricResource:
    singular = "Metric"
    plural = "Metrics"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/core/namespaces/{namespace}/metrics"
        body = Metric
        response = Metric

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/namespaces/{namespace}/metrics"
        response = MetricList

    @operation
    class ListAll(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/metrics"
        response = MetricList

    @operation
    class Read:
        method = "GET"
        path = "/core/namespaces/{namespace}/metrics/{name}"
        response = Metric

    @operation
    class Update:
        method = "PUT"
        path = "/core/namespaces/{namespace}/metrics/{name}"
        body = Metric
        response = Metric

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/namespaces/{namespace}/metrics/{name}"
        response = Metric


@core.resource
class MetricsProviderResource:
    singular = "MetricsProvider"
    plural = "MetricsProviders"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/core/namespaces/{namespace}/metricsproviders"
        body = MetricsProvider
        response = MetricsProvider

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/namespaces/{namespace}/metricsproviders"
        response = MetricsProviderList

    @operation
    class ListAll(ListQuery):
        number = "plural"
        method = "GET"
        path = "/core/metricsproviders"
        response = MetricsProviderList

    @operation
    class Read:
        method = "GET"
        path = "/core/namespaces/{namespace}/metricsproviders/{name}"
        response = MetricsProvider

    @operation
    class Update:
        method = "PUT"
        path = "/core/namespaces/{namespace}/metricsproviders/{name}"
        body = MetricsProvider
        response = MetricsProvider

    @operation
    class Delete:
        method = "DELETE"
        path = "/core/namespaces/{namespace}/metricsproviders/{name}"
        response = MetricsProvider
