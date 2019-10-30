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
from argparse import ArgumentParser

from krake import load_config, setup_logging

from ...controller import create_ssl_context, run
from .kubernetes_application import ApplicationController


logger = logging.getLogger("krake.controller.kubernetes")


def main(config):
    krake_conf = load_config(config)

    setup_logging(krake_conf["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(krake_conf))
    controller_config = krake_conf["controllers"]["kubernetes_application"]

    tls_config = controller_config.get("tls")
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = ApplicationController(
        api_endpoint=controller_config["api_endpoint"],
        worker_count=controller_config["worker_count"],
        ssl_context=ssl_context,
        debounce=controller_config.get("debounce", 0),
    )
    setup_logging(krake_conf["log"])
    run(controller)


if __name__ == "__main__":
    parser = ArgumentParser(description="Kubernetes application controller")
    parser.add_argument("-c", "--config", help="Path to configuration YAML file")
    main(**vars(parser.parse_args()))
