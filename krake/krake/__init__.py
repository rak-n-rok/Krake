import os
import sys
from copy import deepcopy
from typing import List

import yaml
import logging.config

from dataclasses import is_dataclass
from marshmallow import ValidationError


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


def _create_error_message(err):
    """Create a prettier display from the Marshmallow ValidationError

    Args:
        err (ValidationError): Error that occurred during parsing of the
            configuration file

    Returns:
        str: the message that can be displayed.

    """
    message = "Parsing configuration failed with error(s): \n"

    lines = [
        f" - field '{field}': " + ", ".join(errors)
        for field, errors in err.messages.items()
    ]
    return message + "\n".join(lines)


def generate_option_name(fields):
    """From a hierarchical list of fields, create the corresponding option name, by
    taking the name of all fields in order, joining them with dash characters and
    replacing all underscores with dashes.

    Args:
        fields (list): a list of fields

    Returns:
        str: the concatenated string of the name of all fields, with dash
            characters.

    """
    fields_names = [field.name.replace("_", "-") for field in fields]
    return "-".join(fields_names)


def add_opt_args(parser, config_cls, parents=None):
    """Using the configuration class given, create automatically and recursively
    command-line options to set the different attributes of the configuration.
    Nested options keep the upper layers as prefixes, which are separated by a "-"
    character.

    For instance, the following classes:

    .. code:: python

        class SpaceShipConfiguration(Serializable):
            name: str
            cockpit: CockpitConfiguration
            propulsion: PropulsionConfiguration

        class PropulsionConfiguration(Serializable):
            power: int
            engine_type: TypeConfiguration

        class TypeConfiguration(Serializable):
            name: str

    Will be transformed into the following options:

    .. code:: bash

        --name str
        --propulsion-power int
        --propulsion-engine-type-name: str

    And the returned option-fields mapping will be:

    .. code:: python

        {
            "name": [Field(name="name", ...)],
            "propulsion-power": [
                Field(name="propulsion", ...), Field(name="power", ...)
            ],
            "propulsion-engine-type-name": [
                Field(name="propulsion", ...),
                Field(name="engine_type", ...),
                Field(name="name", ...),
            ],
        }

    Args:
        parser (argparse.Argumentparser): the parser to which the new command-line
            options will be added.
        config_cls (type): the configuration class
            which will be used as a model to generate the options.
        parents (list): hierarchy of fields of the current configuration class.

    Returns:
        dict: a mapping of the option names created, to the hierarchy of configuration
            classes of the option attribute.

    """
    if not parents:
        parents = []

    option_fields_mapping = {}
    for field in config_cls.__dataclass_fields__.values():
        new_parents = list(parents)  # Need to copy to prevent adding to another list
        new_parents.append(field)

        if is_dataclass(field.type):
            # Create options for the config class recursively
            sub_options = add_opt_args(parser, field.type, parents=new_parents)
            option_fields_mapping = dict(sub_options, **option_fields_mapping)
        else:
            kwargs = {}

            if "help" in field.metadata:
                kwargs["help"] = field.metadata["help"]

            if field.type is bool:
                # If the default is True, the action should be "store_false"
                kwargs["action"] = f"store_{str(not field.default).lower()}"
            else:
                kwargs["type"] = field.type

            if getattr(field.type, "__origin__", None) == List:
                continue

            name = generate_option_name(new_parents)
            optname = "--" + name
            option_fields_mapping[name] = new_parents
            parser.add_argument(optname, **kwargs)

    return option_fields_mapping


def load_command_line(args, option_fields_mapping):
    """From the options parsed, keep only the values that have been set with
     the command line.

    Args:
        args (argparse.Namespace): the values read by the command line parser.
        option_fields_mapping (dict): a mapping of the option names, with POSIX
            convention (with "-" character"), to the list of fields:
            <option_name_with_dash>: <hierarchical_list_of_fields>

    Returns:
        dict: the values set by the user: <option_name_with_underscore>: <value>

    """
    modified = {}
    for arg, value in vars(args).items():
        # If the value is not set, continue
        if value is None:
            continue

        # The names of the options have "-" as separation character, but argparse
        # changed it into "_" character.
        option = arg.replace("_", "-")
        field = option_fields_mapping[option]

        # field holds the whole hierarchy of the option,
        # here just the name of the value is needed (last element).
        if field[-1].default == value:
            continue

        modified[arg] = value

    return modified


def replace_from_cli(loaded_config, args, option_fields_mapping):
    """Update the given configuration with the arguments read from the command line.

    Args:
        loaded_config (dict): the configuration to replace the values from.
        args (argparse.Namespace): the values read by the command line parser.
        option_fields_mapping (dict): a mapping of the option names, with POSIX
            convention (with "-" character"), to the list of fields:
            <option_name_with_dash>: <hierarchical_list_of_fields>

    Returns:
        dict: a copy of the given configuration, with the values given by command line
            updated.
    """
    cl_config = load_command_line(args, option_fields_mapping)

    config = dict(loaded_config)
    for option, new_value in cl_config.items():
        # The mapping of the option name to the list of fields is necessary here
        # because a configuration element called "lorem-ipsum" with a "dolor-sit-amet"
        # element will be transformed into a "--lorem-ipsum-dolor-sit-amet" option.
        # It will then be parsed as "lorem_ipsum_dolor_sit_amet". This last string,
        # if split with "_", could be separated into "lorem" and
        # "ipsum_dolor_sit_amet", or  "lorem_ipsum_dolor" and "sit_amet". Thus the
        # idea of the mapping to get the right separation.
        field_list = option_fields_mapping[option.replace("_", "-")]

        # Loop through the configuration to access the right attribute
        config_to_change = config
        for field in field_list[:-1]:
            config_to_change = config_to_change[field.name]

        # Update the configuration
        option_name = field_list[-1].name
        config_to_change[option_name] = new_value

    return config


def load_config(template, args=None, option_fields_mapping=None, filepath=None):
    """Load Krake configuration settings

    Krake base configuration settings is defined by Krake YAML configuration file.
    Only selected configuration values can be overwritten by values loaded from
    environment variables.

    Args:
        template (type): Configuration class used to validate the read configuration.
        args (argparse.Namespace): the values read by the command line parser.
        option_fields_mapping (dict): a mapping of the option names, with POSIX
            convention (with "-" character"), to the list of fields:
            <option_name_with_dash>: <hierarchical_list_of_fields>
        filepath (os.PathLike, optional): Path to YAML configuration file

    Returns:
        krake.data.serialize.Serializable: Krake configuration

    """
    read_config = load_yaml_config(filepath)
    final_config = replace_hyphen(read_config)

    if bool(args) != bool(option_fields_mapping):
        raise ValueError("'args' and 'option_field_mapping' should both be set.")

    if args and option_fields_mapping:
        final_config = replace_from_cli(final_config, args, option_fields_mapping)

    try:
        config = template.deserialize(final_config)
    except ValidationError as err:
        sys.exit(_create_error_message(err))

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


def replace_hyphen(dictionary):
    """Loop all keys of a dictionary recursively to replace hyphen characters in the
    key by underscores.

    Args:
        dictionary (dict): the dictionary to loop on

    Returns:
        dict: a copy of the given dictionary, with all hyphens in keys replaced.

    """
    # During recursion, copy any value that is not a dict
    if type(dictionary) is not dict:
        return deepcopy(dictionary)  # do a copy for values such as lists

    copy = dict(dictionary)
    # For each key of the given dictionary,
    # - replace the dict values with the same dict without hyphens.
    # - replace the hyphen in the current key by an underscore
    for old_key in dictionary:
        new_key = old_key.replace("-", "_")

        # Replace the keys in the current value in any case
        copy[new_key] = replace_hyphen(copy[old_key])

        # If the key has been modified, a new entry has been added,
        # the old one needs to be removed
        if new_key != old_key:
            del copy[old_key]

    return copy


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
