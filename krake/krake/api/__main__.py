"""Main module for starting the Krake API service as Python module:

.. code:: bash

    python -m krake.api

"""
import logging
import pprint
from argparse import ArgumentParser, MetavarTypeHelpFormatter
from aiohttp import web
from krake.data.config import ApiConfiguration

from .. import load_config, setup_logging, add_opt_args, search_config
from .app import create_app


logger = logging.getLogger(__name__)


def main():
    option_fields_mapping = add_opt_args(parser, ApiConfiguration)
    args = parser.parse_args()

    filepath = args.config or search_config("api.yaml")
    config = load_config(
        ApiConfiguration,
        option_fields_mapping=option_fields_mapping,
        args=args,
        filepath=filepath,
    )
    setup_logging(config.log)
    logger.debug(
        "Krake configuration settings:\n %s", pprint.pformat(config.serialize())
    )

    app = create_app(config)
    web.run_app(app, ssl_context=app["ssl_context"])


parser = ArgumentParser(
    description="Krake API server", formatter_class=MetavarTypeHelpFormatter
)
parser.add_argument("--config", "-c", type=str, help="Path to configuration file")


if __name__ == "__main__":
    main()
