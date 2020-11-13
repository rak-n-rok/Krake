"""Core of the declarative REST API definition API.

The *API definition* API is based on a set of decorators that are applied on
classes. The class bodies are used as mere data containers. The decorators
use the class attributes as parameters to construct definition objects.

Example:
    .. code:: python

        from krake.apidefs.definitios import ApiDef, Scope, operation
        from krake.data.shelf import Book, BookList


        shelf = ApiDef("shelf")

        @shelf.resource
        class BookResource:
            singular = "Book"
            plural = "Books"
            scope = Scope.NAMESPACED

            @operation
            class Create:
                method = "POST"
                path = "/shelf/namespaces/{namespace}/books"
                body = Book
                response = Book

            @operation
            class Read:
                method = "GET"
                path = "/shelf/namespaces/{namespace}/books/{name}"
                response = Book

            @operation
            class List:
                number = "plural"
                method = "GET"
                path = "/shelf/namespaces/{namespace}/books"
                response = BookList

"""
from collections import defaultdict
from inspect import getmembers
from enum import Enum, auto
from string import Formatter
from typing import NamedTuple

from krake.utils import camel_to_snake_case
from marshmallow import fields, missing
from marshmallow.validate import Range

from krake.data.serializable import ApiObject


class ApiDef(object):
    """An API definition is a collection of :class:`Resource` definitions.

    The :meth:`resource` decorator is used to transform classes into
    :class:`Resource` objects and adds them to the :attr:`resources` list.

    Attributes:
        name (str): Name of API. This should match the ``api`` attributes of all
            :class:`krake.data.serializable.ApiObject` resources used in this
            definition.
        resources (list(Resource)): List of registered resources that are
            handled by the described API.

    """

    def __init__(self, name):
        self.name = name
        self.resources = []
        self._import_classes = None
        self._import_factory_classes = None

    @property
    def import_classes(self):
        """Get the reference of all classes needed to be imported by the current ApiDef
        from the class:`Resource` defined in it.

        Returns:
            dict: all classes needed for the current ApiDef, separated by a different
                list for each module: "<module_path>: <list_of_classes>".

        """
        if self._import_classes:
            return self._import_classes

        classes = set()
        for resource in self.resources:
            classes.update(resource.import_classes)

        self._import_classes = defaultdict(list)
        for cls in classes:
            self._import_classes[cls.__module__].append(cls)
        return self._import_classes

    @property
    def import_factory_classes(self):
        """Get the reference of all classes for which a Factory will need to be imported
        by the current ApiDef from the class:`Resource` defined in it.

        Returns:
            dict[str, list]: all classes for the current ApiDef, which will need a
                Factory, separated by a different list for each module:
                "<module_path>: <list_of_classes>".

        """
        if self._import_factory_classes:
            return self._import_factory_classes

        self._import_factory_classes = defaultdict(list)
        for module_path, classes in self.import_classes.items():
            for cls in classes:
                if "List" not in cls.__name__:
                    self._import_factory_classes[module_path].append(cls)

        return self._import_factory_classes

    def resource(self, template):
        """Decorator method that is used to transform a given class into a
        :class:`Resource` object and appends the created object to the
        :attr:`resources` list.

        Example:
            .. code:: python

                shelf = ApiDef("shelf")

                @shelf.resource
                class BookResource:
                    ...

        Args:
            template (type): Resource template class. The class attributes
                will be used to create a :class:`Resource` object.

        Returns:
            Resource: Generated resource definition

        """
        resource = make_resource(template, self.name)
        self.resources.append(resource)
        return resource


class Scope(Enum):
    """Scope of resources

    Attributes:
        NONE: The resource is not scoped
        NAMESPACED: The resource is generated in a namespace

    """

    NONE = auto()
    NAMESPACED = auto()


class Resource(object):
    """Resource definition describing all operations and subresources for an API
    resource.

    Args:
        api (str): Name of the API
        scope (Scope): Scope of the resource
        singular (str): Singular name of the resource
        plural (str): Plural name of the resource
        operations (list(tuple(str, operation))): List of operations and their
            name
        subresources (list(tuple(str, subresource))): List of subresources and
            their name

    Attributes:
        api (str): Name of the API
        scope (Scope): Scope of the API
        singular (str): Singular name of the resource
        plural (str): Plural name of the resource
        operations (list(operation)): List of supported operations on the
            resource
        subresources (list(subresource)): List of supported subresources of the
            resource

    """

    def __init__(self, api, scope, singular, plural, operations, subresources):
        self.api = api
        self.scope = scope
        self.singular = singular
        self.plural = plural
        self._import_classes = None

        for name, op in operations:
            op.resource = self
        self.operations = [op for _, op in operations]

        for name, sub in subresources:
            sub.resource = self
        self.subresources = [sub for _, sub in subresources]

    def __getitem__(self, item):
        """Get the operation defined for this resource, with the given name.

        Args:
            item (str): name of the operation to retrieve.

        Returns:
            operation: the operation with the given name.

        Raises:
            KeyError: if no operation with this name has been defined for this Resource.

        """
        for operation in self.operations:
            if operation.name == item:
                return operation
        else:
            raise KeyError(item)

    @property
    def snake_case_singular(self):
        return camel_to_snake_case(self.singular)

    @property
    def snake_case_plural(self):
        return camel_to_snake_case(self.plural)

    @property
    def import_classes(self):
        """Get all the references to the classes that need to be imported to use the
        current Resource from the operations defined in it.

        Returns:
            set: the set of all classes that the operations in the current Resource
                need.

        """
        if self._import_classes:
            return self._import_classes
        classes = set()

        for operation in self.operations:
            if operation.body:
                classes.add(operation.body)
            if operation.response:
                classes.add(operation.response)

        self._import_classes = classes
        return self._import_classes

    @property
    def namespaced(self):
        """Compute if a resource is namespaced or not.

        Returns:
            bool: True if the resource is namespaced, False otherwise.

        """
        return self.scope == Scope.NAMESPACED

    def __repr__(self):
        return f"<Resource {self.api}.{self.singular} scope={self.scope.name}>"


class operation(object):
    """Definition of a resource or subresource operation.

    This class is meant to be used as decorator for classes.

    Example:
        .. code:: python

            @operation
            class Read:
                number = "singular"  # Default, not required
                method = "GET"
                path = "/shelf/namespaces/{namespace}/books/{name}"
                response = Book

    Attributes:
        number (str): Grammatical number of the resource(s) changed by this
            operation, ``singular`` or ``plural``.
        method (str): HTTP method of the operation, e.g. ``GET``, ``PUT``.
        path (str): HTTP path of the operation with path parameters in Python
            format-style.
        query (dict(str, marshmallow.field.Field), None): Supported query
            parameters.
        body (type, None): Type (:class:`krake.data.serializable.ApiObject`)
            describing the HTTP request body.
        response (type, None): Type (:class:`krake.data.serializable.ApiObject`)
            describing the HTTP response body.

    Args:
        template (type): Class that use used as data container
            (see :class:`OperationData`).

    The class data container should have the following structure:

    .. py:class:: OperationData

        Class that is used as data container for the :class:`operation`
        decorator.

        .. py:attribute:: number

            Grammatical number of the resource(s) changed by this operation,
            ``singular`` or ``plural``. The attribute is optional and defaults
            to ``singular``.

        .. py:attribute:: method

            HTTP method of the operation, e.g. ``GET``, ``PUT``.
            Required class attribute.

        .. py:attribute:: path

            HTTP path of the operation with path parameters in Python
            format-style. Required class attribute.

        .. py:attribute:: query

            Optional dictionary of query parameters and associated
            :class:`marshmallow.field.Field` objects.

        .. py:attribute:: body

            Optional type (:class:`krake.data.serializable.ApiObject`)
            describing the HTTP request body.

        .. py:attribute:: response

            Optional type (:class:`krake.data.serializable.ApiObject`)
            describing the HTTP response body.

    """

    def __init__(self, template):
        self.number = getattr(template, "number", "singular")
        self.method = template.method
        self.path = template.path
        self.query = getattr(template, "query", {})
        self.body = getattr(template, "body", None)
        self.response = getattr(template, "response", None)
        self.name = template.__name__
        self._resource = None
        self._subresource = None
        self._arguments = None

        # Only API objects are allowed in HTTP bodies
        if self.body:
            assert issubclass(
                self.body, ApiObject
            ), f"Body must be ApiObject, got {type(self.response)}"
        if self.response:
            assert issubclass(
                self.response, ApiObject
            ), f"Response must be ApiObject, got {type(self.response)}"

    @property
    def resource(self):
        """Resource: Resource holding this operation. If the operation is
        on a :class:`subresource`, the :attr:`subresource.resource` attribute
        is returned.

        If the :class:`operation` is not bound to any :class:`Resource` yet,
        :data:`None` is returned.
        """
        if self._subresource:
            return self._subresource.resource
        elif self._resource:
            return self._resource
        return None

    @resource.setter
    def resource(self, value):
        if self._subresource:
            raise RuntimeError(f"Operation already bound to {self._subresource}")
        if self._resource:
            raise RuntimeError(f"Operation already bound to {self._resource}")
        self._resource = value

    @property
    def subresource(self):
        """subresource, None: The subresource this :class:`operation` is bound
        to or :data:`None` if not bound to a subresource (or unbound).
        """
        return self._subresource

    @subresource.setter
    def subresource(self, value):
        if self._subresource:
            raise RuntimeError(f"Operation already bound to {self._subresource}")
        self._subresource = value

    @property
    def signature_name(self):
        """Generate the base name of an API or client handler for the current operation.
        Snake case is used, as well as the number of the operation (singular or plural).

        Returns:
            str: the generated name, as "<name_singular_or_plural>" or
                "<name_singular_or_plural>_<subresource_name>" if the operation belongs
                to a subresource.

        """
        if self.number == "singular":
            name = camel_to_snake_case(self.resource.singular)
        else:
            name = camel_to_snake_case(self.resource.plural)

        if self.subresource:
            subresource_name = camel_to_snake_case(self.subresource.name)
            name = f"{name}_{subresource_name}"
        return name

    @property
    def arguments(self):
        """Get all arguments that should be added in the docstring of the handlers for
        the current operation.

        Returns:
            list[Argument]: the list of all docstring arguments of the operation.

        """
        if self._arguments:
            return self._arguments

        arguments = []

        if self.body:
            # TODO: Should the documentation be here or in the template?
            body_arg = Argument(name="body")
            arguments.append(body_arg)

        # Create an entry for all parameters in the path of the operation
        for _, name, _, _ in Formatter().parse(self.path):
            if name is not None:
                # TODO: Should the documentation be here or in the template?
                namespace_arg = Argument(name=name, kind="str")
                arguments.append(namespace_arg)

        # Create an entry for all parameters in the query of the operation
        if self.query:
            for name, field in self.query.items():
                kind = getattr(field, "num_type", str).__name__
                field_arg = Argument(name, kind=kind, doc=field.metadata["doc"])
                arguments.append(field_arg)

        self._arguments = arguments
        return self._arguments

    def __repr__(self):
        if self.subresource:
            return (
                f"<operation {self.name} for "
                f"{self.resource.api}.{self.resource.singular}"
                f".{self.subresource.name}>"
            )
        elif self.resource:
            return (
                f"<operation {self.name} for "
                f"{self.resource.api}.{self.resource.singular}>"
            )
        else:
            return f"<operation {self.name} unbound>"


class Argument(NamedTuple):
    """Stores a docstring argument entry, corresponding to a parameter.

    Attributes:
        name (str): name of the parameter.
        kind (str): kind of the parameter.
        doc (str): description of the parameter.

    """

    name: str
    kind: str = None
    doc: str = None


class subresource(object):
    """Definition of a subresource.

    This class is meant to be used as decorator for classes.

    Example:
        .. code:: python

            @subresource
            class Status:
                @operation
                class Update:
                    method = "PUT"
                    path = "/shelf/namespaces/{namespace}/books/{name}/status"
                    body = Book
                    response = Book

    Attributes:
        name (str): Name of the subresource. This is automatically inferred
            from the class name of the decorated class.

    Args:
        template (type): Class that is used as data container.


    """

    def __init__(self, template):
        self.name = template.__name__
        self._resource = None

        operations = getmembers(template, lambda member: isinstance(member, operation))
        for name, op in operations:
            op.subresource = self
        self.operations = [op for _, op in operations]

    @property
    def resource(self):
        """Resource: Resource this subresources belongs to"""
        return self._resource

    @resource.setter
    def resource(self, value):
        if self._resource:
            raise RuntimeError(f"Subresource already bound to {self._resource!r}")
        self._resource = value

    @property
    def resource_name(self):
        return f"{self.resource.plural.lower()}/{self.name.lower()}"

    def __repr__(self):
        return (
            f"<subresource {self.name} for "
            f"{self.resource.api}.{self.resource.singular}>"
        )


def make_resource(cls, api):
    """Create an :class:`Resource` object from a given class

    Args:
        cls (type): Class that is used as data container
        api (str): Name of the API

    Returns:
        Resource: Resource definition based on the class attributes of the
        passed class.

    """
    operations = getmembers(cls, lambda member: isinstance(member, operation))
    subresources = getmembers(cls, lambda member: isinstance(member, subresource))

    return Resource(
        api=api,
        singular=cls.singular,
        plural=cls.plural,
        scope=cls.scope,
        operations=operations,
        subresources=subresources,
    )


class QueryFlag(fields.Field):
    """Field used for boolean query parameters.

    If the query parameter exists the field is deserialized to :data:`True`
    regardless of the value. The field is marked as ``load_only``.

    """

    def __init__(self, **metadata):
        super().__init__(load_only=True, **metadata)

    def deserialize(self, value, attr=None, data=None, **kwargs):
        if value is missing:
            return False
        return True


class ListQuery(object):
    """Simple mixin class for :class:`operation` template classes.

    Defines default :attr:`operation.query` attribute for *list* and *list
    all* operations.

    """

    query = {
        "heartbeat": fields.Integer(
            missing=None,
            doc=(
                "Number of seconds after which the server sends a heartbeat in "
                "form a an empty newline. Passing 0 disables the heartbeat. "
                "Default: 10 seconds"
            ),
            validate=Range(min=0),
        ),
        "watch": QueryFlag(
            doc=(
                "Watch for changes to the described resources and return "
                "them as a stream of :class:`krake.data.core.WatchEvent`"
            )
        ),
    }
