"""Module for Krake controller responsible for
:class:`krake.data.kubernetes.Cluster` resources and entry point of
Kubernetes controller.

.. code:: bash

    python -m krake.controller.kubernetes.cluster --help

Configuration is loaded from the ``controllers.kubernetes.cluster`` section:

.. code:: yaml

    controllers:
      kubernetes:
        cluster:
          api_endpoint: http://localhost:8080
          worker_count: 5

"""
import asyncio
import logging
import pprint
from argparse import ArgumentParser
from aiohttp import ClientResponseError

from krake import load_config, setup_logging
from krake.data.core import resource_ref
from krake.client.kubernetes import KubernetesApi
from .. import Controller, Worker, run, create_ssl_context


logger = logging.getLogger("krake.controller.kubernetes.cluster")


class ClusterController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Cluster`
    resources.
    """

    async def list_and_watch(self):
        """List and watching Kubernetes clusters."""
        kubernetes_api = KubernetesApi(self.client)

        async def list_apps():
            logger.info("List cluster")
            cluster_list = await kubernetes_api.list_all_clusters()
            for cluster in cluster_list.items:
                logger.debug("Received %r", cluster)
                if cluster.metadata.deleted:
                    await self.queue.put(cluster.metadata.uid, cluster)

        async def watch_apps(watcher):
            logger.info("Watching cluster")
            async for event in watcher:
                cluster = event.object
                logger.debug("Received %r", cluster)
                if cluster.metadata.deleted:
                    await self.queue.put(cluster.metadata.uid, cluster)

        async with kubernetes_api.watch_all_clusters() as watcher:
            await asyncio.gather(list_apps(), watch_apps(watcher))


async def wait_for_app_deletion(api, namespace, name):
    while True:
        try:
            await api.read_application(namespace=namespace, name=name)
        except ClientResponseError as err:
            if err.status == 404:
                return
            raise


class ClusterWorker(Worker):
    async def resource_received(self, cluster):
        # Delete all applications bound to the cluster before updating it
        kubernetes_api = KubernetesApi(self.client)

        logger.debug("Starting deletion of %r", cluster)
        cluster_ref = resource_ref(cluster)

        waiters = []

        # TODO Filter only the applications that depends on this cluster (change API)
        cluster_list = await kubernetes_api.list_all_applications()
        for app in cluster_list.items:
            if app.status.cluster == cluster_ref:
                logger.debug("Delete application %r", app.metadata.name)
                await kubernetes_api.delete_application(
                    namespace=app.metadata.namespace, name=app.metadata.name
                )
                waiters.append(
                    wait_for_app_deletion(
                        kubernetes_api,
                        namespace=app.metadata.namespace,
                        name=app.metadata.name,
                    )
                )

        await asyncio.wait_for(asyncio.gather(*waiters), 60 * 5)

        await kubernetes_api.delete_cluster(
            namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )


parser = ArgumentParser(description="Kubernetes cluster controller")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)

    setup_logging(config["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(config))
    controller_config = config["controllers"]["kubernetes"]["cluster"]

    tls_config = controller_config.get("tls")
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = ClusterController(
        api_endpoint=controller_config["api_endpoint"],
        worker_factory=ClusterWorker,
        worker_count=controller_config["worker_count"],
        ssl_context=ssl_context,
    )
    run(controller)


if __name__ == "__main__":
    main()
