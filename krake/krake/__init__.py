import yaml
import logging.config


def load_config(filepath=None):
    """Load Krake YAML configuration

    If no filepath is specified, the configuration is searched in the
    following locations by this order:

    1. ``krake.yaml`` (current working directory)
    2. ``/etc/krake/krake.yaml``

    Args:
        filepath (os.PathLike, optional): Path to configuration file

    Raises:
        FileNotFoundError: If no configuration file can be found

    """
    if filepath is not None:
        filepaths = [filepath]
    else:
        filepaths = ["krake.yaml", "/etc/krake/krake.yaml"]

    for path in filepaths:
        try:
            with open(path, "r") as fd:
                return yaml.safe_load(fd)
        except FileNotFoundError:
            pass

    raise FileNotFoundError(f"No config file found: {filepaths}")


def setup_logging(config_log):
    """Setups Krake logging based on logging configuration

    Args:
        config_log (dict): dictschema logging configuration
            (see :func:`logging.config.dictConfig`)

    """
    logging.config.dictConfig(config_log)
