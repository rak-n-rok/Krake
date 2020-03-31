import os
import sys
from argparse import Action


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
        help=f"Relative path of the template in the template directory.",
        default=default,
        **kwargs,
    )


def get_default_template_dir():
    """Generate the complete path to the template directory for the API generator

    Returns:
        str: the absolute path to the default template directory.

    """
    dir = os.path.dirname(__file__)
    return os.path.join(dir, "templates")
