import copy
import os

import yaml
import logging.config
from functools import reduce


KRAKE_CONF_ENV_KEYS = (
    "ETCD",
    "TLS",
    "AUTHENTICATION",
    "AUTHORIZATION",
    "CONTROLLERS",
    "LOG",
)


def evaluate_value(value, base_value):
    """Evaluate Krake environment variable value based on Krake base
     configuration value and rules definition, see :func:``validate_krake_env`` doc

    Args:
        value: Krake environment variable value
        base_value: Krake base configuration value

    Raises:
        ValueError if base_value type is not valid

    Returns:
        Evaluated Krake environment variable value

    """
    if isinstance(base_value, str):
        return str(value)

    if isinstance(base_value, bool):
        return value in ("True", "true")

    if isinstance(base_value, int):
        return int(value)

    raise ValueError


def validate_krake_env(name, value, base_config):
    """Validate Krake environment variable

     Validation of Krake environment variable is defined by following rules:

    1. Only environment variable name prefixed by the parent Krake
    configuration key defined in ``KRAKE_CONF_ENV_KEYS`` can be loaded
    2. Only environment variable name which strictly keeps the Krake base
    configuration structure defined by ``base_config`` can be loaded
    3. Only environment variable with non empty value can be loaded
    4. Only <class 'str'> or <class 'int'> or <class 'bool'> value can be overwritten

    Args:
        name (str): Environment variable name
        value (str): Environment variable value
        base_config (dict): Krake base configuration

    Raises:
        KeyError: If environment variable name is not valid
        ValueError: If environment variable value is empty

    Returns:
        list, str: Validated Krake configuration keys loaded from environment variable
        and its value

    """
    if not name.startswith(KRAKE_CONF_ENV_KEYS):
        raise KeyError

    if not value.strip():
        raise ValueError

    keys = []
    key_buffer = []
    base_value = None

    for key in [n.lower() for n in name.split("_")]:
        base_key = "_".join(key_buffer + [key])
        try:
            base_value = reduce(lambda d, k: d[k], keys + [base_key], base_config)
            keys.append(base_key)
            key_buffer = []
        except KeyError:
            key_buffer.append(key)
            continue

    if not keys or "_".join(keys) != name.lower():
        raise KeyError

    value = evaluate_value(value, base_value)

    return keys, value


def load_env_config(base_config):
    """Load Krake environment variables configuration

    Selected Krake configuration values loaded from Krake YAML configuration file
    can be overwritten by values loaded from environment variables.
    Krake environment variable is validate by :func:`validate_krake_env`

    Args:
        base_config (dict): Krake base configuration

    Returns:
        dict: Krake environment variables configuration

    """
    env_config = {}
    for name, value in os.environ.items():
        try:
            keys, value = validate_krake_env(name, value, base_config)
        except (KeyError, ValueError):
            continue

        env_config[tuple(keys)] = value

    return env_config


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
    base_config = load_yaml_config(filepath)
    env_config = load_env_config(base_config)

    config = copy.deepcopy(base_config)
    for keys, value in env_config.items():
        # Overwrite config value by value loaded from environment variable
        reduce(lambda d, k: d[k], keys[:-1], config)[keys[-1]] = value

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
