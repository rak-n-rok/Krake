import os
import sys
from copy import deepcopy

import yaml
import logging.config

from marshmallow import ValidationError


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


def _create_error_message(err):
    """Create a prettier display from the Marshmallow ValidationError

    Args:
        err (ValidationError): Error that occurred during parsing of the
            configuration file

    Returns:
        str: the message that can be displayed.

    """
    message = "Parsing configuration failed with error(s): \n"

    lines = [
        f" - field '{field}': " + ", ".join(errors)
        for field, errors in err.messages.items()
    ]
    return message + "\n".join(lines)


def load_config(template, filepath=None):
    """Load Krake configuration settings

    Krake base configuration settings is defined by Krake YAML configuration file.
    Only selected configuration values can be overwritten by values loaded from
    environment variables.

    Args:
        template (type): Configuration class used to validate the read configuration.
        filepath (os.PathLike, optional): Path to YAML configuration file

    Returns:
        krake.data.serialize.Serializable: Krake configuration

    """
    read_config = load_yaml_config(filepath)

    processed_config = replace_hyphen(read_config)

    try:
        config = template.deserialize(processed_config)
    except ValidationError as err:
        sys.exit(_create_error_message(err))

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


def replace_hyphen(dictionary):
    """Loop all keys of a dictionary recursively to replace hyphen characters in the
    key by underscores.

    Args:
        dictionary (dict): the dictionary to loop on

    Returns:
        dict: a copy of the given dictionary, with all hyphens in keys replaced.

    """
    # During recursion, copy any value that is not a dict
    if type(dictionary) is not dict:
        return deepcopy(dictionary)  # do a copy for values such as lists

    copy = dict(dictionary)
    # For each key of the given dictionary,
    # - replace the dict values with the same dict without hyphens.
    # - replace the hyphen in the current key by an underscore
    for old_key in dictionary:
        new_key = old_key.replace("-", "_")

        # Replace the keys in the current value in any case
        copy[new_key] = replace_hyphen(copy[old_key])

        # If the key has been modified, a new entry has been added,
        # the old one needs to be removed
        if new_key != old_key:
            del copy[old_key]

    return copy


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
