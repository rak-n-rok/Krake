import logging
from aiohttp import web
from webargs.aiohttpparser import use_kwargs
from krake.api.auth import protected
from krake.api.helpers import (
    load,
    session,
    use_schema,
    make_create_request_schema,
    ListQuery,
 )
from krake.api.base import (
    must_create_resource_async,
    delete_resource_async,
    update_resource_async,
    list_resources_async,
    watch_resource_async,
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
    RoleList
)

logger = logging.getLogger(__name__)


class CoreApi(object):
    """Contains all handlers for the resources of the "core" API.
    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    @routes.route(
        "POST", "/core/globalmetrics"
    )
    @protected(
        api="core", resource="globalmetrics", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(GlobalMetric)
    )
    async def create_global_metric(request, body):
        return await must_create_resource_async(request, body, None)

    @routes.route(
        "DELETE", "/core/globalmetrics/{name}"
    )
    @protected(
        api="core", resource="globalmetrics", verb="delete"
    )
    @load("entity", GlobalMetric)
    async def delete_global_metric(request, entity):
        return await delete_resource_async(request, entity)

    @routes.route(
        "GET", "/core/globalmetrics"
    )
    @protected(
        api="core", resource="globalmetrics", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_metrics(request, heartbeat, watch, **query):
        resource_class = GlobalMetric
        # Return the list of resources
        if not watch:
            return await list_resources_async(
                resource_class, GlobalMetricList, request, None)

        # Watching resources
        kwargs = {}
        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route(
        "GET", "/core/globalmetrics/{name}"
    )
    @protected(
        api="core", resource="globalmetrics", verb="get"
    )
    @load("entity", GlobalMetric)
    async def read_global_metric(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/globalmetrics/{name}"
    )
    @protected(
        api="core", resource="globalmetrics", verb="update"
    )
    @use_schema(
        "body", schema=GlobalMetric.Schema
    )
    @load("entity", GlobalMetric)
    async def update_global_metric(request, body, entity):
        return await update_resource_async(request, entity, body)

    @routes.route(
        "POST", "/core/globalmetricsproviders"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(GlobalMetricsProvider)
    )
    async def create_global_metrics_provider(request, body):
        return await must_create_resource_async(request, body, None)

    @routes.route(
        "DELETE", "/core/globalmetricsproviders/{name}"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="delete"
    )
    @load("entity", GlobalMetricsProvider)
    async def delete_global_metrics_provider(request, entity):
        return await delete_resource_async(request, entity)

    @routes.route(
        "GET", "/core/globalmetricsproviders"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_global_metrics_providers(request, heartbeat, watch,
                                                     **query):
        resource_class = GlobalMetricsProvider

        # Return the list of resources
        if not watch:
            return await list_resources_async(
                resource_class, GlobalMetricsProviderList, request, None)

        # Watching resources
        kwargs = {}
        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route(
        "GET", "/core/globalmetricsproviders/{name}"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="get"
    )
    @load("entity", GlobalMetricsProvider)
    async def read_global_metrics_provider(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/globalmetricsproviders/{name}"
    )
    @protected(
        api="core", resource="globalmetricsproviders", verb="update"
    )
    @use_schema(
        "body", schema=GlobalMetricsProvider.Schema
    )
    @load("entity", GlobalMetricsProvider)
    async def update_global_metrics_provider(request, body, entity):
        return await update_resource_async(request, entity, body)

    @routes.route(
        "POST", "/core/roles"
    )
    @protected(
        api="core", resource="roles", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(Role)
    )
    async def create_role(request, body):
        return await must_create_resource_async(request, body, None)

    @routes.route(
        "DELETE", "/core/roles/{name}"
    )
    @protected(
        api="core", resource="roles", verb="delete"
    )
    @load("entity", Role)
    async def delete_role(request, entity):
        return await delete_resource_async(request, entity)

    @routes.route(
        "GET", "/core/roles"
    )
    @protected(
        api="core", resource="roles", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_roles(request, heartbeat, watch, **query):
        resource_class = Role

        # Return the list of resources
        if not watch:
            return await list_resources_async(resource_class, RoleList, request, None)

        # Watching resources
        kwargs = {}
        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route(
        "GET", "/core/roles/{name}"
    )
    @protected(
        api="core", resource="roles", verb="get"
    )
    @load("entity", Role)
    async def read_role(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/roles/{name}"
    )
    @protected(
        api="core", resource="roles", verb="update"
    )
    @use_schema(
        "body", schema=Role.Schema
    )
    @load("entity", Role)
    async def update_role(request, body, entity):
        return await update_resource_async(request, entity, body)

    @routes.route(
        "POST", "/core/rolebindings"
    )
    @protected(
        api="core", resource="rolebindings", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(RoleBinding)
    )
    async def create_role_binding(request, body):
        return await must_create_resource_async(request, body, None)

    @routes.route(
        "DELETE", "/core/rolebindings/{name}"
    )
    @protected(
        api="core", resource="rolebindings", verb="delete"
    )
    @load("entity", RoleBinding)
    async def delete_role_binding(request, entity):
        return await delete_resource_async(request, entity)

    @routes.route(
        "GET", "/core/rolebindings"
    )
    @protected(
        api="core", resource="rolebindings", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_role_bindings(request, heartbeat, watch, **query):
        resource_class = RoleBinding

        # Return the list of resources
        if not watch:
            return await list_resources_async(
                resource_class, RoleBindingList, request, None)

        # Watching resources
        kwargs = {}
        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route(
        "GET", "/core/rolebindings/{name}"
    )
    @protected(
        api="core", resource="rolebindings", verb="get"
    )
    @load("entity", RoleBinding)
    async def read_role_binding(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/rolebindings/{name}"
    )
    @protected(
        api="core", resource="rolebindings", verb="update"
    )
    @use_schema(
        "body", schema=RoleBinding.Schema
    )
    @load("entity", RoleBinding)
    async def update_role_binding(request, body, entity):
        return await update_resource_async(request, entity, body)

    @routes.route(
        "POST", "/core/namespaces/{namespace}/metrics"
    )
    @protected(
        api="core", resource="metrics", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(Metric)
    )
    async def create_metric(request, body):
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route(
        "DELETE", "/core/namespaces/{namespace}/metrics/{name}"
    )
    @protected(
        api="core", resource="metrics", verb="delete"
    )
    @load("entity", Metric)
    async def delete_metric(request, entity):
        return await delete_resource_async(request, entity)

    @routes.route(
        "GET", "/core/metrics"
    )
    @routes.route(
        "GET", "/core/namespaces/{namespace}/metrics"
    )
    @protected(
        api="core", resource="metrics", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_metrics(request, heartbeat, watch, **query):
        resource_class = Metric

        # If the ListAll operation
        namespace = request.match_info.get("namespace", None)

        # Return the list of resources
        if not watch:
            return await list_resources_async(
                resource_class, MetricList, request, namespace)

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route(
        "GET", "/core/namespaces/{namespace}/metrics/{name}"
    )
    @protected(
        api="core", resource="metrics", verb="get"
    )
    @load("entity", Metric)
    async def read_metric(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/namespaces/{namespace}/metrics/{name}"
    )
    @protected(
        api="core", resource="metrics", verb="update"
    )
    @use_schema(
        "body", schema=Metric.Schema
    )
    @load("entity", Metric)
    async def update_metric(request, body, entity):
        return await update_resource_async(request, entity, body)

    @routes.route(
        "POST", "/core/namespaces/{namespace}/metricsproviders"
    )
    @protected(
        api="core", resource="metricsproviders", verb="create"
    )
    @use_schema(
        "body", schema=make_create_request_schema(MetricsProvider)
    )
    async def create_metrics_provider(request, body):
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route(
        "DELETE", "/core/namespaces/{namespace}/metricsproviders/{name}"
    )
    @protected(
        api="core", resource="metricsproviders", verb="delete"
    )
    @load("entity", MetricsProvider)
    async def delete_metrics_provider(request, entity):
        return await delete_resource_async(request, entity)

    @routes.route(
        "GET", "/core/metricsproviders"
    )
    @routes.route(
        "GET", "/core/namespaces/{namespace}/metricsproviders"
    )
    @protected(
        api="core", resource="metricsproviders", verb="list"
    )
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_metrics_providers(request, heartbeat, watch, **query):
        resource_class = MetricsProvider

        # If the ListAll operation
        namespace = request.match_info.get("namespace", None)

        # Return the list of resources
        if not watch:
            return await list_resources_async(
                resource_class, MetricsProviderList, request, namespace)

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route(
        "GET", "/core/namespaces/{namespace}/metricsproviders/{name}"
    )
    @protected(
        api="core", resource="metricsproviders", verb="get"
    )
    @load("entity", MetricsProvider)
    async def read_metrics_provider(request, entity):
        return web.json_response(entity.serialize())

    @routes.route(
        "PUT", "/core/namespaces/{namespace}/metricsproviders/{name}"
    )
    @protected(
        api="core", resource="metricsproviders", verb="update"
    )
    @use_schema(
        "body", schema=MetricsProvider.Schema
    )
    @load("entity", MetricsProvider)
    async def update_metrics_provider(request, body, entity):
        return await update_resource_async(request, entity, body)
