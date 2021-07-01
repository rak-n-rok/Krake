"""Data abstraction module for all REST resources used by the Krake API. This
module provides common data definitions for :mod:`krake.api` and
:mod:`krake.client`.

The core functionality is provided by :mod:`.serializable` providing a Python
API for declarative definitions of data models together with serializing and
deserializing functionality.

Domain-specific models are defined in corresponding submodules, e.g.
Kubernetes-related data models are defined in :mod:`.kubernetes`.
"""
import re
from operator import itemgetter


class Key(object):
    """Etcd key template using the same syntax as Python's standard format
    strings for parameters.

    Example:
        .. code:: python

            key = Key("/books/{namespaces}/{isbn}")

    The parameters are substituted by in the corresponding methods by either
    attributes of the passed object or additional keyword arguments.

    Args:
        template (str): Key template with format string-like parameters
        attribute (str, optional): Load attributes in :meth:`format_object`
            from this attribute of the passed object.

    """

    _params_re = re.compile(r"\{(.+?)\}")

    def __init__(self, template, attribute=None):
        self.template = template
        self.attribute = attribute
        self.parameters = list(self._params_re.finditer(template))

        # For each parameter, only accepts ASCII, ":", "." and "-".
        template_re = self._params_re.sub("[.a-zA-Z0-9_:-]+?", template)
        self.pattern = re.compile(fr"^{template_re}$")

    def matches(self, key):
        """Check if a given key matches the template

        Args:
            key (str): Key that should be checked

        Returns:
            bool: True of the given key matches the key template
        """
        return self.pattern.match(key) is not None

    def format_object(self, obj):
        """Create a key from a given object

        If ``attribute`` is given, attributes are loaded from this attribute
        of the object rather than the object itself.

        Args:
            obj (object): Object from which attributes are looked up

        Returns:
            str: Key from the key template with all parameters substituted by
            attributes loaded from the given object.

        Raises:
            AttributeError: If a required parameter is missing
        """
        params = {}

        if self.attribute:
            obj = getattr(obj, self.attribute)

        for param in map(itemgetter(1), self.parameters):
            params[param] = getattr(obj, param)

        return self.template.format(**params)

    def format_kwargs(self, **kwargs):
        """Create a key from keyword arguments

        Args:
            **kwargs: Keyword arguments for parameter substitution

        Returns:
            str: Key from the key template with all parameters substituted by
            the given keyword arguments.
        """
        template = self.template
        params = {}

        for match in self.parameters:
            key = match[1]
            try:
                params[key] = kwargs.pop(key)
            except KeyError:
                raise TypeError(f"Missing required keyword argument {key!r}")
        if kwargs:
            key, _ = kwargs.popitem()
            raise TypeError(f"Got unexpected keyword argument parameter {key!r}")

        return template.format(**params)

    def prefix(self, **kwargs):
        """Create a partial key (prefix) for a given object.

        Args:
            **kwargs: Parameters that will be used for substitution

        Returns:
            str: Partial key from the key template with some parameters
            substituted

        Raises:
            TypeError: If a parameter is passed as keyword argument but a
                preceding parameter is not given.

        """
        template = self.template
        params = {}

        for match in self.parameters:
            try:
                params[match[1]] = kwargs.pop(match[1])
            except KeyError:
                template = match.string[: match.start()]
                break

        if kwargs:
            key, _ = kwargs.popitem()
            raise TypeError(
                f"Got parameter {key!r} without preceding parameter {match[1]!r}"
            )

        return template.format(**params)


def persistent(key):
    """Decorator factory for marking a class with a template that should be
    used as etcd key.

    The passed template will be converted into a :class:`Key` instance using
    the ``metadata`` attribute and will be assigned to the ``__etcd_key__``
    attribute of the decorated class.

    Example:
        .. code:: python

            from krake.data import persistent
            from krake.data.serializable import Serializable, persistent
            from krake.data.core import Metadata

            @persistent("/books/{name}")
            class Book(Serializable):
                metadata: Metadata

    Args:
        key (str): Etcd key template. Parameters will be loaded from the
            ``metadata`` attribute of the decorated class.

    Returns:
        callable: Decorator that can be used to assign an ``__etcd_key__``
        attribute to the decorated object based on the passed key template.

    """

    def decorator(cls):
        assert not hasattr(cls, "__etcd_key__")
        cls.__etcd_key__ = Key(key, attribute="metadata")
        return cls

    return decorator
