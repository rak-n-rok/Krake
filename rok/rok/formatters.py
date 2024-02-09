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

    The return value of the wrapped function is transparently passed back
    to the caller. If :obj:`None` is returned from the wrapped function, this
    the output is considered *empty*. No formatter will be called and nothing
    is printed to stdout.

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
            format_type = kwargs.pop("output", "yaml")

            try:
                value = func(*args, **kwargs)
            except HTTPError as he:
                if "application/problem+json" in he.response.headers.get(
                    "content-type", ""
                ):
                    problem = json.dumps(he.response.json(), indent=2, sort_keys=True)
                    sys.exit(problem)

                sys.exit(str(he))

            if value is None:
                return

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
        time_str (str, None): Time string

    Returns:
        str: Formatted time string to the human readable YY-mm-dd H:M:S format

    """
    if time_str is None:
        return None
    return datetime.strftime(parse(time_str), "%Y-%m-%d %H:%M:%S")


def bool_formatter(attr):
    """Format a boolean into a more readable format

    Args:
        attr (bool): a boolean attribute

    Returns:
        str: the string "True" or "False", depending of the boolean value of the given
            attribute.

    """
    return str(attr)


def nodes_formatter(
    attr, pid_pressure=False, disk_pressure=False, memory_pressure=False
):
    """Format a cluster nodes into a "X/Y" format.

    "X" represents the sum of nodes in the following node conditions:
    1. Sum of ready nodes (default)
    2. Sum of nodes under PID pressure
    3. Sum of nodes under DISK pressure
    4. Sum of nodes under MEMORY pressure

    "Y" represents the total sum of nodes.

    Args:
        attr (list): an attribute with nodes elements
        pid_pressure (bool, optional): If the sum of nodes under PID pressure,
            should be returned. Defaults to False.
        disk_pressure (bool, optional): If the sum of nodes under DISK pressure,
            should be returned. Defaults to False.
        memory_pressure (bool, optional): If the sum of nodes under MEMORY pressure,
            should be returned. Defaults to False.

    Returns:
        str: Formatted string with the format "X/Y".

    """
    if not attr:
        return str(None)

    node_count_total = node_count_ready = len(attr)
    node_count_memory_pressure = 0
    node_count_disk_pressure = 0
    node_count_pid_pressure = 0

    for node in attr:
        for condition in node["status"]["conditions"]:
            if (
                condition["type"].lower().endswith("pressure")
                and condition["status"] == "True"
            ):
                if condition["type"].lower() == "pidpressure":
                    node_count_pid_pressure += 1

                if condition["type"].lower() == "diskpressure":
                    node_count_disk_pressure += 1

                if condition["type"].lower() == "memorypressure":
                    node_count_memory_pressure += 1

            if condition["type"].lower() == "ready" and condition["status"] != "True":
                node_count_ready -= 1

    if pid_pressure:
        return "{0}/{1}".format(node_count_pid_pressure, node_count_total)

    if disk_pressure:
        return "{0}/{1}".format(node_count_disk_pressure, node_count_total)

    if memory_pressure:
        return "{0}/{1}".format(node_count_memory_pressure, node_count_total)

    return "{0}/{1}".format(node_count_ready, node_count_total)


def pods_formatter(attr):
    if not attr:
        return str(None)

    if attr["completed_pods"] is not None:
        return "{0} active / {1} failed / {2} succeeded / {3} desired".\
            format(attr["running_pods"], attr["failed_pods"],
                   attr["completed_pods"], attr["desired_pods"])
    elif attr["desired_pods"] is not None:
        return "{0} active / {1} desired".\
            format(attr["running_pods"], attr["desired_pods"])


def dict_formatter(attr):
    """Format a dictionary into a more readable format

    Args:
        attr (dict): an attribute with key:value elements

    Returns:
        str: Formatted dict with the format ``<key>: <value>`` with one line per
        element.

    """
    if not attr:
        return str(None)

    formatted_attr = []
    for key, value in attr.items():
        formatted_value = list_formatter(value) if isinstance(value, list) else value
        formatted_attr.append(f"{key}: {formatted_value}\n")

    return "".join(formatted_attr)[:-1]  # Remove the last end of line character


def metrics_formatter(attr):
    """Format a list of static metrics into a more readable format

    Args:
        attr(list): an list of tuples (key,value)

    Returns:
        str: Formatted labels list

    """
    if not attr:
        return str(None)

    formatted_attr = []
    for item in attr:
        formatted_item = item["name"] + "=" + str(item["weight"])
        formatted_attr.append(f"{formatted_item}\n")

    return "".join(formatted_attr)[:-1]  # Remove the last end of line character


def labels_formatter(attr):
    """Format a list of labels into a more readable format

    Args:
        attr(list): an list of tuples (key,value)

    Returns:
        str: Formatted labels list
    """
    if not attr:
        return str(None)

    formatted_attr = []
    for item in attr:
        formatted_item = item["value"] + "=" + item["key"]
        formatted_attr.append(f"{formatted_item}\n")

    return "".join(formatted_attr)[:-1]  # Remove the last end of line character


def list_formatter(attr):
    """Format a list into a more readable format

    Args:
        attr (list): an attribute with items

    Returns:
        str: Formatted list

    """
    if not attr:
        return str(None)

    formatted_attr = []
    for item in attr:
        formatted_item = dict_formatter(item) if isinstance(item, dict) else item
        formatted_attr.append(f"{formatted_item}\n")

    return "".join(formatted_attr)[:-1]  # Remove the last end of line character


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
        nested attributes. Hence, item is recursively accessed.

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
        """Collect :class:`Cell` attributes and assigns it to the
        :attr:`cells` attribute.

        Args:
            cls (type): Class that is being initialized

        """
        super().__init_subclass__()

        cells = {}

        # Fetch all we do not use "inspect.getmembers" because it orders the
        # attributes by name.
        for c in reversed(cls.__mro__):  # Reverse to get base table cells first
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

    @staticmethod
    def get_terminal_size(fallback=(80, 24)):
        """Get the current terminal size

        This method is a thin wrapper around the :func:`os.get_terminal_size`
        function. :func:`os.get_terminal_size` takes as argument the file
        descriptor to use:

        - ``0``: Standard Input
        - ``1``: Standard Output
        - ``2``: Standard Error

        If the selected file descriptor is a non-interactive terminal, then
        the function raises an `OSError` exception. This happen especially in
        the following situations (assuming these commands are ran in an
        interactive terminal):

        .. code:: bash

            # stdout of rok is not the interactive terminal
            $ python3 program.py | cat -

            # stdin is not the interactive terminal
            $ cat - | python3 program.py

            # neither stdin nor stdout are the interactive terminals, however
            # stderr is.
            $ cat - | python3 program.py | cat -

            # neither stdin nor stdout nor stderr are the interactive
            # terminals.
            $ cat - | python3 program.py 2>somefile | cat -

        We are trying all possible file descriptors, hoping that at least one
        of them is a tty. In case no tty can be found, we fallback to default
        values.

        Visit `this blog post
        <http://granitosaurus.rocks/getting-terminal-size.html#edit_1>`_ for
        more information.

        Args:
            fallback (tuple, optional): Fallback values for width and height
                in case no tty is found.

        """
        for i in range(0, 3):
            try:
                return os.get_terminal_size(i)
            except OSError:
                continue

        return fallback

    def __call__(self, data, file):
        """Print a table from the passed data

        Args:
            data (object): Data that should be formatted
            file: File-like object where the output should be written

        """
        width, height = self.get_terminal_size()
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
    labels = Cell("metadata.labels", formatter=labels_formatter)
    created = Cell("metadata.created", formatter=format_datetime)
    modified = Cell("metadata.modified", formatter=format_datetime)
    deleted = Cell("metadata.deleted", formatter=format_datetime)
