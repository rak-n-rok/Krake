"""This specific module handles the generation of the code for the API client of the
provided API definition, given as the Python path to its Krake data module.

The generator prints a file content. This should be put into a Python file, which can
then be integrated into Krake, in the ``krake.client`` package.

The following syntax should be used:

.. code:: bash

    python -m krake.api_generator api_client <module_path> [<other_opts>...] > \
        <module.path>

For example:

.. code:: bash

    python -m krake.api_generator api_client krake.apidefs.core

"""
import os

from krake.api_generator.utils import (
    add_templates_dir,
    get_data_classes,
    get_default_template_dir,
    render_and_print,
)
from krake.apidefs.definitions import ApiDef


def is_api_def(obj):
    """Check if the given object is an instance of :class:`ApiDef`.

    Args:
        obj: the object to check.

    Returns:
        bool: True if the given object is an instance of ApiDef, or one of its inherited
            class.

    """
    return isinstance(obj, ApiDef)


def generate_api_client(data_path, templates_dir, template_path="main.jinja"):
    """From a given Krake API definition path, print a Python file that contains the
    code of an implementation of the client for this API definition, to be included in
    Krake.

    Args:
        data_path (str): The Python module path to the data structures. For example:
            "krake.data.my_api".
        templates_dir (str): path of the directory in which the template is stored.
        template_path (str): name of the template.

    """
    api_definitions = get_data_classes(data_path, condition=is_api_def)
    assert len(api_definitions) == 1, "Only one API should be defined."
    api_definition = api_definitions[0]

    parameters = {"api_def": api_definition}
    render_and_print(templates_dir, template_path, parameters)


def add_apidef_subparser(subparsers):
    """Add the subparser that is specific for the generation of the API client code, as
    well as its arguments.

    Args:
        subparsers: the subparsers on which an additional parser should be added.

    """
    parser = subparsers.add_parser(
        "api_client",
        help="Generation of the client code, using an API definition as base.",
    )

    parser.add_argument(
        "data_path",
        help=(
            "Path to the module to parse for API definitions."
            "Syntax: '<path>.<to>.<module>'. Example: 'krake.api.apidefs.foo'."
        ),
    )
    default = os.path.join(get_default_template_dir(), "api_client")
    add_templates_dir(parser=parser, default=default)

    parser.set_defaults(generator=generate_api_client)
