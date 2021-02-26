import os
import sys
from copy import deepcopy
from typing import List

import yaml
import logging.config

from dataclasses import is_dataclass, MISSING
from krake.data.serializable import is_generic_subtype, is_qualified_generic
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


class ConfigurationOptionMapper(object):
    """Handle the creation of command line options for a specific Configuration
    class. For each attribute of the Configuration, and recursively, an option will
    be added to set it from the command line. A mapping between the option name and
    the hierarchical list of fields is created. Nested options keep the upper layers
    as prefixes, which are separated by a "-" character.

    For instance, the following classes:

    .. code:: python

        class SpaceShipConfiguration(Serializable):
            name: str
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

    And the option-fields mapping will be:

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

    Then, from parsed arguments, the default value of an element of configuration
    are replaced by the elements set by the user through the parser, using this
    mapping.

    The mapping of the option name to the list of fields is necessary here
    because a configuration element called ``"lorem-ipsum"`` with a
    ``"dolor-sit-amet"`` element will be transformed into a
    ``"--lorem-ipsum-dolor-sit-amet"`` option. It will then be parsed as
    ``"lorem_ipsum_dolor_sit_amet"``. This last string, if split with ``"_"``, could
    be separated into ``"lorem"`` and ``"ipsum_dolor_sit_amet"``, or
    ``"lorem_ipsum_dolor"`` and ``"sit_amet"``. Hence the idea of the mapping to get
    the right separation.

    Args:
        config_cls (type): the configuration class which will be used as a model to
            generate the options.
        option_fields_mapping (dict, optional): a mapping of the option names, with
            POSIX convention (with "-" character"), to the list of fields:
            <option_name_with_dash>: <hierarchical_list_of_fields>
            This argument can be used to set the mapping directly, instead of creating
            it from a Configuration class.
    """

    def __init__(self, config_cls, option_fields_mapping=None):
        self.config_cls = config_cls

        if not option_fields_mapping:
            option_fields_mapping = {}
        self.option_fields_mapping = option_fields_mapping

    @staticmethod
    def _generate_option_name(fields):
        """From a hierarchical list of fields, create the corresponding option name, by
        taking the name of all fields in order, joining them with dash characters and
        replacing all underscores with dashes.

        Args:
            fields (list): a list of fields

        Returns:
            str: the concatenated string of the name of all fields, with dash
                characters.

        """
        return "-".join(field.name.replace("_", "-") for field in fields)

    def add_arguments(self, parser):
        """Using the configuration class given, create automatically and recursively
        command-line options to set the different attributes of the configuration.
        Nested options keep the upper layers as prefixes, which are separated by a "-"
        character.

        Generate the mapping between the option name and the hierarchy of the
        attributes of the Configuration.

        Args:
            parser (argparse.ArgumentParser): the parser to which the new command-line
                options will be added.

        """
        self.option_fields_mapping = self._add_opt_args(parser, self.config_cls)

    @classmethod
    def _add_opt_args(cls, parser, config_cls, parents=None):
        """Recursive function to go through all attributes of the Configuration class
        given, add options to the parser and generate the mapping of option name
        to fields.

        Args:
            parser (argparse.ArgumentParser): the parser to which the new command-line
                options will be added.
            config_cls (type): the configuration class which will be used as a
                model to generate the options.
            parents (list): hierarchy of fields of the current configuration class.

        Returns:
            dict: a mapping of the option names created, to the hierarchy of
            configuration classes of the option attribute.

        """
        if not parents:
            parents = []

        option_fields_mapping = {}
        for field in config_cls.__dataclass_fields__.values():
            new_parents = list(
                parents
            )  # Need to copy to prevent adding to another list
            new_parents.append(field)

            if is_dataclass(field.type):
                # Create options for the config class recursively
                sub_options = cls._add_opt_args(parser, field.type, parents=new_parents)
                option_fields_mapping = dict(sub_options, **option_fields_mapping)
            else:
                # Ignore fields that are "subclasses" of List (List[int], List[str]...)
                if is_qualified_generic(field.type) and is_generic_subtype(
                    field.type, List
                ):
                    continue

                kwargs = {}

                if "help" in field.metadata:
                    kwargs["help"] = field.metadata["help"]

                if field.type is bool:
                    # If the default is True, the action should be "store_false"
                    opposite = str(not field.default).lower()
                    kwargs["action"] = f"store_{opposite}"
                else:
                    kwargs["type"] = field.type

                name = cls._generate_option_name(new_parents)
                optname = "--" + name
                option_fields_mapping[name] = new_parents

                if field.default != MISSING:
                    kwargs["default"] = field.default

                parser.add_argument(optname, **kwargs)

        return option_fields_mapping

    @classmethod
    def _replace_hyphen(cls, dictionary):
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
            copy[new_key] = cls._replace_hyphen(copy[old_key])

            # If the key has been modified, a new entry has been added,
            # the old one needs to be removed
            if new_key != old_key:
                del copy[old_key]

        return copy

    @staticmethod
    def _create_error_message(err):
        """Create a prettier display from the Marshmallow ValidationError

        Args:
            err (ValidationError): Error that occurred during parsing of the
                configuration file

        Returns:
            str: the message that can be displayed.

        """

        def _get_field_errors(messages):
            """Generate a list of all fields with errors, along with the corresponding
            error.

            When validated, all validation errors for the nested fields are nested as
            well in the exception.

            Take the following example:

            .. code:: python

                class SimpleNested(Serializable):
                    attr: str

                class MultipleNested(Serializable):
                    a: int
                    b: SimpleNested

                class MyClass(Serializable):
                    first: str
                    second: SimpleNested
                    third: MultipleNested

            If each field has a validation error in MyClass, then the resulting
            "message" attribute of the validation exception will be similar to:

            .. code:: python

                my_dict = {
                    "first": ["Not a valid string"]
                    "second": {
                        "attr": ["Not a valid string"]
                    },
                    "third": {
                        "a": ["Not a valid integer"],
                        "b": ["Not a valid bool"]
                    },
                }

            So the current closure goes recursively through the dictionary to get each
            different error and concatenate the fields names when nested:

            .. code:: python

                assert _get_field_errors(my_dict) == [
                    ("first", ["Not a valid string"]),
                    ("second.attr", ["Not a valid string"]),
                    ("third.a", ["Not a valid integer"]),
                    ("third.b", ["Not a valid bool"]),
                ]

            Args:
                messages (dict[str, dict|list]): the dictionary of errors as provided by
                    marshmallow.

            Returns:
                list[(str, list[str])]: a list of tuples. Each tuple corresponds to one
                    attribute or nested attribute for which a validation error was
                    raised. The tuple all follow the signature:
                    ("<field_name>", ["<error_1>",... ,"[<error_n>]").

            """
            errors = []
            for field, nested in messages.items():

                if type(nested) is dict:
                    nested_results = _get_field_errors(nested)

                    # Concatenate the current field name with the one extracted from the
                    # layer below before adding it to the list of returned errors.
                    for field_error in nested_results:
                        formatted_tuple = field + "." + field_error[0], field_error[1]
                        errors.append(formatted_tuple)

                # Stop condition / non-nested dictionary.
                elif type(nested) is list:
                    errors.append((field, nested))

                else:
                    raise NotImplementedError("TODO")

            return errors

        message = "Parsing configuration failed with error(s): \n"

        lines = [
            f" - field {field!r}: " + ", ".join(errors)
            for field, errors in _get_field_errors(err.messages)
        ]
        return message + "\n".join(lines)

    def _load_command_line(self, args):
        """From the options parsed, keep only the values that have been set with
         the command line. Any argument that was set not through the mapper will be
         ignored.

        Args:
            args (dict): the values read by the command line parser.

        Returns:
            dict: the values set by the user: <option_name_with_underscore>: <value>

        """
        modified = {}
        for arg, value in args.items():
            # If the value is not set, continue
            if value is None:
                continue

            # The names of the options have "-" as separation character, but argparse
            # changed it into "_" character.
            option = arg.replace("_", "-")
            field = self.option_fields_mapping.get(option)

            # If an argument has been added by the user on top of the Configuration
            # object, it will not appear in the mapping
            if not field:
                continue

            # field holds the whole hierarchy of the option,
            # here just the name of the value is needed (last element).
            if field[-1].default == value:
                continue

            modified[arg] = value

        return modified

    def _replace_from_cli(self, loaded_config, args):
        """Update the given configuration with the arguments read from the command line.

        Args:
            loaded_config (dict): the configuration to replace the values from.
            args (dict): the values read by the command line parser.

        Returns:
            dict: a copy of the given configuration, with the values given by command
                line updated.
        """
        cl_config = self._load_command_line(args)

        config = dict(loaded_config)
        for option, new_value in cl_config.items():
            field_list = self.option_fields_mapping[option.replace("_", "-")]

            # Loop through the configuration to access the right attribute
            config_to_change = config
            for field in field_list[:-1]:
                config_to_change = config_to_change[field.name]

            # Update the configuration
            option_name = field_list[-1].name
            config_to_change[option_name] = new_value

        return config

    def merge(self, config, args):
        """Merge the configuration taken from file and the one from the command line
        arguments. The arguments have priority and replace the values read from
        configuration.

        Args:
            config (dict): the configuration to replace the values from.
            args (dict): the values read by the command line parser.

        Returns:
            krake.data.serializable.Serializable: the result of the merge of the CLI
                arguments into the configuration, as serializable object.

        """
        # Prevent side effect
        args = args.copy()
        merged = deepcopy(config)

        processed_config = self._replace_hyphen(merged)
        merged = self._replace_from_cli(processed_config, args)

        try:
            config_obj = self.config_cls.deserialize(merged, creation_ignored=True)
        except ValidationError as err:
            sys.exit(self._create_error_message(err))

        return config_obj


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
