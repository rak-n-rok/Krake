"""Module for Krake controller responsible for managing infrastructure resources and
creating Kubernetes clusters. It connects to the infrastructure
providers (IM, Yaook, etc.) that are responsible for actual management
of infrastructure resources.

.. code:: bash

    python -m krake.controller.infrastructure --help

The configuration should have the following structure:

.. code:: yaml

    api_endpoint: http://localhost:8080
    worker_count: 5
    debounce: 1.0

    tls:
      enabled: false
      client_ca: tmp/pki/ca.pem
      client_cert: tmp/pki/system:infrastructure.pem
      client_key: tmp/pki/system:infrastructure-key.pem


    log:
      ...

"""
import logging
import pprint
from argparse import ArgumentParser

from krake import (
    ConfigurationOptionMapper,
    setup_logging,
    load_yaml_config,
    search_config,
)

from krake.data.config import InfrastructureConfiguration
from krake.utils import KrakeArgumentFormatter

from .. import create_ssl_context, run
from .infrastructure import InfrastructureController

logger = logging.getLogger("krake.controller.infrastructure")

parser = ArgumentParser(
    description="Infrastructure controller", formatter_class=KrakeArgumentFormatter
)
parser.add_argument("-c", "--config", type=str, help="Path to configuration YAML file")

mapper = ConfigurationOptionMapper(InfrastructureConfiguration)
mapper.add_arguments(parser)


def main(config):
    setup_logging(config.log)
    logger.debug(
        "Krake infrastructure Controller configuration settings:\n %s",
        pprint.pformat(config.serialize()),
    )

    tls_config = config.tls
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = InfrastructureController(
        api_endpoint=config.api_endpoint,
        worker_count=config.worker_count,
        ssl_context=ssl_context,
        debounce=config.debounce,
        poll_interval=config.poll_interval,
    )
    run(controller)


if __name__ == "__main__":
    args = vars(parser.parse_args())

    config = load_yaml_config(args["config"] or search_config("infrastructure.yaml"))
    infrastructure_config = mapper.merge(config, args)

    main(infrastructure_config)
