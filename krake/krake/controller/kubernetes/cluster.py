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
from argparse import ArgumentParser

from krake import load_config, setup_logging
from krake.controller.kubernetes import KubernetesController
from krake.data.kubernetes import ClusterState
from .. import Worker, run

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
    controller = ClusterController(
        api_endpoint=config["controllers"]["kubernetes"]["cluster"]["api_endpoint"],
        worker_factory=ClusterWorker,
        worker_count=config["controllers"]["kubernetes"]["cluster"]["worker_count"],
    )
    setup_logging(config["log"])
    run(controller)


if __name__ == "__main__":
    main()
