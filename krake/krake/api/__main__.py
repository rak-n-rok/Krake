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
    setup_logging(config.log)
    logger.debug(
        "Krake configuration settings:\n %s", pprint.pformat(config.serialize())
    )

    app = create_app(config)
    web.run_app(app, ssl_context=app["ssl_context"], port=config.port)


if __name__ == "__main__":
    args = vars(parser.parse_args())

    config = load_yaml_config(args["config"] or search_config("api.yaml"))
    api_config = mapper.merge(config, args)

    main(api_config)
