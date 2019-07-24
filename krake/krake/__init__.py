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


def setup_logging(level):
    logging.config.dictConfig(
        {
            "version": 1,
            "handlers": {"console": {"class": "logging.StreamHandler", "level": level}},
            "loggers": {"krake": {"handlers": ["console"], "level": level}},
        }
    )
