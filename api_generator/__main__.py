"""This module should be used to generate code for a newly added API in Krake, or after
modifying an existing one. It allows the creation of:

 * the API definition of an API, using the resources defined in ``krake.data``;

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Code generator for the Krake API.")
    subparsers = parser.add_subparsers()

    add_apidef_subparser(subparsers)

    args = parser.parse_args()

    if not hasattr(args, "generator"):
        # In case a user calls the script without any arguments, "generator" is not set
        parser.print_help()
    else:
        generator = args.generator
        del args.generator
        generator(**vars(args))
