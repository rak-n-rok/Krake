import os
import sys
import logging.config


# Prepend package directory for working imports
package_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, package_dir)


logging.config.dictConfig(
    {
        "version": 1,
        "handlers": {"console": {"class": "logging.StreamHandler", "level": "DEBUG"}},
        "loggers": {"rok": {"handlers": ["console"]}},
    }
)
