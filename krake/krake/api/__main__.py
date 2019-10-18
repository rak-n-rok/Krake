"""Main module for starting the Krake API service as Python module:

.. code:: bash

    python -m krake.api

"""
import logging
import pprint
from argparse import ArgumentParser
from aiohttp import web
from krake.data.config import ApiConfiguration

from .. import load_config, search_config, setup_logging
from .app import create_app


logger = logging.getLogger(__name__)


def main(config):
    filepath = config or search_config("api.yaml")
    api_config = load_config(ApiConfiguration, filepath=filepath)

    setup_logging(api_config.log)
    logger.debug(
        "Krake configuration settings:\n %s", pprint.pformat(api_config.serialize())
    )

    app = create_app(api_config)
    web.run_app(app, ssl_context=app["ssl_context"])


if __name__ == "__main__":
    parser = ArgumentParser(description="Krake API server")
    parser.add_argument("--config", "-c", help="Path to configuration file")

    args = parser.parse_args()
    main(**vars(args))
