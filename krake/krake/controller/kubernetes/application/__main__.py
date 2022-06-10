"""Module for Krake controller responsible for
:class:`krake.data.kubernetes.Application` resources and entry point of
Kubernetes application controller.

.. code:: bash

    python -m krake.controller.kubernetes.application --help

Configuration is loaded from the ``controllers.kubernetes.application`` section:

.. code:: yaml

    api_endpoint: http://localhost:8080
    worker_count: 5
    debounce: 1.0
    hooks:
      complete:
        hook_user: system:complete-hook
        intermediate_src: tmp/pki/system:complete-signing.pem
        intermediate_key_src: tmp/pki/system:complete-signing-key.pem
        cert_dest: /etc/krake_cert
        env_token: KRAKE_COMPLETE_TOKEN
        env_url: KRAKE_COMPLETE_URL
      shutdown:
        hook_user: system:shutdown-hook
        intermediate_src: tmp/pki/system:shutdown-signing.pem
        intermediate_key_src: tmp/pki/system:shutdown-signing-key.pem
        cert_dest: /etc/krake_cert
        env_token: KRAKE_SHUTDOWN_TOKEN
        env_url: KRAKE_SHUTDOWN_URL

    tls:
      enabled: false
      client_ca: tmp/pki/ca.pem
      client_cert: tmp/pki/system:kubernetes-application.pem
      client_key: tmp/pki/system:kubernetes-application-key.pem


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
from krake.data.config import KubernetesConfiguration
from krake.utils import KrakeArgumentFormatter

from ....controller import create_ssl_context, run
from .application import KubernetesApplicationController


logger = logging.getLogger("krake.controller.kubernetes.application")


parser = ArgumentParser(
    description="Kubernetes application controller",
    formatter_class=KrakeArgumentFormatter,
)
parser.add_argument("-c", "--config", type=str, help="Path to configuration YAML file")

mapper = ConfigurationOptionMapper(KubernetesConfiguration)
mapper.add_arguments(parser)


def main(config):
    setup_logging(config.log)
    logger.debug(
        "Krake Kubernetes application controller configuration settings:\n %s",
        pprint.pformat(config.serialize()),
    )

    tls_config = config.tls
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    controller = KubernetesApplicationController(
        api_endpoint=config.api_endpoint,
        worker_count=config.worker_count,
        ssl_context=ssl_context,
        debounce=config.debounce,
        hooks=config.hooks,
    )
    run(controller)


if __name__ == "__main__":
    args = vars(parser.parse_args())

    config = load_yaml_config(
        args["config"] or search_config("kubernetes_application.yaml")
    )
    kubernetes_config = mapper.merge(config, args)

    main(kubernetes_config)
