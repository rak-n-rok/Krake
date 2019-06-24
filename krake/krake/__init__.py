import yaml


def load_config(filepath=None):
    """Load Krake YAML configuration

    If no filepath is specified, the configuration is searched in the
    following locations by this order:

    1. ``config.yaml`` (current working directory)
    2. ``/etc/krake/config.yaml``

    Args:
        filepath (os.PathLike, optional): Path to configuration file

    Raises:
        FileNotFoundError: If no configuration file can be found

    """
    if filepath is not None:
        filepaths = [filepath]
    else:
        filepaths = ["config.yaml", "/etc/krake/config.yaml"]

    for path in filepaths:
        try:
            with open(path, "r") as fd:
                return yaml.safe_load(fd)
        except FileNotFoundError:
            pass

    raise FileNotFoundError(f"No config file found: {filepaths}")
