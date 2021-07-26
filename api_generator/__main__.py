"""This module should be used to generate code for a newly added API in Krake, or after
modifying an existing one. It allows the creation of:

 * the API definition of an API, using the resources defined in ``krake.data``;
 * the API server code for Krake using the given API definition;
 * the API client code for Krake using the given API definition.
 * the unit tests for Krake clients using the given API definition.
 * the unit tests for the Krake server using the given API definition.

To use it, the ``extras_requires`` called ``api_generator`` of the ``setup.py`` must be
installed. Use the following:

.. code:: bash

    pip install "krake/[api_generator]"


To see all possible generators, use:

.. code:: bash

    python -m api_generator -h

To use a specific generator:

.. code:: bash

    python -m api_generator <generator> <gen_opt_1> ... <gen_opt_n> > <result_file>

The potential values of ``<gen_opt_X>`` are described in more details in the
documentation of the module for the specific generators.

"""
import argparse

from .api_definition import add_apidef_subparser
from .api_or_test_generator import ApiOrTestGenerator


def add_generators(parsers):
    api_client = ApiOrTestGenerator(
        "api_client", "api_client/main.jinja", "API client code"
    )
    api_client.add_apidef_subparser(parsers)

    api_server = ApiOrTestGenerator(
        "api_server", "api_server/main.jinja", "API server-side code"
    )
    api_server.add_apidef_subparser(parsers)

    test_client = ApiOrTestGenerator(
        "test_client", "test_client/main.jinja", "unit tests for the API client"
    )
    test_client.add_apidef_subparser(parsers)

    test_server = ApiOrTestGenerator(
        "test_server", "test_server/main.jinja", "unit tests for the API server code"
    )
    test_server.add_apidef_subparser(parsers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Code generator for the Krake API.")
    subparsers = parser.add_subparsers()

    add_apidef_subparser(subparsers)
    add_generators(subparsers)

    args = parser.parse_args()

    if not hasattr(args, "generator"):
        # In case a user calls the script without any arguments, "generator" is not set
        parser.print_help()
    else:
        generator = args.generator
        del args.generator
        generator(**vars(args))
