from argparse import ArgumentParser, Namespace
from copy import deepcopy
from typing import List

import marshmallow
import pytest
import yaml
from pathlib import Path
from tempfile import TemporaryDirectory

from dataclasses import field
from krake import ConfigurationOptionMapper, load_yaml_config, search_config
from krake.data.config import ApiConfiguration
from krake.data.serializable import Serializable


def load_config(config):
    with TemporaryDirectory() as tempdir:
        base_config_path = Path(tempdir) / "krake.yaml"

        with base_config_path.open("w") as fd:
            yaml.dump(config.serialize(), stream=fd)
        raw_config = load_yaml_config(base_config_path)

    return ApiConfiguration.deserialize(raw_config, creation_ignored=True)


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


test_args = Namespace(
    first_key=None, second_key=True, third_key=False, the_fourth_key=4
)

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

    assert parsed == test_args

    # The list should not be parsed
    argv = "--second-key --fifth-key lorem".split()
    with pytest.raises(SystemExit):
        parser.parse_args(argv)


def test_load_command_line():
    modified_args = vars(test_args).copy()
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
    final_config = mapper._replace_from_cli(loaded_config, vars(test_args).copy())

    expected = {
        "first_key": "value_one",
        "second_key": True,
        "third_key": False,
        "the": {"fourth_key": 4},
    }
    assert final_config == expected


def test_search_config(tmp_path):
    """Test the search_config function"""
    root_yaml = tmp_path / "root.yaml"
    with open(root_yaml, "w") as f:
        f.write("foobar")

    chosen_path = search_config(root_yaml)
    assert chosen_path == root_yaml


def test_search_config_no_file():
    """Tests the error handling of search_config() if no file is found."""
    message = (
        "Configuration in 'non-existing.yaml', "
        "'/etc/krake/non-existing.yaml' not found"
    )
    with pytest.raises(FileNotFoundError, match=message):
        search_config("non-existing.yaml")


def test_merge():
    """Test that the merge function takes the argument parameters with a higher
    priority.
    """
    config = {
        "first_key": "value_one",
        "second_key": False,
        "third_key": False,
        "the": {"fourth_key": 0},
    }
    mapper = ConfigurationOptionMapper(
        RootConfiguration, option_fields_mapping=option_fields_mapping
    )

    merged = mapper.merge(config, vars(test_args))

    assert merged.first_key == "value_one"
    assert merged.second_key
    assert not merged.third_key
    assert merged.the.fourth_key == 4


def test_merge_validation_error():
    """Test that the merge function raises errors if arguments values are not valid."""
    config = {
        "first_key": "value_one",
        "second_key": False,
        "third_key": False,
        "the": {"fourth_key": 0},
    }
    mapper = ConfigurationOptionMapper(
        RootConfiguration, option_fields_mapping=option_fields_mapping
    )

    invalid_type = deepcopy(test_args)
    invalid_type.second_key = "not_a_bool"

    with pytest.raises(SystemExit, match=" - field 'second_key': Not a valid boolean."):
        mapper.merge(config, vars(invalid_type))

    invalid_nested_type = deepcopy(test_args)
    invalid_nested_type.the_fourth_key = "not_an_int"

    with pytest.raises(
        SystemExit, match=" - field 'the.fourth_key': Not a valid integer."
    ):
        mapper.merge(config, vars(invalid_nested_type))


def test_args_workflow_no_cli(tmp_path):
    """Test the workflow for starting a Krake component with support of the
    :class:`ConfigurationOptionMapper`.

    Let the mapper use the content of a default configuration file.
    """
    # Prepare the default configuration file:
    serialized_config = {
        "first_key": "value_one",
        "second_key": False,
        "third_key": False,
        "the": {"fourth_key": 0},
    }
    root_config = RootConfiguration.deserialize(serialized_config)

    root_yaml = tmp_path / "root.yaml"
    with open(root_yaml, "w") as f:
        yaml.dump(root_config.serialize(), f)

    # Create the mapper:
    parser = ArgumentParser()
    parser.add_argument("--config", "-c")

    mapper = ConfigurationOptionMapper(RootConfiguration)
    mapper.add_arguments(parser)

    # Use default configuration file, as no file has been set in the arguments
    no_config_args = Namespace(config=None)
    args = vars(no_config_args)

    config = load_yaml_config(args["config"] or search_config(root_yaml))
    api_config = mapper.merge(config, args)

    assert api_config.first_key == "value_one"
    assert not api_config.second_key
    assert not api_config.third_key
    assert api_config.the.fourth_key == 0


def test_args_workflow_file_from_cli(tmp_path):
    """Test the workflow for starting a Krake component with support of the
    :class:`ConfigurationOptionMapper`.

    Let the mapper use the content of a configuration file whose path was provided as
    parameter.
    """
    # Prepare the configuration file given as argument:
    serialized_config = {
        "first_key": "value_one",
        "second_key": True,
        "third_key": False,
        "the": {"fourth_key": 42},
    }
    root_config = RootConfiguration.deserialize(serialized_config)

    root_yaml = tmp_path / "root.yaml"
    with open(root_yaml, "w") as f:
        yaml.dump(root_config.serialize(), f)

    # Create the mapper:
    parser = ArgumentParser()
    parser.add_argument("--config", "-c")

    mapper = ConfigurationOptionMapper(RootConfiguration)
    mapper.add_arguments(parser)

    # Use file set in the arguments
    args_with_config = Namespace(config=root_yaml)
    args = vars(args_with_config)

    config = load_yaml_config(args["config"] or search_config("non-existing.yaml"))
    api_config = mapper.merge(config, args)

    assert api_config.first_key == "value_one"
    assert api_config.second_key
    assert not api_config.third_key
    assert api_config.the.fourth_key == 42
