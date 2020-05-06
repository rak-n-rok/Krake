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

    python -m krake.api_generator -h

To use a specific generator:

.. code:: bash

    python -m krake.api_generator <generator> <option_1> ... <option_n> > <result_file>

"""
import argparse

import krake.api_generator.api_definition as api_definition
import krake.api_generator.api_client as api_client
import krake.api_generator.api_server as api_server
import krake.api_generator.test_client as test_client
import krake.api_generator.test_server as test_server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Code generator for the Krake API.")
    subparsers = parser.add_subparsers()

    api_definition.add_apidef_subparser(subparsers)
    api_client.add_apidef_subparser(subparsers)
    api_server.add_apidef_subparser(subparsers)
    test_client.add_apidef_subparser(subparsers)
    test_server.add_apidef_subparser(subparsers)

    args = parser.parse_args()

    if not hasattr(args, "generator"):
        # In case a user calls the script without any arguments, "generator" is not set
        parser.print_help()
    else:
        generator = args.generator
        del args.generator
        generator(**vars(args))
