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
from argparse import ArgumentParser, MetavarTypeHelpFormatter

from krake import load_config, setup_logging, search_config, add_opt_args
from krake.data.config import KubernetesConfiguration

from ...controller import create_ssl_context, run
from .kubernetes_application import ApplicationController


logger = logging.getLogger("krake.controller.kubernetes")


def main():
    option_fields_mapping = add_opt_args(parser, KubernetesConfiguration)
    args = parser.parse_args()

    filepath = args.config or search_config("kubernetes.yaml")
    controller_config = load_config(
        KubernetesConfiguration,
        filepath=filepath,
        args=args,
        option_fields_mapping=option_fields_mapping,
    )

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


parser = ArgumentParser(
    description="Kubernetes application controller",
    formatter_class=MetavarTypeHelpFormatter,
)
parser.add_argument("-c", "--config", type=str, help="Path to configuration YAML file")


if __name__ == "__main__":
    main()
