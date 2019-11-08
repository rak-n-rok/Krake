"""Module for Krake controller responsible for binding Krake
applications to specific backends and entry point of Krake scheduler.

.. code:: bash

    python -m krake.controller.scheduler --help

Configuration is loaded from the ``controllers.scheduler`` section:

.. code:: yaml

    controllers:
      scheduler:
        api_endpoint: http://localhost:8080
        worker_count: 5

"""
import logging
import pprint
from argparse import ArgumentParser

from krake import load_config, setup_logging, search_config
from ...controller import create_ssl_context, run
from .scheduler import Scheduler

logger = logging.getLogger("krake.controller.scheduler")


def main(config):
    scheduler_config = load_config(config or search_config("scheduler.yaml"))

    setup_logging(scheduler_config["log"])
    logger.debug(
        "Krake configuration settings:\n %s" % pprint.pformat(scheduler_config)
    )

    tls_config = scheduler_config.get("tls")
    ssl_context = create_ssl_context(tls_config)
    logger.debug("TLS is %s", "enabled" if ssl_context else "disabled")

    scheduler = Scheduler(
        api_endpoint=scheduler_config["api_endpoint"],
        worker_count=scheduler_config["worker_count"],
        ssl_context=ssl_context,
        debounce=scheduler_config.get("debounce", 0),
        reschedule_after=scheduler_config.get("reschedule_after", 60),
        stickiness=scheduler_config.get("stickiness", 0.1),
    )
    run(scheduler)


if __name__ == "__main__":
    parser = ArgumentParser(description="Krake scheduler")
    parser.add_argument("-c", "--config", help="Path to configuration YAML file")
    main(**vars(parser.parse_args()))
