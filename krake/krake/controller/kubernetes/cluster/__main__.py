"""Module for Krake controller responsible for
:class:`krake.data.kubernetes.Cluster` resources and entry point of
Kubernetes cluster controller.

.. code:: bash

    python -m krake.controller.kubernetes.cluster --help

Configuration is loaded from the ``controllers.kubernetes.cluster`` section:

.. code:: yaml

    api_endpoint: http://localhost:8080
    worker_count: 5
    debounce: 1.0

    tls:
      enabled: false
      client_ca: tmp/pki/ca.pem
      client_cert: tmp/pki/system:kubernetes-cluster.pem
      client_key: tmp/pki/system:kubernetes-cluster-key.pem


    log:
      ...

"""
import logging
import pprint
from argparse import ArgumentParser

from krake import (
    setup_logging,
    search_config,
    ConfigurationOptionMapper,
    load_yaml_config,
)
from krake.data.config import ControllerConfiguration
from krake.utils import KrakeArgumentFormatter

from ....controller import create_ssl_context, run
from .cluster import KubernetesClusterController


logger = logging.getLogger("krake.controller.kubernetes.cluster")


parser = ArgumentParser(
    description="Kubernetes cluster controller",
    formatter_class=KrakeArgumentFormatter,
)
parser.add_argument("-c", "--config", type=str, help="Path to configuration YAML file")

mapper = ConfigurationOptionMapper(ControllerConfiguration)
mapper.add_arguments(parser)


def main(config):
    setup_logging(config.log)
    logger.debug(
        "Krake Kubernetes cluster controller configuration settings:\n %s",
        pprint.pformat(config.serialize()),
    )

    tls_config = config.tls
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = KubernetesClusterController(
        api_endpoint=config.api_endpoint,
        worker_count=config.worker_count,
        ssl_context=ssl_context,
        debounce=config.debounce
    )
    run(controller)


if __name__ == "__main__":
    args = vars(parser.parse_args())

    config = load_yaml_config(
        args["config"] or search_config("kubernetes_cluster.yaml")
    )
    kubernetes_config = mapper.merge(config, args)

    main(kubernetes_config)
