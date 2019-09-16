from argparse import ArgumentParser
import logging.config
from aiohttp import web

from .. import load_config
from .app import create_app


parser = ArgumentParser(description="Krake API server")
parser.add_argument("--config", "-c", help="Path to configuration file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)
    logging.config.dictConfig(
        {
            "version": 1,
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": config["log"]["level"],
                }
            },
            "loggers": {
                "krake": {"handlers": ["console"], "level": config["log"]["level"]}
            },
        }
    )
    app = create_app(config)
    web.run_app(app)


if __name__ == "__main__":
    main()
