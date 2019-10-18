import yaml
from pathlib import Path
from tempfile import TemporaryDirectory

from krake import load_config as load_krake_config


def load_config(config):
    with TemporaryDirectory() as tempdir:
        base_config_path = Path(tempdir) / "krake.yaml"

        with base_config_path.open("w") as fd:
            yaml.dump(config, stream=fd)
        config = load_krake_config(filepath=base_config_path)

    return config


def test_config_load_base(config):

    config_loaded = load_config(config)

    assert config_loaded == config
