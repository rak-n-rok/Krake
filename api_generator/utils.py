import importlib
import inspect
import os
import sys
from argparse import Action

import black
from jinja2 import FileSystemLoader, Environment, TemplateNotFound

from .apidefs.definitions import ApiDef


def is_api_def(obj):
    """Check if the given object is an instance of :class:`ApiDef`.

    Args:
        obj: the object to check.

    Returns:
        bool: True if the given object is an instance of ApiDef, or one of its inherited
            class.

    """
    return isinstance(obj, ApiDef)


def get_data_classes(data_path, condition=None):
    """Get a list of references to the objects defined in the given module. The classes
    are filtered using the given condition.

    Args:
        condition (callable): a function with signature "object -> bool". If the
            condition is True, the object from the module is filtered and given in the
            output list. Default: all objects are returned.
        data_path (str): The Python module path to the data structures. For example:
            "krake.data.my_api".

    Returns:
        list[krake.apidefs.definitions.ApiDef]: the list of API definitions extracted
            from the module at the given path.

    Raises:
        SystemExit: if the given module path is not valid.

    """
    if not condition:

        def condition(x):
            return True

    try:
        api_module = importlib.import_module(data_path)
    except ModuleNotFoundError:
        sys.exit(f"ERROR: Module {data_path!r} cannot be found.")

    # Get all objects defined in the module and keep only the persisted classes.
    return [obj for name, obj in inspect.getmembers(api_module, condition)]


def add_option(parser, name, help, short=None, default=None, action=None, **kwargs):
    """Define a new option that is accepted by the parser. One of default or action
    parameter has to be given.

    Args:
        parser (ArgumentParser): argument parser on which the new option will be added
        name (str): the name of the newly added option.
        help (str): what will be printed in the help. The default value, if given,
            will be printed along.
        short (str): short version of the newly added option
        default (Any, optional): the default value that will be given to the option.
        action (str, optional): the argparse action to apply.
        kwargs (dict, optional): additional options given to the parser.

    """
    if not default and not action:
        sys.exit(f"For option {name}, both default and action cannot be empty")

    option = name.replace("_", "-")

    if default:
        help = f"{help} Default: '{default}'"
        # Prevent "None" to be added as default value if no default value is wanted
        kwargs["default"] = default

    if short:
        parser.add_argument(short, option, action=action, help=help, **kwargs)
    else:
        parser.add_argument(option, action=action, help=help, **kwargs)


class StoreDict(Action):
    """Action storing <key=value> pairs in a dictionary.

    Example:
        .. code:: python

            parser = argparse.ArgumentParser()
            parser.add_argument(
                '--foo', action=StoreDict
            )
            args = parser.parse_args('--foo label=test --foo lorem=ipsum')
            assert argparse.Namespace(foo={'label': 'test', 'lorem': 'ipsum'}) == args

    """

    def __init__(self, option_strings, dest, nargs=None, metavar="KEY=VALUE", **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")
        super().__init__(option_strings, dest, metavar=metavar, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest)
        if items is None:
            items = {}
            setattr(namespace, self.dest, items)

        key, value = values.split("=", 1)
        items[key] = value


def add_templates_dir(parser, default=None, **kwargs):
    """Add a generic "templates_dir" option for the given parser, with the given default
    value.

    Args:
        parser (argparse.ArgumentParser): parser to which the option will be added.
        default (Path-like, optional): default path for the templates directory.
        **kwargs (dict): additional arguments to give to the parser.

    """
    if not default:
        default = get_default_template_dir()
    add_option(
        parser,
        name="--templates-dir",
        help="Directory where the Jinja2 template are stored.",
        default=default,
        **kwargs,
    )


def add_template_path(parser, default=None, **kwargs):
    """Add a generic "template_path" option for the given parser, with the given default
    value. This path mus be relative to the template directory.

    Args:
        parser (argparse.ArgumentParser): parser to which the option will be added.
        default (Path-like, optional): default path for the template path in the
            template directory.
        **kwargs (dict): additional arguments to give to the parser.

    """
    add_option(
        parser,
        name="--template-path",
        help="Relative path of the template in the template directory.",
        default=default,
        **kwargs,
    )


def add_no_black_formatting(parser, **kwargs):
    """Add a generic "--no-black" option for the given parser, as an optional argument.
    Specifying this option will set this variable to True.

    Args:
        parser (argparse.ArgumentParser): parser to which the option will be added.
        **kwargs (dict): additional arguments to give to the parser.

    """
    add_option(
        parser,
        name="--no-black",
        help="If set, the black formatting will not be applied to the output.",
        action="store_true",
        **kwargs,
    )


def get_default_template_dir():
    """Generate the complete path to the template directory for the API generator

    Returns:
        str: the absolute path to the default template directory.

    """
    directory = os.path.dirname(__file__)
    return os.path.join(directory, "templates")


def get_template(templates_dir, template_path):
    """Retrieve the template object associated with the file with the given name in the
    given directory.

    Args:
        templates_dir (str): path of the directory in which the template is stored.
        template_path (str): name of the template.

    Returns:
        jinja2.Template: the template, as managed by Jinja2.

    Raises:
        SystemExit: if the template cannot be found.

    """
    file_loader = FileSystemLoader(templates_dir)
    env = Environment(loader=file_loader)

    try:
        template = env.get_template(template_path)
    except TemplateNotFound:
        sys.exit(f"ERROR: Template {template_path!r} not found in {templates_dir!r}.")
    return template


def render_and_print(templates_dir, template_path, parameters, no_black=False):
    """Apply the given parameters to the given template and display the formatted
    result.

    Args:
        templates_dir (str): path of the directory in which the template is stored.
        template_path (str): name of the template.
        parameters (dict): values to give to the template for rendering.
        no_black (bool): if False, format the output of the template rendering using
            the black utility. Otherwise, just print the raw rendering.

    """
    template = get_template(templates_dir, template_path)
    output = template.render(**parameters)

    if not no_black:
        output = black.format_str(output, mode=black.FileMode())

    print(output)


def add_operations_to_keep(parser, **kwargs):
    """Add an "--operations" option for the given parser, which can be reused several
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
    """From the provided resource, remove all operations which are not in the provided
    operations list.

    Args:
        resource: API definition resource or subresource.
        operations (list[str]): list of operations name to keep.

    """
    for res_operation in list(resource.operations):
        if res_operation.name.lower() not in operations:
            resource.operations.remove(res_operation)


def filter_operations(api_definition, keep_operations):
    """From an API definition, remove all operations on all resources and sub-resources
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
    """Add an "--resources" option for the given parser, which can be reused several
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
    """From an API definition, remove all resources on all resources and sub-resources
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
