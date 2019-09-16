import yaml


def load_config(filepath=None):
    if filepath is not None:
        filepaths = [filepath]
    else:
        filepaths = ["config.yaml", "/etc/krake/config.yaml"]

    for path in filepaths:
        try:
            with open(path, "r") as fd:
                return yaml.load(fd)
        except FileNotFoundError:
            pass

    raise FileNotFoundError(f"No config file found: {filepaths}")
