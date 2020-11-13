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
from krake.api_generator.utils import (
    add_templates_dir,
    get_data_classes,
    get_default_template_dir,
    render_and_print,
    add_no_black_formatting,
    add_operations_to_keep,
    filter_operations,
    add_resources_to_keep,
    filter_resources,
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


def generate_api_client(
    data_path,
    templates_dir,
    no_black,
    template_path="api_client/main.jinja",
    operations=None,
    resources=None,
):
    """From a given Krake API definition path, print a Python file that contains the
    code of an implementation of the client for this API definition, to be included in
    Krake.

    Args:
        data_path (str): The Python module path to the data structures. For example:
            "krake.data.my_api".
        templates_dir (str): path of the directory in which the template is stored.
        no_black (bool): if True, the black formatting will not be used.
        template_path (str): name of the template.
        operations (list[str]): list of names of operations that the generator should
            display. If empty, all operations are processed and displayed.
        resources (list[str]): list of names of resources that the generator should
            display. If empty, all resources are processed and displayed.

    """
    api_definitions = get_data_classes(data_path, condition=is_api_def)
    assert len(api_definitions) == 1, "Only one API should be defined."
    api_definition = api_definitions[0]

    if resources:
        filter_resources(api_definition, resources)

    if operations:
        filter_operations(api_definition, operations)

    parameters = {"api_def": api_definition}
    render_and_print(templates_dir, template_path, parameters, no_black=no_black)


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
    add_templates_dir(parser=parser, default=get_default_template_dir())

    add_no_black_formatting(parser=parser)

    add_operations_to_keep(parser=parser)
    add_resources_to_keep(parser=parser)

    parser.set_defaults(generator=generate_api_client)
