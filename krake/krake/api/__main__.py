"""Main module for starting the Krake API service as Python module:

.. code:: bash

    python -m krake.api

"""
import logging
import pprint
from argparse import ArgumentParser
from aiohttp import web
from krake.data.config import ApiConfiguration
from krake.utils import KrakeArgumentFormatter

from .. import load_yaml_config, setup_logging, ConfigurationOptionMapper, search_config
from .app import create_app

# import for advanced logging
from . import middlewares
from aiohttp.web_log import AccessLogger

logger = logging.getLogger(__name__)

parser = ArgumentParser(
    description="Krake API server", formatter_class=KrakeArgumentFormatter
)
parser.add_argument("--config", "-c", type=str, help="Path to configuration file")

mapper = ConfigurationOptionMapper(ApiConfiguration)
mapper.add_arguments(parser)


def main(config):
    """Starts the API using the provided configuration.

    Args:
        config (ApiConfiguration): the configuration that will be used to parameterize
            the API.

    """

    # logging.basicConfig(
    # level=logging.DEBUG,
    # format='%(asctime)s [%(threadName)s] %(name)-26s %(levelname)5s:
    # %(requestIdPrefix)s%(message)s')
    # format='[%(threadName)s] %(name)-26s %(levelname)5s:
    # %(requestIdPrefix)s%(message)s')

    middlewares.setup_logging_request_id_prefix()

    setup_logging(config.log)
    logger.debug(
        "Krake configuration settings:\n %s", pprint.pformat(config.serialize())
    )

    app = create_app(config)
    web.run_app(
        app,
        ssl_context=app["ssl_context"],
        port=config.port,
        access_log_class=middlewares.RequestIdContextAccessLogger,
        access_log_format=AccessLogger.LOG_FORMAT.replace(" %t ", " ") + " %Tf",
    )


if __name__ == "__main__":
    args = vars(parser.parse_args())

    config = load_yaml_config(args["config"] or search_config("api.yaml"))
    api_config = mapper.merge(config, args)

    main(api_config)
