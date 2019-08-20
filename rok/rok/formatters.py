"""rok output formatters.

The API of this module is a decorator factory function :func:`printer` that
can be used to annotate functions and print their return value in a format-
specific way.
"""
import sys
import json
import yaml
import os
from datetime import datetime

from dateutil.parser import parse
from functools import wraps

from requests import HTTPError
from texttable import Texttable


def printer(file=sys.stdout, **formatters):
    """Decorator factory for printing formatted return values.

    An additional ``format`` keyword argument is appended to the keyword
    arguments of the wrapped function. The specified ``format`` key is used to
    look up the formatter function in the additional keyword arguments. The
    signature of formatters is:

    .. function:: my_formatter(value, file)

        :param value: Return value of the wrapped function
        :param file: File-like object where the output should be
            written

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
            format_type = kwargs.pop("format", "yaml")

            try:
                value = func(*args, **kwargs)
            except HTTPError as he:
                sys.exit(str(he))

            try:
                formatter = formatters[format_type]
            except KeyError:
                raise KeyError(f"Unknown format {format_type!r}")

            formatter(value, file)

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


class Cell(object):
    """Declaration of a single text table cell.

    Args:
        attribute (str): Attribute that should displayed in this cell. Nested
            attributes are supported with dot notation.
        width (int, optional): Width of the cell. Used when the table displays
            the cell horizontally.
        name (str, optional): Name that is used in the header of as field
            name. Defaults to the Python attribute name of the cell.
        formatter (callable, optional): Formatting function that is used to
            transform the mapped attribute.

    """

    def __init__(self, attribute, width=None, name=None, formatter=None):
        self.attribute = attribute
        self.width = width
        self.name = name
        self.formatter = formatter

    def load_attribute(self, obj):
        """Load an attribute from a dictionary. :attr:`attribute` allows
        nested attributes. Hence, item access is recursed.

        Args:
            obj (dict): Data dictionary from witch the cell attribute should
                be loaded.

        Returns:
            Item from the data object

        Raises:
            KeyError: If a key can not be found.

        """
        for key in self.attribute.split("."):
            obj = obj[key]
        return obj

    def render(self, data):
        """Return the string content of the cell. The corresponding attribute
        is loaded from the data object.

        Args:
            data (object): Data object from which the corresponding cell
                attribute is loaded

        Returns:
            str: Content of the cell

        """
        attr = self.load_attribute(data)

        if self.formatter is None:
            return attr
        return self.formatter(attr)


class Table(object):
    """Declarative base class for table printers.

    It implements the Python :meth:`__call__` protocol. This means instances
    can be used as functions. This allows their usage as formatters in
    :func:`printer.`

    Examples:
        .. code:: python

            from rok,formatters import Table, Cell

            class BookTable(Table):
                isbn = Cell("isbn")
                title = Cell("title")
                author = Cell("author")


            book = {
                "isbn": 42,
                "title": "The Hitchhiker's Guide to the Galaxy",
                "author": "Douglas Adams",
            }

            table = BookTable()
            table(book)

    Two different layouts are supported depending if the table is used to
    format a list of objects or a single object.

    Horizontal layout
        is used to print a list of object. A header is printed with all cell
        names and every proceeding row contains the formatted attributes of
        a single item of the list (see :meth:`draw_many`).
    Vertical layout
        is used to print a single element. The table contains to columns.
        The left column contains the attribute names and the right column
        the corresponding values (see :meth:`draw`).

    Attributes:
        cells (Dict[str, Cell]): Mapping of all cell attributes of
            the class.

    Args:
        many (bool, optional): Controls the horizontal or vertical layout.

    """

    def __init__(self, many=False):
        self.many = many

    def __init_subclass__(cls):
        """Collect :class:`Cell` attributes and assignes it to the
        :attr:`cells` attribute.

        Args:
            cls (type): Class that is being initialized

        """
        super().__init_subclass__()

        cells = {}

        # Fetch all we do not use "inspect.getmembers" because it orders the
        # attributes by name.
        for c in cls.__mro__:
            # We use "__dict__" here instead of dir() because we want to
            # preserve the declaration order of attributes
            for name, attr in c.__dict__.items():
                if isinstance(attr, Cell):
                    cells[name] = attr

        # Set name of unnamed cells to their Python attribute name
        for name, cell in cells.items():
            if cell.name is None:
                cell.name = name

        cls.cells = cells

    def __call__(self, data, file):
        """Print a table from the passed data

        Args:
            data (object): Data that should be formatted
            file: File-like object where the output should be written

        """
        # @see https://stackoverflow.com/a/41864359/2467158
        width, height = os.get_terminal_size(0)
        table = Texttable(max_width=width)

        if self.many:
            self.draw_many(table, data, file)
        else:
            self.draw(table, data, file)

    def draw(self, table, data, file):
        """Print a data item.

        Args:
            table (texttable.Texttable): Table that is used for formatting
            data (object): Data object that will be used to populate the table
            file: File-like object where the output should be written

        """
        table.set_cols_align("ll")
        table.set_cols_valign("cc")
        table.set_deco(Texttable.BORDER | Texttable.VLINES)

        for cell in self.cells.values():
            table.add_row([cell.name, cell.render(data)])

        print(table.draw(), file=file)

    def draw_many(self, table, data, file):
        """Print a list of data item.

        Args:
            table (texttable.Texttable): Table that is used for formatting
            data (object): List of items used to populate the table
            file: File-like object where the output should be written

        """
        table.header([name for name in self.cells.keys()])
        # table.set_cols_width([cell.width for cell in self.cells.values()])
        table.set_cols_align(len(self.cells) * "l")
        table.set_cols_valign(len(self.cells) * "c")
        table.set_deco(Texttable.BORDER | Texttable.HEADER | Texttable.VLINES)

        if self.cells:
            for item in data:
                table.add_row([cell.render(item) for cell in self.cells.values()])

        print(table.draw(), file=file)


class BaseTable(Table):
    """Standard base class for declarative table formatters.
    Defines a couple of default resource attributes.

    """

    name = Cell("metadata.name")
    namespace = Cell("metadata.namespace")
    user = Cell("metadata.user")
    created = Cell("status.created", formatter=format_datetime)
    modified = Cell("status.modified", formatter=format_datetime)
    state = Cell("status.state")
