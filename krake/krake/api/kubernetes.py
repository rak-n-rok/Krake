import logging
from aiohttp import web
from webargs.aiohttpparser import use_kwargs

from krake import utils
from krake.api.auth import protected
from krake.api.helpers import (
    load,
    blocking,
    session,
    use_schema,
    HttpProblem,
    HttpProblemTitle,
    HttpProblemError,
    make_create_request_schema,
    ListQuery,
)
from krake.api.base import (
    must_create_resource_async,
    initialize_subresource_fields,
    delete_resource_async,
    update_resource_async,
    list_resources_async,
    watch_resource_async,
    update_property_async,
)
from krake.data.infrastructure import CloudBinding
from krake.data.kubernetes import (
    ApplicationList,
    Application,
    Cluster,
    ClusterList,
    ClusterBinding,
    ApplicationComplete,
    ApplicationShutdown,
    ApplicationState,
)


logger = logging.getLogger(__name__)


class KubernetesApi(object):
    """Contains all handlers for the resources of the "kubernetes" API.
    These handlers will be added to the Krake API components.
    """

    routes = web.RouteTableDef()

    # region Applications
    # region Applications CRUD
    @routes.route("POST", "/kubernetes/namespaces/{namespace}/applications")
    @protected(api="kubernetes", resource="applications", verb="create")
    @use_schema("body", schema=make_create_request_schema(Application))
    @blocking()
    async def create_application(request, body):
        body = initialize_subresource_fields(body)
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("GET", "/kubernetes/applications")
    @routes.route("GET", "/kubernetes/namespaces/{namespace}/applications")
    @protected(api="kubernetes", resource="applications", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_applications(request, heartbeat, watch, **query):
        resource_class = Application

        # If the ListAll operation
        namespace = request.match_info.get("namespace", None)

        # Return the list of resources
        if not watch:
            return await list_resources_async(
                resource_class, ApplicationList, request, namespace
            )

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route("GET", "/kubernetes/namespaces/{namespace}/applications/{name}")
    @protected(api="kubernetes", resource="applications", verb="get")
    @load("entity", Application)
    async def read_application(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/applications/{name}")
    @protected(api="kubernetes", resource="applications", verb="update")
    @use_schema("body", schema=Application.Schema)
    @load("entity", Application)
    async def update_application(request, body, entity):
        return await update_resource_async(request, entity, body)

    @routes.route("DELETE", "/kubernetes/namespaces/{namespace}/applications/{name}")
    @protected(api="kubernetes", resource="applications", verb="delete")
    @load("entity", Application)
    @blocking()
    async def delete_application(request, entity, **query):

        # Application is marked as force delete and will be removed from the Database
        force_deletion = "force" in request.query and request.query["force"] == "True"
        return await delete_resource_async(request, entity, force_deletion)

    # endregion Applicions CRUD

    # region Applications subroutes
    @routes.route(
        "PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/binding"
    )
    @protected(api="kubernetes", resource="applications/binding", verb="update")
    @use_schema("body", ClusterBinding.Schema)
    @load("app", Application)
    async def update_application_binding(request, body, app):
        now = utils.now()
        app.status.scheduled = now
        app.status.kube_controller_triggered = now
        app.status.scheduled_to = body.cluster

        if body.cluster not in app.metadata.owners:
            app.metadata.owners.append(body.cluster)

        await session(request).put(app)
        logger.info(
            "Update binding of application %r (%s)", app.metadata.name, app.metadata.uid
        )
        return web.json_response(app.serialize())

    @routes.route(
        "PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/complete"
    )
    @protected(api="kubernetes", resource="applications/complete", verb="update")
    @use_schema("body", ApplicationComplete.Schema)
    @load("app", Application)
    async def update_application_complete(request, body, app):
        # If the hook is not enabled for the Application or if the token is invalid
        if app.status.complete_token is None or app.status.complete_token != body.token:
            logger.debug(
                "The given token %s doesn't equal the required token %s",
                body.token,
                app.status.complete_token,
            )
            raise web.HTTPUnauthorized(
                reason="No token has been provided or the provided one is invalid."
            )

        app.status.state = ApplicationState.READY_FOR_ACTION
        # Resource marked as deletion, to be deleted by the Garbage Collector
        app.metadata.deleted = utils.now()
        await session(request).put(app)
        logger.info(
            "Deleting of application %r (%s) by calling complete hook",
            app.metadata.name,
            app.metadata.uid,
        )
        return web.json_response(app.serialize())

    @routes.route(
        "PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/shutdown"
    )
    @protected(api="kubernetes", resource="applications/shutdown", verb="update")
    @use_schema("body", ApplicationShutdown.Schema)
    @load("app", Application)
    async def update_application_shutdown(request, body, app):
        # If the hook is not enabled for the Application or if the token is invalid
        if app.status.shutdown_token is None or app.status.shutdown_token != body.token:
            logger.debug(
                "The given token %s doesn't equal the required token %s",
                body.token,
                app.status.shutdown_token,
            )
            raise web.HTTPUnauthorized(
                reason="No token has been provided or the provided one is invalid."
            )

        # Resource state changed to a READY_FOR state depending on the deleted flag
        if app.status.state in [
            ApplicationState.WAITING_FOR_CLEANING,
            ApplicationState.DEGRADED,
        ]:
            if app.metadata.deleted:
                app.status.state = ApplicationState.READY_FOR_ACTION
                app.status.shutdown_grace_period = None
            else:
                app.status.state = ApplicationState.READY_FOR_ACTION
                app.status.shutdown_grace_period = None
        await session(request).put(app)
        logger.info(
            "Deleting application %r (%s) by calling shutdown hook",
            app.metadata.name,
            app.metadata.uid,
        )
        return web.json_response(app.serialize())

    @routes.route(
        "PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/status"
    )
    @protected(api="kubernetes", resource="applications/status", verb="update")
    @use_schema("body", Application.Schema)
    @load("entity", Application)
    async def update_application_status(request, body, entity):
        return await update_property_async("status", request, body, entity)

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/applications/{name}/retry")
    @protected(api="kubernetes", resource="applications/status", verb="update")
    @load("entity", Application)
    async def retry_application(request, entity):

        if entity.status.state == ApplicationState.DEGRADED:
            entity.status.state = ApplicationState.WAITING_FOR_CLEANING
            entity.status.shutdown_grace_period = None
            await session(request).put(entity)
            logger.info(
                "Deleting %s %r (%s)",
                "Application",
                entity.metadata.name,
                entity.metadata.uid,
            )

        else:
            logger.info(
                "No migration or deletion retry for %s %r (%s) needed",
                "Application",
                entity.metadata.name,
                entity.metadata.uid,
            )
            problem = HttpProblem(
                detail="No migration or deletion retry needed",
                title=HttpProblemTitle.UPDATE_ERROR,
            )
            raise HttpProblemError(web.HTTPBadRequest, problem)

        return web.json_response(entity.serialize())

    # endregion Applications subroutes
    # endregion Applications

    # region Clusters CRUD
    @routes.route("POST", "/kubernetes/namespaces/{namespace}/clusters")
    @protected(api="kubernetes", resource="clusters", verb="create")
    @use_schema("body", schema=make_create_request_schema(Cluster))
    @blocking()
    async def create_cluster(request, body):
        body = initialize_subresource_fields(body)
        namespace = request.match_info.get("namespace")
        return await must_create_resource_async(request, body, namespace)

    @routes.route("GET", "/kubernetes/clusters")
    @routes.route("GET", "/kubernetes/namespaces/{namespace}/clusters")
    @protected(api="kubernetes", resource="clusters", verb="list")
    @use_kwargs(ListQuery.query, location="query")
    async def list_or_watch_clusters(request, heartbeat, watch, **query):
        resource_class = Cluster

        # If the ListAll operation
        namespace = request.match_info.get("namespace", None)

        # Return the list of resources
        if not watch:
            return await list_resources_async(
                resource_class, ClusterList, request, namespace
            )

        # Watching resources
        kwargs = {}
        if namespace is not None:
            kwargs["namespace"] = namespace

        async with session(request).watch(resource_class, **kwargs) as watcher:
            await watch_resource_async(request, heartbeat, watcher, resource_class)

    @routes.route("GET", "/kubernetes/namespaces/{namespace}/clusters/{name}")
    @protected(api="kubernetes", resource="clusters", verb="get")
    @load("entity", Cluster)
    async def read_cluster(request, entity):
        return web.json_response(entity.serialize())

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/clusters/{name}")
    @protected(api="kubernetes", resource="clusters", verb="update")
    @use_schema("body", schema=Cluster.Schema)
    @load("entity", Cluster)
    async def update_cluster(request, body, entity):
        return await update_resource_async(request, entity, body)

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/clusters/{name}/binding")
    @protected(api="kubernetes", resource="clusters/binding", verb="update")
    @use_schema("body", CloudBinding.Schema)
    @load("entity", Cluster)
    async def update_cluster_binding(request, body, entity):
        now = utils.now()
        entity.status.scheduled = now
        entity.status.scheduled_to = body.cloud

        if body.cloud not in entity.metadata.owners:
            entity.metadata.owners.append(body.cloud)

        await session(request).put(entity)
        logger.info(
            "Update %s of %s %r (%s)",
            "Binding",
            "Cluster",
            entity.metadata.name,
            entity.metadata.uid,
        )

        return web.json_response(entity.serialize())

    @routes.route("PUT", "/kubernetes/namespaces/{namespace}/clusters/{name}/status")
    @protected(api="kubernetes", resource="clusters/status", verb="update")
    @use_schema("body", Cluster.Schema)
    @load("entity", Cluster)
    async def update_cluster_status(request, body, entity):
        return await update_property_async("status", request, body, entity)

    @routes.route("DELETE", "/kubernetes/namespaces/{namespace}/clusters/{name}")
    @protected(api="kubernetes", resource="clusters", verb="delete")
    @load("entity", Cluster)
    @blocking()
    async def delete_cluster(request, entity, **query):

        # Resource is marked as force delete and will be removed from the Database
        force_deletion = "force" in request.query and request.query["force"] == "True"
        return await delete_resource_async(request, entity, force_deletion)

    # endregion Clusters
