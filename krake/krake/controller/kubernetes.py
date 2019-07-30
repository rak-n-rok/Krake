"""Module for Krake controller responsible for
:class:`krake.data.kubernetes.Application` resources and entry point of
Kubernetes controller.

.. code:: bash

    python -m krake.controller.kubernetes --help

Configuration is loaded from the ``controllers.kubernetes`` section:

.. code:: yaml

    controllers:
      kubernetes:
        api_endpoint: http://localhost:8080
        worker_count: 5

"""
import logging
import re
import yaml
from argparse import ArgumentParser
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.client import ApiClient, CoreV1Api, AppsV1Api, Configuration
from kubernetes_asyncio.client.rest import ApiException

from krake import load_config, setup_logging
from krake.data.kubernetes import ApplicationState
from . import Controller, Worker, run


logger = logging.getLogger("krake.controller.kubernetes")


class KubernetesController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in "SCHEDULED" and "DELETING" state.
    """

    states = (ApplicationState.SCHEDULED, ApplicationState.DELETING)

    async def list_and_watch(self):
        """List and watching Kubernetes applications in the ``SCHEDULED``
        state.
        """
        logger.info("List Application")
        for app in await self.client.kubernetes.application.list(namespace="all"):
            logger.debug("Received %r", app)
            if app.status.state in self.states:
                await self.queue.put(app.metadata.uid, app)

        logger.info("Watching Application")
        async with self.client.kubernetes.application.watch(namespace="all") as watcher:
            async for app in watcher:
                logger.debug("Received %r", app)
                if app.status.state in self.states:
                    await self.queue.put(app.metadata.uid, app)


class KubernetesWorker(Worker):
    async def resource_received(self, app):
        # Delete Kubernetes resources if the application was bound to a
        # cluster.
        if app.spec.cluster:
            cluster = await self.client.kubernetes.cluster.get_by_url(app.spec.cluster)

            async with KubernetesClient(cluster.spec.kubeconfig) as kube:
                for resource in yaml.safe_load_all(app.spec.manifest):
                    if app.status.state == ApplicationState.SCHEDULED:
                        await kube.apply(resource)
                    else:
                        await kube.delete(resource)

        if app.status.state == ApplicationState.SCHEDULED:
            transition = ApplicationState.RUNNING
        else:
            transition = ApplicationState.DELETED

        await self.client.kubernetes.application.update_status(
            cluster=app.spec.cluster,
            namespace=app.metadata.namespace,
            name=app.metadata.name,
            state=transition,
        )


class InvalidResourceError(ValueError):
    pass


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
            raise ValueError('Resource must define "kind"')

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
                raise

        if resp is None:
            resp = await self._create(kind, body=resource, namespace=namespace)
            logger.info("%s created. status=%r", kind, resp.status)
        else:
            resp = await self._replace(
                kind, name=name, body=resource, namespace=namespace
            )
            logger.info("%s replaced. status=%r", kind, resp.status)

    async def delete(self, resource, namespace="default"):
        try:
            kind = resource["kind"]
        except KeyError:
            raise ValueError('Resource must define "kind"')

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
            raise

        logger.info("%s deleted. status=%r", kind, resp.status)


def camel_to_snake_case(name):
    """Converts camelCase to the snake_case

    Args:
        name (str): Camel case name

    Returns:
        str: Name in stake case
    """
    cunder = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", cunder).lower()


parser = ArgumentParser(description="Kubernetes application controller")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)
    controller = KubernetesController(
        api_endpoint=config["controllers"]["kubernetes"]["api_endpoint"],
        worker_factory=KubernetesWorker,
        worker_count=config["controllers"]["kubernetes"]["worker_count"],
    )
    setup_logging(config["log"])
    run(controller)


if __name__ == "__main__":
    main()
