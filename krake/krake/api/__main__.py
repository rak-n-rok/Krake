"""Main module for starting the Krake API service as Python module:

.. code:: bash

    python -m krake.api

"""
import logging
import pprint
from argparse import ArgumentParser
from aiohttp import web
from krake.api.garbage_collection import (
    register_garbage_collection,
    cleanup_garbage_collection,
)

from .. import load_config, setup_logging
from .app import create_app


logger = logging.getLogger(__name__)


parser = ArgumentParser(description="Krake API server")
parser.add_argument("--config", "-c", help="Path to configuration file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)
    setup_logging(config["log"])
    logger.debug("Krake configuration settings:\n %s" % pprint.pformat(config))

    app = create_app(config)
    app.on_startup.append(register_garbage_collection)
    app.on_cleanup.append(cleanup_garbage_collection)
    web.run_app(app, ssl_context=app["ssl_context"])


if __name__ == "__main__":
    main()
