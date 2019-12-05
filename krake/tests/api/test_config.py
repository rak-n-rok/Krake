from argparse import ArgumentParser, Namespace
from typing import List

import marshmallow
import pytest
import yaml
from pathlib import Path
from tempfile import TemporaryDirectory

from dataclasses import field
from krake import ConfigurationOptionMapper, load_yaml_config
from krake.data.config import ApiConfiguration
from krake.data.serializable import Serializable


def load_config(config):
    with TemporaryDirectory() as tempdir:
        base_config_path = Path(tempdir) / "krake.yaml"

        with base_config_path.open("w") as fd:
            yaml.dump(config.serialize(), stream=fd)
        raw_config = load_yaml_config(base_config_path)

    return ApiConfiguration.deserialize(raw_config)


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

    new = ConfigurationOptionMapper._replace_hyphen(origin)

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


# Command line option mapping


class Field(object):
    def __init__(self, name, default=None):
        self.name = name
        self.default = default


class NestedConfiguration(Serializable):
    fourth_key: int


class RootConfiguration(Serializable):
    first_key: str
    second_key: bool = field(default=False)
    third_key: bool = field(default=False)
    the: NestedConfiguration
    fifth_key: List[NestedConfiguration] = field(default_factory=list)


args = Namespace(first_key=None, second_key=True, third_key=False, the_fourth_key=4)

# Option name to list of fields mapping
option_fields_mapping = {
    "first-key": [Field("first_key")],
    "second-key": [Field("second_key", default=False)],
    "third-key": [Field("third_key", default=False)],
    "the-fourth-key": [Field("the"), Field("fourth_key")],
}


def test_add_argumentss():
    parser = ArgumentParser()
    mapper = ConfigurationOptionMapper(RootConfiguration)
    mapper.add_arguments(parser)
    mapping = mapper.option_fields_mapping

    assert len(mapping["first-key"]) == len(mapping["second-key"]) == 1
    assert len(mapping["third-key"]) == len(mapping["second-key"])
    assert len(mapping["the-fourth-key"]) == 2
    assert "fifth_key" not in mapping

    opt = mapping["the-fourth-key"][0].name + "_" + mapping["the-fourth-key"][1].name
    assert opt == "the_fourth_key"

    argv = "--second-key --the-fourth-key 4".split()
    parsed = parser.parse_args(argv)

    assert parsed == args

    # The list should not be parsed
    argv = "--second-key --fifth-key lorem".split()
    with pytest.raises(SystemExit):
        parser.parse_args(argv)


def test_load_command_line():
    modified_args = vars(args).copy()
    modified_args["foo"] = "over"

    mapper = ConfigurationOptionMapper(
        RootConfiguration, option_fields_mapping=option_fields_mapping
    )
    modified = mapper._load_command_line(modified_args)

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
    mapper = ConfigurationOptionMapper(
        RootConfiguration, option_fields_mapping=option_fields_mapping
    )
    final_config = mapper._replace_from_cli(loaded_config, vars(args).copy())

    expected = {
        "first_key": "value_one",
        "second_key": True,
        "third_key": False,
        "the": {"fourth_key": 4},
    }
    assert final_config == expected
