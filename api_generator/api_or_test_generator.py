"""This specific module handles the generation of API code, for the client and the
server-side, and for their unit tests counterparts. The API definitions files must be
provided as path to the API definition module in the API generator.

The generator prints a file content. This should be put into a Python file, which can
then be integrated into Krake, in the Krake code or unit tests.

The following syntax should be used:

.. code:: bash

    python -m api_generator <generator_name> <module_path> [<other_opts>...] > \
        <module.path>

For ``generator_name``, the possibilities are set in the main of the API generator.

For example:

.. code:: bash

    python -m api_generator api_client api_generator.apidefs.core

"""
import sys

from .utils import (
    add_templates_dir,
    get_data_classes,
    get_default_template_dir,
    render_and_print,
    add_no_black_formatting,
    add_option,
)
from api_generator.apidefs.definitions import ApiDef


def is_api_def(obj):
    """Checks if the given object is an instance of :class:`ApiDef`.

    Args:
        obj: the object to check.

    Returns:
        bool: True if the given object is an instance of ApiDef, or one of its inherited
            class.

    """
    return isinstance(obj, ApiDef)


class ApiOrTestGenerator(object):
    """Handles the generation of the code for the provided templates directory, using
    the provided API definition. The latter should be given as the Python path to its
    Krake data module. A name is also given to the generator.

    The generator prints the content of a file. This should be put into a Python file,
    which can then be integrated into Krake in the chosen package.

    The following syntax should be used:

    .. code:: bash

        python -m api_generator <generator_name> <module_path> [<other_opts>...] \
            > <module.path>

    For example:

    .. code:: bash

        python -m api_generator api_server krake.apidefs.core

    Args:
        name (str): name of the generator.
        template_path (str): name of the template main file in the directory.
        description (str): small description of the current generator, to be included in
            the argument's help for the generator.

    """

    def __init__(self, name, template_path, description):
        self.name = name
        self.template_path = template_path
        self.description = description

    def generate_code(
        self, data_path, templates_dir, no_black, operations=None, resources=None
    ):
        """From a given Krake API definition path, prints a Python file that contains the
        code from the templates directory, with the given API definition applied, to be
        included in Krake.

        Args:
            data_path (str): The Python module path to the data structures. For example:
                "krake.data.my_api".
            templates_dir (str): path of the directory in which the template is stored.
            no_black (bool): if True, the black formatting will not be used.
            operations (list[str]): list of names of operations that the generator
                should display. If empty, all operations are processed and displayed.
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
        render_and_print(
            templates_dir, self.template_path, parameters, no_black=no_black
        )

    def add_apidef_subparser(self, subparsers):
        """Adds the subparser that is specific for the generation of the current
        generator, as well as its arguments.

        Args:
            subparsers: the subparsers on which an additional parser should be added.

        """
        parser = subparsers.add_parser(
            self.name,
            help=(
                f"Generation of the {self.description}, using an API definition"
                " as base."
            ),
        )

        parser.add_argument(
            "data_path",
            help=(
                "Path to the module to parse for API definitions. "
                "Syntax: '<path>.<to>.<module>'. Example: 'krake.api.apidefs.foo'."
            ),
        )
        add_templates_dir(parser=parser, default=get_default_template_dir())

        add_no_black_formatting(parser=parser)

        add_operations_to_keep(parser=parser)
        add_resources_to_keep(parser=parser)

        parser.set_defaults(generator=self.generate_code)


def add_operations_to_keep(parser, **kwargs):
    """Adds an "--operations" option for the given parser, which can be reused several
    times. The resulting list of strings can then be used for a list of operations to
    display.

    Args:
        parser (argparse.ArgumentParser): parser to which the option will be added.
        **kwargs (dict): additional arguments to give to the parser.

    """
    add_option(
        parser,
        short="-o",
        name="--operations",
        help=(
            "Names of operations from the API definition resources (any case) that"
            " will be displayed by the generator. Can be used several times. Empty to"
            " keep all operations."
        ),
        action="append",
        **kwargs,
    )


def _keep_given_operations(resource, operations):
    """From the provided resource, removes all operations which are not in the provided
    operations list.

    Args:
        resource: API definition resource or subresource.
        operations (list[str]): list of operations name to keep.

    """
    for res_operation in list(resource.operations):
        if res_operation.name.lower() not in operations:
            resource.operations.remove(res_operation)


def filter_operations(api_definition, keep_operations):
    """From an API definition, removes all operations on all resources and sub-resources
    that are not in the provided operations.

    Args:
        api_definition (krake.apidefs.definitions.ApiDef): API definition extracted from
            a module file.
        keep_operations (list[str]): list of operations name to keep.

    """
    if len(set(keep_operations)) != len(keep_operations):
        sys.exit("Error: some operations to keep are duplicates.")

    keep_operations = [op.lower() for op in keep_operations]

    for resource in api_definition.resources:
        _keep_given_operations(resource, keep_operations)

        for sub_resource in resource.subresources:
            _keep_given_operations(sub_resource, keep_operations)


def add_resources_to_keep(parser, **kwargs):
    """Adds an "--resources" option for the given parser, which can be reused several
    times. The resulting list of strings can then be used for a list of resources to
    display.

    Args:
        parser (argparse.ArgumentParser): parser to which the option will be added.
        **kwargs (dict): additional arguments to give to the parser.

    """
    add_option(
        parser,
        short="-r",
        name="--resources",
        help=(
            "Names of resources from the API definition (any case) that will be"
            " displayed by the generator. Can be used several times. Empty to keep all"
            " resources."
        ),
        action="append",
        **kwargs,
    )


def filter_resources(api_definition, keep_resources):
    """From an API definition, removes all resources on all resources and sub-resources
    that are not in the provided resources.

    Args:
        api_definition (krake.apidefs.definitions.ApiDef): API definition extracted from
            a module file.
        keep_resources (list[str]): list of resources name to keep.

    """
    if len(set(keep_resources)) != len(keep_resources):
        sys.exit("Error: some resources to keep are duplicates.")

    keep_resources = [op.lower() for op in keep_resources]

    for resource in list(api_definition.resources):
        if (
            resource.singular.lower() not in keep_resources
            and resource.snake_case_singular.lower() not in keep_resources
        ):
            api_definition.resources.remove(resource)
