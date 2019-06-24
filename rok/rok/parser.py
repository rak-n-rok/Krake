"""This module defines the root parser for the rok command line interface.
Other modules add new subparsers to this parser:

Example:
    .. code:: python

        from rok.parser import subparsers

        platform = subparsers.add_parser("platform", help="Manage platform applications")
        commands = platform.add_subparsers(help="Platform subcommands", dest="command")
        commands.required = True

"""
from argparse import ArgumentParser


parser = ArgumentParser(prog="rok", description="Command line interface for Krake")
subparsers = parser.add_subparsers(help="Application types", dest="command")
subparsers.required = True
