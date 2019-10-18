import os

import yaml
import logging.config


def load_yaml_config(filepath):
    """Load Krake base configuration settings from YAML file

    Args:
        filepath (os.PathLike, optional): Path to YAML configuration file

    Raises:
        FileNotFoundError: If no configuration file can be found

    Returns:
        dict: Krake YAML file configuration

    """
    with open(filepath, "r") as fd:
        return yaml.safe_load(fd)


def load_config(filepath):
    """Load Krake configuration settings

    Krake base configuration settings is defined by Krake YAML configuration file.
    Only selected configuration values can be overwritten by values loaded from
    environment variables.

    Args:
        filepath (os.PathLike):  Path to YAML configuration file

    Returns:
        dict: Krake configuration

    """
    config = load_yaml_config(filepath=filepath)

    return config


def search_config(filename):
    """Search configuration file in known directories.

    The filename is searched in the following directories in given order:

    1. Current working directory
    2. ``/etc/krake``

    Returns:
        os.PathLike: Path to configuration file

    Raises:
        FileNotFoundError: If the configuration cannot be found in any of the
            search locations.

    """
    options = [filename, os.path.join("/etc/krake/", filename)]

    for path in options:
        if os.path.exists(path):
            return path

    locations = ", ".join(map(repr, options))
    raise FileNotFoundError(f"Configuration in {locations} not found")


def setup_logging(config_log):
    """Setups Krake logging based on logging configuration and
    global config level for each logger without log-level configuration

    Args:
        config_log (dict): dictschema logging configuration
            (see :func:`logging.config.dictConfig`)

    """
    logging.config.dictConfig(config_log)
    loggers = [
        logging.getLogger(name)
        for name in logging.root.manager.loggerDict
        if not logging.getLogger(name).level
    ]

    for logger in loggers:
        logger.setLevel(config_log["level"])
