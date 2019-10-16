"""This module defines a declarative API for Python's standard :mod:`argparse`
module.
"""
import copy
from argparse import ArgumentParser

import argparse


class ParserSpec(object):
    """Declarative parser specification for Python's standard :mod:`argparse`
    module.

    Example:
        .. code:: python

            from rok.parser import ParserSpec, argument

            spec = ParserSpec(prog="spam", description="Spam command line interface")

            @spec.command("spam", help="Spam your shell")
            @argument("-n", type=int, default=42, help="How often should I spam?")
            @argument("message", help="Spam message")
            def spam(n, message):
                for _ in range(n):
                    print(message)

            parser = spec.create_parser()
            args = parser.parse_args()

        Specifications can be nested:

        .. code:: python

            eggs = ParserSpec("eggs", aliases=["eg"], help="... and eggs")

            @eggs.command("spam")
            def eggs_spam():
                while True:
                    print("spam")
                    print("eggs")

            spec.add_spec(eggs)

    Args:
        *args: Positional arguments that will be passed to either
            :class:`argparse.ArgumentParser` or subparsers.
        *kwargs: Keyword arguments that will be passed to either
            :class:`argparse.ArgumentParser` or subparsers.

    """

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.commands = {}
        self.specs = []

    def command(self, name, *args, **kwargs):
        """Decorator function for commands registering the name, positional
        and keyword arguments for a subparser.

        Args:
            str (name): Name of the command that will be used in the command
                line.
            *args: Positional arguments for the subparser
            **kwargs: Keyword arguments for the subparser

        Returns:
            callable: Decorator for functions that will be registed as
            ``command`` default argument on the subparser.
        """

        def decorator(fn):
            if name is self.commands:
                raise RuntimeError(f"Command {name!r} already registered")
            self.commands[name] = (fn, args, kwargs)
            return fn

        return decorator

    def add_spec(self, subparser):
        """Register a another specification as subparser

        Args:
            subparser (ParserSpec): Sub-specification defining subcommands

        """
        self.specs.append(subparser)

    def subparser(self, *args, **kwargs):
        """Create a subspecification and automatically register it via :meth:`add_spec`

        Args:
            *args: Positional arguments for the specification
            **kwargs: Keyword arguments for the specification

        Returns:
            ParserSpec: The new subspecification for subcommands

        """
        parser = self.__class__(*args, **kwargs)
        self.add_spec(parser)
        return parser

    def create_parser(self, parent=None):
        """Create a standard Python parser from the specification

        Args:
            parent (optional): argparse subparser that should be used instead
                of creating a new root :class:`argparse.ArgumentParser`

        Returns:
            argparse.ArgumentParser: Standard Python parser

        """
        if parent is None:
            parser = ArgumentParser(*self.args, **self.kwargs)
        else:
            parser = parent.add_parser(*self.args, **self.kwargs)

        commands = parser.add_subparsers(metavar="<command>", dest="command")
        commands.required = True

        for name, (fn, parser_args, parser_kwargs) in self.commands.items():
            parser = commands.add_parser(name, *parser_args, **parser_kwargs)
            parser.set_defaults(command=fn)

            for argument_args, argument_kwargs in getattr(fn, "parser_arguments", []):
                parser.add_argument(*argument_args, **argument_kwargs)

        for subparser in self.specs:
            subparser.create_parser(parent=commands)

        return parser

    def __repr__(self):
        return f"<ParserSpec args={self.args} kwargs={self.kwargs}>"


def argument(*args, **kwargs):
    """Decorator function for standard :mod:`argparse` arguments.

    The passed arguments and keyword arguments are stored as tuple in a
    ``parser_arguments`` attribute of the decorated function. This list will
    be reused by class:`ParserSpec` to add arguments to decorated commands.

    Args:
        *args: Positional arguments that should be passed to
            :meth:`argparse.ArgumentParser.add_argument`.
        **kwargs: Keyword arguments that should be passed to
            :meth:`argparse.ArgumentParser.add_argument`.

    Returns:
        callable: A decorator that can be used to decorate a command function.

    """

    def decorator(fn):
        if not hasattr(fn, "parser_arguments"):
            fn.parser_arguments = []
        fn.parser_arguments.append((args, kwargs))
        return fn

    return decorator


class StoreDictPairInList(argparse.Action):
    """Custom action to store and validate dict <key=value> pairs in a list

    Example:
        .. code:: python

            parser = argparse.ArgumentParser()
            parser.add_argument(
                '--foo', metavar="KEY=VALUE", action=StoreDictPairInList
            )
            args = parser.parse_args('--foo label=test'.split())
            assert argparse.Namespace(foo=[{'label': 'test'}]) == args

    """

    def __call__(self, parser, namespace, values, option_string=None):
        items = copy.copy(self.ensure_value(namespace, self.dest, []))
        split_value = values.split("=", 1)
        if len(split_value) != 2:
            print(f"Error: Malformed <key=value> format of {values!r}.")
            raise SystemExit(1)
        items.append({key: value for key, value in [split_value]})
        setattr(namespace, self.dest, items)

    @staticmethod
    def ensure_value(namespace, name, value):
        if getattr(namespace, name, None) is None:
            setattr(namespace, name, value)
        return getattr(namespace, name)


arg_formatting = argument(
    "-f",
    "--format",
    choices=["table", "json", "yaml"],
    default="table",
    help="Format of the output, table by default",
)
arg_labels = argument(
    "-l",
    "--label",
    dest="labels",
    default=[],
    metavar="KEY=VALUE",
    action=StoreDictPairInList,
    help="Label <key=value>. Can be specified multiple times",
)
arg_constraints_labels = argument(
    "-L",
    "--constraint-label",
    dest="constraints_labels",
    default=[],
    action=StoreDictPairInList,
    help="Constraint label <key=value>. Can be specified multiple times",
)
arg_namespace = argument(
    "-n", "--namespace", help="Namespace of the resource. Defaults to user"
)
arg_metric = argument(
    "--metric",
    "-m",
    dest="metrics",
    action="append",
    default=[],
    help="Metric name. Can be specified multiple times",
)
