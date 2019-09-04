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
import logging
import pprint
import re
import yaml
import yarl
from argparse import ArgumentParser
from inspect import iscoroutinefunction

from krake.data.core import ReasonCode
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.client import ApiClient, CoreV1Api, AppsV1Api, Configuration
from kubernetes_asyncio.client.rest import ApiException
from typing import NamedTuple

from krake import load_config, setup_logging
from krake.controller.kubernetes import KubernetesController
from krake.data.kubernetes import ApplicationState
from ..exceptions import on_error, ControllerError, application_error_mapping
from .. import Worker, run


logger = logging.getLogger("krake.controller.kubernetes")


class InvalidResourceError(ControllerError):
    """Raised in case of invalid kubernetes resource definition."""

    code = ReasonCode.INVALID_RESOURCE


class ApplicationController(KubernetesController):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in "SCHEDULED" and "DELETING" state.
    """

    states = (ApplicationState.SCHEDULED, ApplicationState.DELETING)
    resource_name = "application"


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


class ApplicationWorker(Worker):
    @on_error(ControllerError)
    async def resource_received(self, app):
        # Delete Kubernetes resources if the application was bound to a
        # cluster.
        if app.status.cluster:

            cluster = await self.client.kubernetes.cluster.get_by_url(
                app.status.cluster
            )

            # Initialize empty services dictionary: The services dictionary is
            # initialized with "None" in the Kubernetes data model indicating
            # that the application was not yet processed by the controller.
            # Here we reset the services dictionary to an empty dict to
            # signify that the application has been at least once processed.
            # Previously created Services, if any, are overwritten because
            # they will be updated or deleted by the Worker anyway.
            app.status.services = {}

            async with KubernetesClient(cluster.spec.kubeconfig) as kube:
                for resource in yaml.safe_load_all(app.spec.manifest):
                    if app.status.state == ApplicationState.SCHEDULED:
                        resp = await kube.apply(resource)
                        await listen.emit(
                            Event(resource["kind"], "apply"),
                            app=app,
                            cluster=cluster,
                            resp=resp,
                        )
                    else:
                        resp = await kube.delete(resource)
                        await listen.emit(
                            Event(resource["kind"], "delete"),
                            app=app,
                            cluster=cluster,
                            resp=resp,
                        )

        if app.status.state == ApplicationState.SCHEDULED:
            app.status.state = ApplicationState.RUNNING
        else:
            app.status.state = ApplicationState.DELETED

        await self.client.kubernetes.application.update_status(
            namespace=app.metadata.namespace, name=app.metadata.name, status=app.status
        )

    async def error_occurred(self, app, error=None):
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

        await self.client.kubernetes.application.update_status(
            namespace=app.metadata.namespace, name=app.metadata.name, status=app.status
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

    async def _replace(self, kind, name, body, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"replace_namespaced_{camel_to_snake_case(kind)}")
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
            logger.info("%s created. status=%r", kind, resp.status)
        else:
            resp = await self._replace(
                kind, name=name, body=resource, namespace=namespace
            )
            logger.info("%s replaced. status=%r", kind, resp.status)

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
                logger.info("%s already deleted", kind)
                return
            raise InvalidResourceError(err_resp=err)

        logger.info("%s deleted. status=%r", kind, resp.status)

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

    controller = ApplicationController(
        api_endpoint=config["controllers"]["kubernetes"]["application"]["api_endpoint"],
        worker_factory=ApplicationWorker,
        worker_count=config["controllers"]["kubernetes"]["application"]["worker_count"],
    )
    run(controller)


if __name__ == "__main__":
    main()
