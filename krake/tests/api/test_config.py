from argparse import ArgumentParser, Namespace

import marshmallow
import pytest
import yaml
from pathlib import Path
from tempfile import TemporaryDirectory

from dataclasses import field
from krake import (
    load_config as load_krake_config,
    replace_hyphen,
    load_command_line,
    replace_from_cli,
    add_opt_args,
)
from krake.data.config import ApiConfiguration
from krake.data.serializable import Serializable


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


class Field(object):
    def __init__(self, name, default=None):
        self.name = name
        self.default = default


args = Namespace(first_key=None, second_key=True, third_key=False, the_fourth_key=4)

# Option name to list of fields mapping
option_fields_mapping = {
    "first-key": [Field("first_key")],
    "second-key": [Field("second_key", default=False)],
    "third-key": [Field("third_key", default=False)],
    "the-fourth-key": [Field("the"), Field("fourth_key")],
}


def test_add_opt_args():
    class NestedConfiguration(Serializable):
        fourth_key: int

    class RootConfiguration(Serializable):
        first_key: str
        second_key: bool = field(default=False)
        third_key: bool = field(default=False)
        the: NestedConfiguration

    parser = ArgumentParser()
    mapping = add_opt_args(parser, RootConfiguration)

    assert len(mapping["first-key"]) == len(mapping["second-key"]) == 1
    assert len(mapping["third-key"]) == len(mapping["second-key"])
    assert len(mapping["the-fourth-key"]) == 2

    opt = mapping["the-fourth-key"][0].name + "_" + mapping["the-fourth-key"][1].name
    assert opt == "the_fourth_key"

    argv = "--second-key --the-fourth-key 4".split()
    parsed = parser.parse_args(argv)

    assert parsed == args


def test_load_command_line():
    modified = load_command_line(args, option_fields_mapping)

    # Only values modified compared to the ones set in the Fields.
    expected = {"second_key": True, "the_fourth_key": 4}
    assert modified == expected


def test_replace_from_cli():
    loaded_config = {
        "first_key": "value_one",
        "second_key": False,
        "third_key": False,
        "the": {"fourth_key": 0},
    }
    final_config = replace_from_cli(loaded_config, args, option_fields_mapping)

    expected = {
        "first_key": "value_one",
        "second_key": True,
        "third_key": False,
        "the": {"fourth_key": 4},
    }
    assert final_config == expected
