import logging
from aiohttp import web
from webargs.aiohttpparser import use_kwargs
from krake.api.auth import protected
from krake.api.helpers import (
    load,
    use_schema,
    make_create_request_schema,
    ListQuery,
)
from krake.api.base import (
    list_or_watch_resources_async,
    must_create_resource_async,
    delete_resource_async,
    update_resource_async,
)
from krake.data.core import (
    GlobalMetric,
    GlobalMetricList,
    GlobalMetricsProvider,
    GlobalMetricsProviderList,
    Metric,
    MetricList,
    MetricsProvider,
    MetricsProviderList,
    Role,
    RoleBinding,
    RoleBindingList,
    RoleList,
)

logger = logging.getLogger(__name__)


class CoreApi(object):
    """Contains all handlers for the resources of the "core" API.
    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    # region GlobalMetrics
    @routes.route("POST", "/core/globalmetrics")
    @protected(api="core", resource="globalmetrics", verb="create")
    @use_schema("body", schema=make_create_request_schema(GlobalMetric))
    async def create_global_metric_async_async(request: web.Request, body):
        return await must_create_resource_async(request, body, None)

    @routes.route("GET", "/core/globalmetrics")
    @protected(api="core", resource="globalmetrics", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_metrics_async_async(
        request: web.Request, heartbeat: int, watch: bool
    ):
        return await list_or_watch_resources_async(
            GlobalMetric, GlobalMetricList, request, heartbeat, watch
        )

    @routes.route("GET", "/core/globalmetrics/{name}")
    @protected(api="core", resource="globalmetrics", verb="get")
    @load("entity", GlobalMetric)
    async def read_global_metric_async(request: web.Request, entity: GlobalMetric):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/core/globalmetrics/{name}")
    @protected(api="core", resource="globalmetrics", verb="update")
    @use_schema("body", schema=GlobalMetric.Schema)
    @load("entity", GlobalMetric)
    async def update_global_metric_async(
        request: web.Request, body: GlobalMetric, entity: GlobalMetric
    ):
        return await update_resource_async(request, entity, body)

    @routes.route("DELETE", "/core/globalmetrics/{name}")
    @protected(api="core", resource="globalmetrics", verb="delete")
    @load("entity", GlobalMetric)
    async def delete_global_metric_async_async(
        request: web.Request, entity: GlobalMetric
    ):
        return await delete_resource_async(request, entity)

    # endregion GlobalMetrics

    # region GlobalMetricsProvider
    @routes.route("POST", "/core/globalmetricsproviders")
    @protected(api="core", resource="globalmetricsproviders", verb="create")
    @use_schema("body", schema=make_create_request_schema(GlobalMetricsProvider))
    async def create_global_metrics_provider_async(
        request: web.Request, body: GlobalMetric
    ):
        return await must_create_resource_async(request, body, None)

    @routes.route("GET", "/core/globalmetricsproviders")
    @protected(api="core", resource="globalmetricsproviders", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_metrics_providers_async(
        request: web.Request, heartbeat: int, watch: bool
    ):
        return await list_or_watch_resources_async(
            GlobalMetricsProvider, GlobalMetricsProviderList, request, heartbeat, watch
        )

    @routes.route("GET", "/core/globalmetricsproviders/{name}")
    @protected(api="core", resource="globalmetricsproviders", verb="get")
    @load("entity", GlobalMetricsProvider)
    async def read_global_metrics_provider_async(
        request: web.Request, entity: GlobalMetricsProvider
    ):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/core/globalmetricsproviders/{name}")
    @protected(api="core", resource="globalmetricsproviders", verb="update")
    @use_schema("body", schema=GlobalMetricsProvider.Schema)
    @load("entity", GlobalMetricsProvider)
    async def update_global_metrics_provider_async(
        request: web.Request, body, entity: GlobalMetricsProvider
    ):
        return await update_resource_async(request, entity, body)

    @routes.route("DELETE", "/core/globalmetricsproviders/{name}")
    @protected(api="core", resource="globalmetricsproviders", verb="delete")
    @load("entity", GlobalMetricsProvider)
    async def delete_global_metrics_provider_async(
        request: web.Request, entity: GlobalMetricsProvider
    ):
        return await delete_resource_async(request, entity)

    # endregion GlobalMetricsProvider

    # region Roles
    @routes.route("POST", "/core/roles")
    @protected(api="core", resource="roles", verb="create")
    @use_schema("body", schema=make_create_request_schema(Role))
    async def create_role_async(request: web.Request, body: Role):
        return await must_create_resource_async(request, body, None)

    @routes.route("GET", "/core/roles")
    @protected(api="core", resource="roles", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_roles_async(
        request: web.Request, heartbeat: int, watch: bool
    ):
        return await list_or_watch_resources_async(
            Role, RoleList, request, heartbeat, watch
        )

    @routes.route("GET", "/core/roles/{name}")
    @protected(api="core", resource="roles", verb="get")
    @load("entity", Role)
    async def read_role_async(request: web.Request, entity: Role):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/core/roles/{name}")
    @protected(api="core", resource="roles", verb="update")
    @use_schema("body", schema=Role.Schema)
    @load("entity", Role)
    async def update_role_async(request: web.Request, body: Role, entity: Role):
        return await update_resource_async(request, entity, body)

    @routes.route("DELETE", "/core/roles/{name}")
    @protected(api="core", resource="roles", verb="delete")
    @load("entity", Role)
    async def delete_role_async(request: web.Request, entity):
        return await delete_resource_async(request, entity)

    # endregion Roles

    # region RoleBindings
    @routes.route("POST", "/core/rolebindings")
    @protected(api="core", resource="rolebindings", verb="create")
    @use_schema("body", schema=make_create_request_schema(RoleBinding))
    async def create_role_binding_async(request: web.Request, body: RoleBinding):
        return await must_create_resource_async(request, body, None)

    @routes.route("GET", "/core/rolebindings")
    @protected(api="core", resource="rolebindings", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_role_bindings_async(
        request: web.Request, heartbeat: int, watch: bool
    ):
        return await list_or_watch_resources_async(
            RoleBinding, RoleBindingList, request, heartbeat, watch
        )

    @routes.route("GET", "/core/rolebindings/{name}")
    @protected(api="core", resource="rolebindings", verb="get")
    @load("entity", RoleBinding)
    async def read_role_binding_async(request: web.Request, entity: RoleBinding):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/core/rolebindings/{name}")
    @protected(api="core", resource="rolebindings", verb="update")
    @use_schema("body", schema=RoleBinding.Schema)
    @load("entity", RoleBinding)
    async def update_role_binding_async(
        request: web.Request, body: RoleBinding, entity: RoleBinding
    ):
        return await update_resource_async(request, entity, body)

    @routes.route("DELETE", "/core/rolebindings/{name}")
    @protected(api="core", resource="rolebindings", verb="delete")
    @load("entity", RoleBinding)
    async def delete_role_binding_async(request: web.Request, entity: RoleBinding):
        return await delete_resource_async(request, entity)

    # region RoleBindings

    # region Metrics
    @routes.route("POST", "/core/namespaces/{namespace}/metrics")
    @protected(api="core", resource="metrics", verb="create")
    @use_schema("body", schema=make_create_request_schema(Metric))
    async def create_metric_async(request: web.Request, body: Metric):
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("DELETE", "/core/namespaces/{namespace}/metrics/{name}")
    @protected(api="core", resource="metrics", verb="delete")
    @load("entity", Metric)
    async def delete_metric_async(request: web.Request, entity: Metric):
        return await delete_resource_async(request, entity)

    @routes.route("GET", "/core/metrics")
    @routes.route("GET", "/core/namespaces/{namespace}/metrics")
    @protected(api="core", resource="metrics", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_metrics_async(
        request: web.Request, heartbeat: int, watch: bool
    ):
        return await list_or_watch_resources_async(
            Metric, MetricList, request, heartbeat, watch
        )

    @routes.route("GET", "/core/namespaces/{namespace}/metrics/{name}")
    @protected(api="core", resource="metrics", verb="get")
    @load("entity", Metric)
    async def read_metric_async(request: web.Request, entity: Metric):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/core/namespaces/{namespace}/metrics/{name}")
    @protected(api="core", resource="metrics", verb="update")
    @use_schema("body", schema=Metric.Schema)
    @load("entity", Metric)
    async def update_metric_async(request: web.Request, body: Metric, entity: Metric):
        return await update_resource_async(request, entity, body)

    # endregion Metrics

    # region MetricsProviders
    @routes.route("POST", "/core/namespaces/{namespace}/metricsproviders")
    @protected(api="core", resource="metricsproviders", verb="create")
    @use_schema("body", schema=make_create_request_schema(MetricsProvider))
    async def create_metrics_provider_async(
        request: web.Request, body: MetricsProvider
    ):
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("DELETE", "/core/namespaces/{namespace}/metricsproviders/{name}")
    @protected(api="core", resource="metricsproviders", verb="delete")
    @load("entity", MetricsProvider)
    async def delete_metrics_provider_async(
        request: web.Request, entity: MetricsProvider
    ):
        return await delete_resource_async(request, entity)

    @routes.route("GET", "/core/metricsproviders")
    @routes.route("GET", "/core/namespaces/{namespace}/metricsproviders")
    @protected(api="core", resource="metricsproviders", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_metrics_providers_async(
        request: web.Request, heartbeat: int, watch: bool
    ):
        return await list_or_watch_resources_async(
            MetricsProvider, MetricsProviderList, request, heartbeat, watch
        )

    @routes.route("GET", "/core/namespaces/{namespace}/metricsproviders/{name}")
    @protected(api="core", resource="metricsproviders", verb="get")
    @load("entity", MetricsProvider)
    async def read_metrics_provider_async(
        request: web.Request, entity: MetricsProvider
    ):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/core/namespaces/{namespace}/metricsproviders/{name}")
    @protected(api="core", resource="metricsproviders", verb="update")
    @use_schema("body", schema=MetricsProvider.Schema)
    @load("entity", MetricsProvider)
    async def update_metrics_provider_async(
        request: web.Request, body: MetricsProvider, entity: MetricsProvider
    ):
        return await update_resource_async(request, entity, body)

    # endregion MetricsProviders
