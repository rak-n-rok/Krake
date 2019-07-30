"""rok output formatters.

The API of this module is a decorator factory function :func:`printer` that
can be used to annotate functions and print their return value in a format-
specific way.
"""
import sys
import json
import yaml
from datetime import datetime
from itertools import chain

from dateutil.parser import parse
from functools import wraps

from texttable import Texttable


def printer(file=sys.stdout, **formatters):
    """Decorator factory for printing formatted return values.

    An additional ``format`` keyword argument is appended to the keyword
    arguments of the wrapped function. The specified ``format`` key is used to
    look up the formatter function in the additional keyword arguments. The
    signature of formatters is:

    .. function:: my_formatter(value, file, is_cluster)

        :param value: Return value of the wrapped function
        :param file: File-like object where the output should be
            written
        :param is_cluster: True if the payload contains clusters.
            Default: False.

    :func:`print_generic_json` is used as default formatter for the ``json``
    format key.

    :func:`print_generic_yaml` is used as default formatter for the ``yaml``
    format key.

    The return value of the wrapped function is is transparently passed back
    to the caller.

    Args:
        file (file-like object, optional): Output file formatted output is
            sent to. Default: ``sys.stdout``
        **formatters: All additional keyword arguments are used as lookup table
            for formatter functions.

    Returns:
        callable: Decorator that can be used to wrap command functions and format
        the returned value

    Examples:
        .. code:: python

            from rok.formatters import printer

            def print_to_table(value, out):
                ...

            @printer(sys.stderr, table=print_to_table)
            def my_function(arg):
                response = requests.get(...)
                returns response.json()

            # This will print the corresponding table with print_to_table(). The
            # response object itself is passed back
            resp = my_function(arg, format='table')

            # Use the default JSON formatter
            my_function(arg, format='json')

            # Use the default YAML formatter
            my_function(arg, format='yaml')

    """
    formatters.setdefault("json", print_generic_json)
    formatters.setdefault("yaml", print_generic_yaml)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            is_cluster = func.__name__.endswith("clusters")
            format_type = kwargs.pop("format", "yaml")
            value = func(*args, **kwargs)

            try:
                formatter = formatters[format_type]
            except KeyError:
                raise KeyError(f"Unknown format {format_type!r}")

            formatter(value, file, is_cluster=is_cluster)

        return wrapper

    return decorator


def print_generic_json(value, file, **kwargs):
    """Use the standard :func:`json.dump` function to serialize the passed
    values into JSON. The output uses indentation and keys are sorted.
    """
    json.dump(value, file, indent=2, sort_keys=True)
    print(file=file)  # New line


def print_generic_yaml(value, file, **kwargs):
    """Use the standard :func:`yaml.dump` function to serialize the passed
    values into YAML.
    """
    yaml.dump(value, default_flow_style=False, stream=file)


def format_datetime(time_str):
    """Formats complex time string to the human readable form

    Args:
        time_str (str): Time string

    Returns:
        str: Formatted time string to the human readable YY-mm-dd H:M:S format

    """
    return datetime.strftime(parse(time_str), "%Y-%m-%d %H:%M:%S")


def print_list_table(payload, file, is_cluster=False):
    """Print list of items from payload as ASCII table

    Args:
        payload (dict): Payload to be processed to the ASCII table
        file (file-like object): a file-like object (stream). Default: sys.stdout
        is_cluster (bool, optional): True if the payload contains clusters.
            Default: False.

    """
    if is_cluster:
        spec_key = spec_header = "kind"
    else:
        spec_header = "deployment"
        spec_key = "cluster"

    table = Texttable()
    cols_wide = ["40", "15", "13", "29", "29", "29"]
    headers = ["uuid", "name", spec_header, "created", "modified", "status"]

    for item in payload:
        metadata = item["metadata"]
        spec = item["spec"][spec_key]
        status = item["status"]
        table.add_row(
            [
                metadata["uid"],
                metadata["name"],
                spec.split("/")[-1] if spec else None,
                format_datetime(status["created"]),
                format_datetime(status["modified"]),
                status["state"],
            ]
        )

    table.header(headers)
    table.set_cols_width(cols_wide)
    table.set_cols_align(len(cols_wide) * "l")
    table.set_cols_valign(len(cols_wide) * "c")
    table.set_deco(Texttable.BORDER | Texttable.HEADER | Texttable.VLINES)

    print(table.draw(), file=file)
    print(file=file)  # New line


def print_detail_table(payload, file, **kwargs):
    """Print an item detail as ASCII table

    Args:
        payload (dict): Payload to be processed to the ASCII table
        file (file-like object): a file-like object (stream). Default: sys.stdout
        **kwargs: Arbitrary keyword arguments

    """
    field_skip = ["manifest"]
    table = Texttable()
    cols_wide = ["40", "50"]
    table.header(["field", "value"])

    table.set_cols_width(cols_wide)
    table.set_cols_align(len(cols_wide) * "l")
    table.set_cols_valign(len(cols_wide) * "c")

    table.set_deco(Texttable.BORDER | Texttable.HEADER | Texttable.VLINES)

    rows = []
    for field, value in chain(
        payload["metadata"].items(), payload["spec"].items(), payload["status"].items()
    ):
        if field in field_skip or field in [field for field, _ in rows]:
            continue

        rows.append([field, value])

    table.add_rows(sorted(rows, key=lambda row: row[0], reverse=True), header=False)
    print(table.draw(), file=file)
    print(file=file)  # New line


# FIXME: The table implementation should be decoupled for every resource.
#   There should not be and if-then-else logic inside the table formatting
#   function.
print_detail = printer(table=print_detail_table)
print_list = printer(table=print_list_table)
