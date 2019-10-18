"""Module for Krake controller responsible for
:class:`krake.data.kubernetes.Application` resources and entry point of
Kubernetes controller.

.. code:: bash

    python -m krake.controller.kubernetes.application --help

Configuration is loaded from the ``controllers.kubernetes.application`` section:

.. code:: yaml

    api_endpoint: http://localhost:8080
    worker_count: 5
    debounce: 1.0
    hooks:
      complete:
        ca_dest: /etc/krake_ca/ca.pem
        env_token: KRAKE_TOKEN
        env_complete: KRAKE_COMPLETE_URL

    tls:
      enabled: false
      client_ca: tmp/pki/ca.pem
      client_cert: tmp/pki/system:kubernetes.pem
      client_key: tmp/pki/system:kubernetes-key.pem


    log:
      ...

"""
import logging
import pprint
from argparse import ArgumentParser

from krake import load_config, setup_logging, search_config
from krake.data.config import KubernetesConfiguration

from ...controller import create_ssl_context, run
from .kubernetes_application import ApplicationController


logger = logging.getLogger("krake.controller.kubernetes")


def main(config):
    filepath = config or search_config("kubernetes.yaml")
    controller_config = load_config(KubernetesConfiguration, filepath=filepath)

    setup_logging(controller_config.log)
    logger.debug(
        "Krake Kubernetes Controller configuration settings:\n %s",
        pprint.pformat(controller_config.serialize()),
    )

    tls_config = controller_config.tls
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = ApplicationController(
        api_endpoint=controller_config.api_endpoint,
        worker_count=controller_config.worker_count,
        ssl_context=ssl_context,
        debounce=controller_config.debounce,
        hooks=controller_config.hooks,
    )
    run(controller)


if __name__ == "__main__":
    parser = ArgumentParser(description="Kubernetes application controller")
    parser.add_argument("-c", "--config", help="Path to configuration YAML file")
    main(**vars(parser.parse_args()))
