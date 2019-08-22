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
import logging
import pprint
from argparse import ArgumentParser

from krake import load_config, setup_logging
from krake.controller.kubernetes import KubernetesController
from krake.data.kubernetes import ClusterState
from .. import Worker, run, extract_ssl_config

logger = logging.getLogger("krake.controller.kubernetes.cluster")


class ClusterController(KubernetesController):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in "SCHEDULED" and "DELETING" state.
    """

    states = (ClusterState.DELETING,)
    resource_name = "cluster"


class ClusterWorker(Worker):
    async def resource_received(self, cluster):
        # Delete all applications bound to the cluster before updating it

        logger.debug("Starting deletion of %r", cluster)
        cluster_ref = (
            f"/kubernetes/namespaces/{cluster.metadata.namespace}"
            f"/clusters/{cluster.metadata.name}"
        )

        # TODO Filter only the applications that depends on this cluster (change API)
        for app in await self.client.kubernetes.application.list(namespace="all"):
            if app.status.cluster == cluster_ref:
                logger.debug("Delete application %r", app.metadata.name)
                await self.client.kubernetes.application.delete(
                    namespace=app.metadata.namespace, name=app.metadata.name
                )

        await self.client.kubernetes.cluster.update_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            state=ClusterState.DELETED,
        )


parser = ArgumentParser(description="Kubernetes cluster controller")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)

    setup_logging(config["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(config))
    controller_config = config["controllers"]["kubernetes"]["cluster"]

    ssl_kwargs = extract_ssl_config(controller_config)

    controller = ClusterController(
        api_endpoint=controller_config["api_endpoint"],
        worker_factory=ClusterWorker,
        worker_count=controller_config["worker_count"],
        **ssl_kwargs,
    )
    run(controller)


if __name__ == "__main__":
    main()
