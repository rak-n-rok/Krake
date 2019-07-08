"""This module defines a functional and inheritance-based declarative API for
defining data models that are JSON-serializable and JSON-deserializable.

Core-API of this module are the single-dispatch function (see :pep:`0443`)
:func:`serialize` and the function :func:`deserialize`.
"""
import dataclasses
import json
from enum import Enum
from datetime import datetime, date
from typing import get_type_hints, List, NamedTuple
from functools import singledispatch
from webargs import fields
from marshmallow import Schema, post_load
from marshmallow_enum import EnumField
from marshmallow_oneofschema import OneOfSchema


@singledispatch
def serialize(value):
    """Single-dispatch generic function (see :pep:`0443`) for serializing objects.

    The standard implementation checks if an object has an ``serialize``
    attribute and calls it accordingly. Otherwise :class:`NotImplementedError`
    is raised.

    Example:
        .. code:: python

            from krake.data import serialize

            class Book(object):
                def __init__(self, isbn, author, title):
                    self.author = author
                    self.title = title

                def serialize(self):
                    return {
                        "author": self.author,
                        "title": self.title,
                    }

            book = Book(
                author="Douglas Adams",
                title="The Hitchhiker's Guide to the Galaxy",
            )
            data = serialize(book)

        If the implementation is not under your control -- meaning a
        ``serialize()`` method cannot be implemented -- a specific
        implementation for this type of object can be registered:

        .. code:: python

            from krake.data import serialize
            from library import Book

            @serialize.register(Book)
            def _(book):
                return {
                    "author": book.author,
                    "title": book.title,
                }

    Args:
        value (object): Object that should be serialized

    Returns:
        The specific implementations should return Python objects compatible
        with the standard :func:`json.dumps` function.

    Raises:
        NotImplementedError: If no implementation is registered and no
            ``serialize()`` method is implemented by the object.

    """
    if hasattr(value, "serialize"):
        return value.serialize()
    raise NotImplementedError(
        "No serialize function registered for type " f"{type(value)}"
    )


def deserialize(cls, value, **kwargs):
    """Loading an object of specific type from JSON-encoded data.

    Internally, a ``__metadata__["schema"]`` attribute is loaded from the type
    parameter. This attribute should be an object implementing the
    mod:`marshmallow.Schema` interface.

    If there are multiple subclasses of an object, :class:`PolymorphicSchema`
    can be used.

    Example:
        .. code:: python

            from dataclasses import dataclass
            from marshmallow import fields
            from krake.data.serializable import ModelizedSchema, deserialize

            @dataclass
            class Book(object):
                author: str
                title: str

            class BookSchema(ModelizedSchema):
                __model__ = Book

                author = fields.String(required=True)
                title = fields.String(required=True)

            Book.__metadata__ = {
                "schema": BookSchema(strict=True)
            }


            book = deserialize(Book, {
                "author": "Douglas Adams",
                "title": "The Hitchhiker's Guide to the Galaxy",
            })

    Args:
        cls (type): Type that should be loaded from the passed value
        value (str, bytes, dict): Either JSON-encoded string or bytes or
            Python dictionary that should deserialized.
        **kwargs: Every key in ``value`` can be overwritten by passing
            corresponding keyword arguments to the function

    Raises:
        marshmallow.ValidationError: If the data is invalid

    """
    if isinstance(value, bytes):
        value = value.decode()

    if isinstance(value, str):
        value = json.loads(value)

    # Overwrite values by keyword arguments
    if kwargs:
        value = dict(value, **kwargs)

    instance, _ = cls.__metadata__["schema"].load(value)
    assert isinstance(instance, cls)
    return instance


class ModelizedSchema(Schema):
    """Simple marshmallow schema constructing Python objects in a
    ``post_load`` hook.

    Subclasses can specifify a callable attribute ``__model__`` which is
    called with all deserialized attributes as keyword arguments.

    Attributes:
        __model__ (callable): Model factory returning a new instance of a
            specific model

    """

    __model__ = None

    @post_load
    def create_model(self, data):
        if self.__model__:
            return self.__model__(**data)
        return data


class PolymorphicSchema(OneOfSchema):
    """Special schema allowing loading of polymorphic classes.

    Example:
        .. code:: python

            from dataclasses import dataclass
            from marshmallow import fields
            from krake.data.serializable import (
                ModelizedSchema,
                PolymorphicSchema,
                deserialize,
            )

            @dataclass
            class Book(object):
                author: str
                title: str
                kind: str

            class Paperback(Book):
                kind: str = "paperback"

            class Hardcover(Book):
                kind: str = "hardcover"

            class BookSchema(ModelizedSchema):
                author = fields.String(required=True)
                title = fields.String(required=True)
                __model__ = Book

            class PaperbackSchema(ModelizedSchema):
                __model__ = Paperback

            class HardcoverSchema(ModelizedSchema):
                __model__ = Hardcover

            schema = PolymorphicSchema("kind")
            schema.type_schemas["book"] = BookSchema(strict=True)
            schema.type_schemas["paperback"] = PaperbackSchema(strict=True)
            schema.type_schemas["hardcover"] = HardcoverSchema(strict=True)

            # Configure metadata in order to used "deserialize()"
            Book.__metadata__ = {
                "schema": schema
            }

            book = deserialize(Book, {
                "author": "Douglas Adams",
                "title": "The Hitchhiker's Guide to the Galaxy",
                "kind": "paperback"
            })
            assert isinstance(book, Paperback)

    Attributes:
        type_field (str): Name of the attribute (see ``discriminator`` in
            :func:`serializable`) that is used to identify different classes.
        type_schemas (dict): Mapping of discriminator values
            (see :func:`serializable`) to schema instances.
    """

    type_field_remove = False

    def __init__(self, type_field, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type_field = type_field
        self.type_schemas = {}

    def get_obj_type(self, obj):
        data_type = getattr(obj, self.type_field)

        # Special case:
        #     Use the name of enumeration fields
        if isinstance(data_type, Enum):
            return data_type.name

        return data_type


class SimpleFieldResolver(object):
    """Simple resolver for a given type and :class:`marshmallow.fields.Field`.
    The resolver simply checks if a given type is a subclass of the passed type
    and retuns a new instance of the configured marshmallow field.

    Example:
        .. code:: python

            from marshmallow import fields

            resolver = SimpleFieldResolver(int, fields.Integer)
            field = resolver([], int, required=True, allow_none=False)

    Args:
        type_ (type): Every subclass of this type will be resolved to the
            given field
        field_type (type): :class:`marshmallow.fields.Field` subclass that
            should be instantiated if the requested type is a subclass of
            the given ``type_``.

    """

    def __init__(self, type_, field_type):
        self.type = type_
        self.field_type = field_type

    def __call__(self, type_, required, allow_none, resolvers):
        if not issubclass(type_, self.type):
            raise ValueError(f"Not a subclass of {self.type}")

        return self.field_type(required=required, allow_none=allow_none)


def resolve_enum(type_, required, allow_none, resolvers):
    """Resolver for enumeration fields. If the given type is a subclass of
    :class:`enum.Enum` an instance of :class:`marshmallow_enum.EnumField` will be
    returned.

    Args:
        type_ (type): Type of an attribute
        required (bool): True of the field should be required
        allow_none (bool): True of the field allows None
        resolvers (List[callable]): List of resolvers

    Returns:
        marshmallow_enum.EnumField: Field for the given type

    Raises:
        ValueError: If the passed type is not an :class:`enum.Enum`.

    """
    if not issubclass(type_, Enum):
        raise ValueError("Not an enumeration")

    return EnumField(type_, required=required, allow_none=allow_none)


def resolve_schema(type_, required, allow_none, resolvers):
    """Resolver for types with a ``__metadata__["schema"]`` attribute.

    Args:
        type_ (type): Type of an attribute
        required (bool): True of the field should be required
        allow_none (bool): True of the field allows None
        resolvers (List[callable]): List of resolvers

    Returns:
        marshmallow.fields.Nested: A nested field with the using the
        ``__metadata__["schema"]`` attribute of the passed type.

    Raises:
        ValueError: If the passed type does not define a
        ``__metadata__["schema"]`` attribute.

    """
    try:
        schema = type_.__metadata__["schema"]
    except AttributeError as err:
        raise ValueError(f"{type_} as no '{err}' attribute")
    except KeyError as err:
        raise ValueError(f"'__metadata__' of {type_} as no '{err}' key")

    return fields.Nested(schema, allow_none=allow_none, required=required)


def resolve_list(type_, required, allow_none, resolvers):
    """Resolver for :class:`typing.List` attributes.

    Args:
        type_ (type): Type of an attribute
        required (bool): True of the field should be required
        allow_none (bool): True of the field allows None
        resolvers (List[callable]): List of resolvers

    Returns:
        marshmallow.fields.List: A list field with the using the field
        resolved for the  inner type of a list.

    Raises:
        ValueError: If the passed type is not an :class:`typing.List`.

    """
    if not issubclass(type_, List):
        raise ValueError("Not a list")

    inner_type = type_.__args__[0]
    inner_serializer = make_field(inner_type, resolvers, default=dataclasses.MISSING)
    return fields.List(inner_serializer, allow_none=allow_none, required=required)


default_resolvers = [
    SimpleFieldResolver(int, fields.Integer),
    SimpleFieldResolver(bool, fields.Boolean),
    SimpleFieldResolver(str, fields.String),
    SimpleFieldResolver(float, fields.Float),
    SimpleFieldResolver(dict, fields.Dict),
    SimpleFieldResolver(datetime, fields.DateTime),
    SimpleFieldResolver(date, fields.Date),
    resolve_enum,
    resolve_schema,
    resolve_list,
]


def serializable(cls=None, resolvers=default_resolvers):
    """Decorator function for automatically defining a marshmallow schema for
    the the decorated class.

    It supports either class type annotations or dataclasses
    (:mod:`dataclasses`). The generated schema class is accessible as
    ``Schema`` attribute on the decorated class. The

    Furthermore, an instance of this schema is assigned to the ``schema`` key
    of the ``__metadata__`` attribute of the class. The class gets
    automatically registered to the :func:`serialize` function using the
    ``__metadata__["schema"]`` attribute.

    If the ``__metadata__`` dictionary specifies a ``discriminator`` key, an
    instance of :class:`PolymorphicSchema` is used for
    ``__metadata__["schema"]``. The same polymorphic schema is used for all
    subclasses. The discriminator value is loaded from the class and its value
    is used as key in the :attr:`PolymorphicSchema.type_schemas` dictionary.
    An instance of the generated ``Schema`` attribute is used as value.

    The corresponding fields for every attribute are resolved by resolver
    functions. A resolver is a function with the following signature:

    .. py::function:: resolver(resolvers, type_, required, allow_none)

           :param List[callable] resolvers: List of resolvers
           :param type type_: Type of an attribute
           :param bool required: True of the field should be required
           :param bool allow_none: True of the field allows None
           :return: A field used for the passed type
           :rtype: marshmallow.field.Field
           :raises ValueError: If the resolver does not match the passed type

    If the function is called without any arguments, it acts as a decorator.

    Args:
        cls (type): Class for which a schema should be generated.
        resolvers (List[callable], optional): List of resolvers

    Returns:
        A decorator function for classes

    Raises:
        ValueError: If the discriminator value is already registered

    """

    def wrap(cls):
        schema_attrs = {
            "__module__": cls.__module__,
            "__qualname__": f"{cls.__qualname__}.Schema",
            "__model__": cls,
        }

        # Generator expression for attributes (name, type, default)
        if dataclasses.is_dataclass(cls):
            fields = ((f.name, f.type, f.default) for f in dataclasses.fields(cls))
        elif issubclass(cls, NamedTuple):
            fields = (
                (name, type_, cls._field_defaults.get(name, dataclasses.MISSING))
                for name, type_ in cls._field_types.items()
            )
        else:
            fields = (
                (name, type_, getattr(cls, name, dataclasses.MISSING))
                for name, type_ in get_type_hints(cls).items()
            )

        for name, type_, default in fields:
            serializer = make_field(type_, resolvers, default)
            schema_attrs[name] = serializer

        cls.Schema = type("GeneratedSchema", (ModelizedSchema,), schema_attrs)

        if not hasattr(cls, "__metadata__"):
            cls.__metadata__ = {}
        # Copy metadata dictionary of defined in a super class
        elif "__metadata__" not in cls.__dict__:
            cls.__metadata__ = cls.__metadata__.copy()

        if "discriminator" in cls.__metadata__:
            # If no discrimniator map is found in the base classes, use this
            # one.
            polymorphic_schema = None

            # Try to load polymorphic schema from base classes
            for base in cls.mro():
                try:
                    schema = base.__metadata__["schema"]
                except (AttributeError, KeyError):
                    pass
                else:
                    if isinstance(base.__metadata__["schema"], PolymorphicSchema):
                        polymorphic_schema = schema

            if polymorphic_schema is None:
                polymorphic_schema = PolymorphicSchema(
                    cls.__metadata__["discriminator"], strict=True
                )
            else:
                assert (
                    polymorphic_schema.type_field == cls.__metadata__["discriminator"]
                )

            if hasattr(cls, cls.__metadata__["discriminator"]):
                discriminator = getattr(cls, cls.__metadata__["discriminator"])

                # Special case:
                #     Use the name of enumeration fields
                if isinstance(discriminator, Enum):
                    discriminator = discriminator.name

                # Ensure that the discrimniator value is not already used
                if discriminator in polymorphic_schema.type_schemas:
                    mapped = polymorphic_schema.type_schemas[discriminator]
                    raise ValueError(
                        f"Discriminator {discriminator!r} is "
                        f"already mapped to {mapped!r}"
                    )

                polymorphic_schema.type_schemas[discriminator] = cls.Schema(strict=True)

            cls.__metadata__["schema"] = polymorphic_schema
        else:
            cls.__metadata__["schema"] = cls.Schema(strict=True)

        @serialize.register(cls)
        def _(value):
            data, _ = cls.__metadata__["schema"].dump(value)
            return data

        return cls

    if cls is None:
        return wrap

    return wrap(cls)


def make_field(attr_type, resolvers, default):
    """Given the type of an attribute, a list of resolvers
    (see :func:`serializable`) and a default value returns a
    marshmallow field for the attribute.

    The first field returned by a resolver will be used.

    Args:
        attr_type (type): Type of an attribute
        resolvers (List[callable]): List of resolvers
        default (object): Default value of the attribute

    Raises:
        NotImplementedError: If no resolver returned a field for the given
            attribute type.

    """
    required = default is dataclasses.MISSING
    allow_none = default is None

    for resolver in resolvers:
        try:
            return resolver(
                attr_type, required=required, allow_none=allow_none, resolvers=resolvers
            )
        except ValueError:
            pass

    raise NotImplementedError(f"No serializer found for {attr_type!r}")


class SerializableMeta(type):
    """Metaclass for :class:`Serializable`. It automatically converts a
    specified class into an dataclass (see :func:`dataclasses.dataclass`) and
    passes the resulting dataclass to :func:`serializable`.

    A class can specify attribute resolver functions (see
    :func:`serializable`) in the ``__metadata__["resolvers"]`` attribute. The
    list of resolvers from all bases classes will be concatenated in method
    resolution order.

    """

    def __new__(mcls, name, bases, attrs, init=False):
        cls = super().__new__(mcls, name, bases, attrs)
        cls = dataclasses.dataclass(cls, init=init)
        cls = serializable(cls, resolvers=mcls.gather_resolvers(cls))

        return cls

    @classmethod
    def gather_resolvers(mcls, cls):
        """Concatenate ``__metadata__["resolver"]`` attributes from all base
        classes.

        Args:
            cls (type): Class from which resolvers should be loaded

        Returns:
            List[callable]: Concatenated list of resolvers

        """
        resolvers = []

        for base in cls.mro():
            if hasattr(base, "__metadata__"):
                resolvers.extend(base.__metadata__.get("resolvers", []))

        return resolvers


class Serializable(metaclass=SerializableMeta):
    """Base class for inheritance-based serialization API.

    The class also defines a custom ``__init__`` method accepting every
    attribute as keyword argument in arbitrary order in contrast to the
    standard init method of dataclasses.

    Example:
        .. code:: python

            from krake.data.serializable import Serializable

            class Book(Serializable):
                author: str
                title: str

            assert hasattr(Book, "Schema")
            assert "schema" in Book.__metadata__

    """

    __metadata__ = {"resolvers": default_resolvers}

    def __init__(self, **kwargs):
        for field in dataclasses.fields(self):
            value = kwargs.pop(field.name, field.default)
            if value is dataclasses.MISSING:
                raise TypeError(f"Missing keyword argument {field.name!r}")
            setattr(self, field.name, value)
        if kwargs:
            key, _ = kwargs.popitem()
            raise TypeError(f"Got unexpected keyword argument {key!r}")
