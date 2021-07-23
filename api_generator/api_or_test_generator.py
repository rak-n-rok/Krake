from .utils import (
    add_templates_dir,
    get_data_classes,
    get_default_template_dir,
    render_and_print,
    add_no_black_formatting,
)
from krake.apidefs.definitions import ApiDef


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

    def generate_code(self, data_path, templates_dir, no_black):
        """From a given Krake API definition path, prints a Python file that contains the
        code from the templates directory, with the given API definition applied, to be
        included in Krake.

        Args:
            data_path (str): The Python module path to the data structures. For example:
                "krake.data.my_api".
            templates_dir (str): path of the directory in which the template is stored.
            no_black (bool): if True, the black formatting will not be used.

        """
        api_definitions = get_data_classes(data_path, condition=is_api_def)
        assert len(api_definitions) == 1, "Only one API should be defined."
        api_definition = api_definitions[0]

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

        parser.set_defaults(generator=self.generate_code)
