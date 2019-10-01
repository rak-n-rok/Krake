"""Module for Krake controller responsible for
:class:`krake.data.kubernetes.Application` resources and entry point of
Kubernetes controller.

.. code:: bash

    python -m krake.controller.kubernetes.application --help

Configuration is loaded from the ``controllers.kubernetes.application`` section:

.. code:: yaml

    controllers:
      kubernetes:
        application:
          api_endpoint: http://localhost:8080
          worker_count: 5

"""
import asyncio
import logging
import pprint
import re
from copy import deepcopy
import yarl
from argparse import ArgumentParser
from inspect import iscoroutinefunction

from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.client import ApiClient, CoreV1Api, AppsV1Api, Configuration
from kubernetes_asyncio.client.rest import ApiException
from typing import NamedTuple

from krake import load_config, setup_logging
from krake.data.core import ReasonCode
from krake.data.kubernetes import ApplicationState
from krake.client.kubernetes import KubernetesApi

from .exceptions import ControllerError, on_error, application_error_mapping
from . import Controller, Worker, run, create_ssl_context


logger = logging.getLogger("krake.controller.kubernetes")


class InvalidResourceError(ControllerError):
    """Raised in case of invalid kubernetes resource definition."""

    code = ReasonCode.INVALID_RESOURCE


class InvalidStateError(ControllerError):
    """Kubernetes application is in an invalid state"""


class ApplicationController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in "SCHEDULED" and "DELETING" state.
    """

    async def list_and_watch(self):
        """List and watching Kubernetes applications in the ``SCHEDULED``
        state.
        """
        kubernetes_api = KubernetesApi(self.client)

        def scheduled_or_deleting(app):
            accepted = app.status.state == ApplicationState.SCHEDULED or (
                app.metadata.deleted
                and app.metadata.finalizers
                and app.metadata.finalizers[-1] == "kubernetes_resources_deletion"
            )
            if not accepted:
                logger.debug(f"Rejected Application {app}")
            return accepted

        async def list_apps():
            logger.info("List application")
            app_list = await kubernetes_api.list_all_applications()
            for app in filter(scheduled_or_deleting, app_list.items):
                logger.debug(
                    "Received %r (%s)", app.metadata.name, app.metadata.namespace
                )
                await self.queue.put(app.metadata.uid, app)

        async def watch_apps(watcher):
            logger.info("Watching application")
            async for event in watcher:
                app = event.object
                if scheduled_or_deleting(app):
                    logger.debug(
                        "Received %r (%s)", app.metadata.name, app.metadata.namespace
                    )
                    await self.queue.put(app.metadata.uid, app)

        async with kubernetes_api.watch_all_applications() as watcher:
            await asyncio.gather(list_apps(), watch_apps(watcher))


class Event(NamedTuple):
    kind: str
    action: str


class EventDispatcher(object):
    """Simple wrapper around a registry of handlers associated to Events

    Events are characterized by a "kind" and an "action" (see :class:`Event`).
    Listeners for cetain events can be registered via :meth:`on`. Registered
    listeners are executed if an event gets emitted via :meth:`emit`.

    Example:
        .. code:: python

        listen = EventDispatcher()

        @listen.on(Event("Deployment","delete"))
        def to_perform_on_deployment_delete(app, cluster, resp):
            # Do Stuff

        @listen.on(Event("Deployment","delete"))
        def another_to_perform_on_deployment_delete(app, cluster, resp):
            # Do Stuff

        @listen.on(Event("Service","apply"))
        def to_perform_on_service_apply(app, cluster, resp):
            # Do Stuff

    """

    def __init__(self):
        self.registry = {}

    def on(self, event):
        """Decorator function to add a new handler to the registry.

        Args:
            event (Event): Event for which to register the handler.

        Returns:
            callable: Decorator for registering listeners for the specified
            events.

        """

        def decorator(handler):
            if not (event.kind, event.action) in self.registry:
                self.registry[(event.kind, event.action)] = [handler]
            else:
                self.registry[(event.kind, event.action)].append(handler)

        return decorator

    async def emit(self, event, **kwargs):
        """ Execute the list of handlers associated to the provided Event.

        Args:
            event (Event): Event for which to execute handlers.

        """
        try:
            handlers = self.registry[(event.kind, event.action)]
        except KeyError:
            pass
        else:
            for handler in handlers:
                if iscoroutinefunction(handler):
                    await handler(**kwargs)
                else:
                    handler(**kwargs)


listen = EventDispatcher()


class ResourceID(NamedTuple):
    """Named tuple for identifying Kubernetes resource objects by their API
    version, kind and name.
    """

    api_version: str
    kind: str
    name: str

    @classmethod
    def from_resource(cls, resource):
        """Create an identifier for the given Kubernetes resource object.

        Args:
            resource (dict): Kubernetes resource object

        Returns:
            ResourceID: Identifier for the given resource object

        """
        return cls(
            api_version=resource["apiVersion"],
            kind=resource["kind"],
            name=resource["metadata"]["name"],
        )


class ApplicationWorker(Worker):
    @on_error(ControllerError)
    async def resource_received(self, app):
        logger.debug("Handle %r", app)

        kubernetes_api = KubernetesApi(self.client)
        copy = deepcopy(app)

        if app.metadata.deleted:
            await self._cleanup_application(copy, kubernetes_api)
        else:
            assert app.status.state == ApplicationState.SCHEDULED
            await self._apply_manifest(copy, kubernetes_api)

    async def _cleanup_application(self, app, kubernetes_api):
        logger.info("Cleanup %r (%s)", app.metadata.name, app.metadata.namespace)

        # Delete Kubernetes resources if the application was bound to a
        # cluster and there Kubernetes resources were created.
        if app.status.cluster and app.status.manifest:
            cluster = await kubernetes_api.read_cluster(
                namespace=app.status.cluster.namespace, name=app.status.cluster.name
            )
            async with KubernetesClient(cluster.spec.kubeconfig) as kube:
                for resource in app.status.manifest:
                    resp = await kube.delete(resource)
                    await listen.emit(
                        Event(resource["kind"], "delete"),
                        app=app,
                        cluster=cluster,
                        resp=resp,
                    )

        if (
            app.metadata.finalizers
            and app.metadata.finalizers[-1] == "kubernetes_resources_deletion"
        ):
            app.metadata.finalizers.pop(-1)

        await kubernetes_api.update_application(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

    async def _apply_manifest(self, app, kubernetes_api):
        logger.info("Apply manifest %r (%s)", app.metadata.name, app.metadata.namespace)

        if not app.status.cluster:
            raise InvalidStateError(
                "Application is scheduled but no cluster is assigned"
            )

        # Append "kubernetes_resources_deletion" finalizer if not already present.
        # This will prevent the API from deleting the resource without remove the
        # Kubernetes resources.
        if "kubernetes_resources_deletion" not in app.metadata.finalizers:
            app.metadata.finalizers.append("kubernetes_resources_deletion")
            await kubernetes_api.update_application(
                namespace=app.metadata.namespace, name=app.metadata.name, body=app
            )

        # Initialize empty services dictionary: The services dictionary is
        # initialized with "None" in the Kubernetes data model indicating
        # that the application was not yet processed by the controller.
        # Here we reset the services dictionary to an empty dict to
        # signify that the application has been at least once processed.
        # Previously created Services, if any, are overwritten because
        # they will be updated or deleted by the Worker anyway.
        app.status.services = {}

        desired_resources = {
            ResourceID.from_resource(resource): resource
            for resource in app.spec.manifest
        }
        current_resources = {
            ResourceID.from_resource(resource): resource
            for resource in (app.status.manifest or [])
        }

        cluster = await kubernetes_api.read_cluster(
            namespace=app.status.cluster.namespace, name=app.status.cluster.name
        )
        async with KubernetesClient(cluster.spec.kubeconfig) as kube:
            # Delete all resources that are no longer in the spec
            for resource_id in set(current_resources) - set(desired_resources):
                current = current_resources[resource_id]
                resp = await kube.delete(current)
                await listen.emit(
                    Event(current["kind"], "delete"),
                    app=app,
                    cluster=cluster,
                    resp=resp,
                )

            # Create or update all desired resources
            for resource_id, desired in desired_resources.items():
                current = current_resources.get(resource_id)

                # Apply resource if no current resource exists or the
                # specification differs.
                if not current or desired["spec"] != current["spec"]:
                    resp = await kube.apply(desired)
                    await listen.emit(
                        Event(desired["kind"], "apply"),
                        app=app,
                        cluster=cluster,
                        resp=resp,
                    )

        # Update resource in application status
        app.status.manifest = app.spec.manifest.copy()

        # Transition into running state
        app.status.state = ApplicationState.RUNNING

        await kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

    async def error_handler(self, app, error=None):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Callback updates kubernetes application status to the failed state and
        describes the reason of the failure.

        Args:
            app (krake.data.kubernetes.Application): Application object processed
                when the error occurred
            error (Exception, optional): The exception whose reason will be propagated
                to the end-user. Defaults to None.
        """
        reason = application_error_mapping(app.status.state, app.status.reason, error)
        app.status.reason = reason

        # If an important error occurred, simply delete the Application
        if reason.code.value >= 100:
            app.status.state = ApplicationState.DELETED
        else:
            app.status.state = ApplicationState.FAILED

        kubernetes_api = KubernetesApi(self.client)
        await kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )


@listen.on(event=Event("Service", "apply"))
async def register_service(app, cluster, resp):
    service_name = resp.metadata.name

    node_port = resp.spec.ports[0].node_port

    if node_port is None:
        return

    # Load Kubernetes configuration and get host
    loader = KubeConfigLoader(cluster.spec.kubeconfig)
    config = Configuration()
    await loader.load_and_set(config)
    url = yarl.URL(config.host)

    app.status.services[service_name] = url.host + ":" + str(node_port)


class KubernetesClient(object):
    def __init__(self, kubeconfig):
        self.kubeconfig = kubeconfig
        self.resource_apis = None

    async def __aenter__(self):
        # Load Kubernetes configuration
        loader = KubeConfigLoader(self.kubeconfig)
        config = Configuration()
        await loader.load_and_set(config)

        api_client = ApiClient(config)
        core_v1_api = CoreV1Api(api_client)
        apps_v1_api = AppsV1Api(api_client)

        self.resource_apis = {
            "ConfigMap": core_v1_api,
            "Deployment": apps_v1_api,
            "Endpoints": core_v1_api,
            "Event": core_v1_api,
            "LimitRange": core_v1_api,
            "PersistentVolumeClaim": core_v1_api,
            "PersistentVolumeClaimStatus": core_v1_api,
            "Pod": core_v1_api,
            "PodLog": core_v1_api,
            "PodStatus": core_v1_api,
            "PodTemplate": core_v1_api,
            "ReplicationController": core_v1_api,
            "ReplicationControllerScale": core_v1_api,
            "ReplicationControllerStatus": core_v1_api,
            "ResourceQuota": core_v1_api,
            "ResourceQuotaStatus": core_v1_api,
            "Secret": core_v1_api,
            "Service": core_v1_api,
            "ServiceAccount": core_v1_api,
            "ServiceStatus": core_v1_api,
        }
        return self

    async def __aexit__(self, *exec):
        self.resource_apis = None

    async def _read(self, kind, name, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"read_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, namespace=namespace)

    async def _create(self, kind, body, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"create_namespaced_{camel_to_snake_case(kind)}")
        return await fn(body=body, namespace=namespace)

    async def _patch(self, kind, name, body, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"patch_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, body=body, namespace=namespace)

    async def _delete(self, kind, name, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"delete_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, namespace=namespace)

    async def apply(self, resource, namespace="default"):
        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidResourceError('Resource must define "kind"')

        if kind not in self.resource_apis:
            raise InvalidResourceError(f"{kind} resources are not supported")

        try:
            name = resource["metadata"]["name"]
        except KeyError:
            raise InvalidResourceError('Resource must define "metadata.name"')

        try:
            resp = await self._read(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status == 404:
                resp = None
            else:
                raise InvalidResourceError(err_resp=err)

        if resp is None:
            resp = await self._create(kind, body=resource, namespace=namespace)
            logger.debug("%s created. status=%r", kind, resp.status)
        else:
            resp = await self._patch(
                kind, name=name, body=resource, namespace=namespace
            )
            logger.debug("%s patched. status=%r", kind, resp.status)

        return resp

    async def delete(self, resource, namespace="default"):
        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidResourceError('Resource must define "kind"')

        if kind not in self.resource_apis:
            raise InvalidResourceError(f"{kind} resources are not supported")

        try:
            name = resource["metadata"]["name"]
        except KeyError:
            raise InvalidResourceError('Resource must define "metadata.name"')

        try:
            resp = await self._delete(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status == 404:
                logger.debug("%s already deleted", kind)
                return
            raise InvalidResourceError(err_resp=err)

        logger.debug("%s deleted. status=%r", kind, resp.status)

        return resp


def camel_to_snake_case(name):
    """Converts camelCase to the snake_case

    Args:
        name (str): Camel case name

    Returns:
        str: Name in snake case

    """
    cunder = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", cunder).lower()


parser = ArgumentParser(description="Kubernetes application controller")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)

    setup_logging(config["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(config))
    controller_config = config["controllers"]["kubernetes_application"]

    tls_config = controller_config.get("tls")
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = ApplicationController(
        api_endpoint=controller_config["api_endpoint"],
        worker_factory=ApplicationWorker,
        worker_count=controller_config["worker_count"],
        ssl_context=ssl_context,
        debounce=controller_config.get("debounce", 0),
    )
    setup_logging(config["log"])
    run(controller)


if __name__ == "__main__":
    main()
