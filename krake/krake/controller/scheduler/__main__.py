"""Module for Krake controller responsible for binding Krake
applications to specific backends and entry point of Krake scheduler.

.. code:: bash

    python -m krake.controller.scheduler --help

Configuration is loaded from the ``controllers.scheduler`` section:

.. code:: yaml

    api_endpoint: http://localhost:8080
    worker_count: 5
    debounce: 1
    reschedule_after: 60
    stickiness: 0.1
    tls:
      enabled: false
      client_ca: tmp/pki/ca.pem
      client_cert: tmp/pki/system:gc.pem
      client_key: tmp/pki/system:gc-key.pem

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
from krake.data.config import SchedulerConfiguration
from krake.utils import KrakeArgumentFormatter

from ...controller import create_ssl_context, run
from .scheduler import Scheduler

logger = logging.getLogger("krake.controller.scheduler")


parser = ArgumentParser(
    description="Krake scheduler", formatter_class=KrakeArgumentFormatter
)
parser.add_argument("-c", "--config", type=str, help="Path to configuration YAML file")

mapper = ConfigurationOptionMapper(SchedulerConfiguration)
mapper.add_arguments(parser)


def main(config):
    setup_logging(config.log)
    logger.debug("Krake Scheduler configuration settings:\n %s", pprint.pformat(config))

    tls_config = config.tls
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    scheduler = Scheduler(
        api_endpoint=config.api_endpoint,
        worker_count=config.worker_count,
        ssl_context=ssl_context,
        debounce=config.debounce,
        reschedule_after=config.reschedule_after,
        stickiness=config.stickiness,
    )
    run(scheduler)


if __name__ == "__main__":
    args = vars(parser.parse_args())

    config = load_yaml_config(args["config"] or search_config("scheduler.yaml"))
    scheduler_config = mapper.merge(config, args)

    main(scheduler_config)
