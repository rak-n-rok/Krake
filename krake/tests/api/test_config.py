import marshmallow
import pytest
import yaml
from pathlib import Path
from tempfile import TemporaryDirectory

from krake import load_config as load_krake_config, replace_hyphen
from krake.data.config import ApiConfiguration


def load_config(config):
    with TemporaryDirectory() as tempdir:
        base_config_path = Path(tempdir) / "krake.yaml"

        with base_config_path.open("w") as fd:
            yaml.dump(config.serialize(), stream=fd)
        config = load_krake_config(ApiConfiguration, filepath=base_config_path)

    return config


def test_config_load_base(config):

    config_loaded = load_config(config)

    assert config_loaded == config


def test_config_validation(config):
    config_dict = config.serialize()

    config_dict["tls"]["enabled"] = 1

    with pytest.raises(marshmallow.exceptions.ValidationError):
        ApiConfiguration.deserialize(config)


def test_replace_hyphen():
    origin = {
        "key-1": "value-1",
        "key_2": "value_2",
        "key-3": {"key_3_1": "value_3"},
        "key-4": {"key-4-1": "value-4"},
        "key-5": ["value_5"],
    }
    copy = dict(origin)

    new = replace_hyphen(origin)

    expected = {
        "key_1": "value-1",
        "key_2": "value_2",
        "key_3": {"key_3_1": "value_3"},
        "key_4": {"key_4_1": "value-4"},
        "key_5": ["value_5"],
    }

    assert origin == copy
    assert origin is not new  # test that a new dict is created
    assert new == expected

    # test that the values are copied
    assert origin["key-5"] == new["key_5"]
    assert origin["key-5"] is not new["key_5"]
