"""Main module for starting the Krake API service as Python module:

.. code:: bash

    python -m krake.api

"""
from argparse import ArgumentParser
from aiohttp import web

from .. import load_config, setup_logging
from .app import create_app


parser = ArgumentParser(description="Krake API server")
parser.add_argument("--config", "-c", help="Path to configuration file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)
    setup_logging(config["log"])
    app = create_app(config)
    web.run_app(app)


if __name__ == "__main__":
    main()
