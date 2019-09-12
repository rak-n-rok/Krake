"""This module defines a declarative API for defining data models that are
JSON-serializable and JSON-deserializable.
"""
import dataclasses
from enum import Enum
from datetime import datetime, date
from typing import List
from webargs import fields
from marshmallow import (
    Schema,
    post_load,
    EXCLUDE,
    INCLUDE,
    missing,
    ValidationError,
    validates,
    validates_schema,
)
from marshmallow.validate import Equal
from marshmallow_enum import EnumField


class ModelizedSchema(Schema):
    """Simple marshmallow schema constructing Python objects in a
    ``post_load`` hook.

    Subclasses can specifify a callable attribute ``__model__`` which is
    called with all deserialized attributes as keyword arguments.

    The ``Meta.unknown`` field is set to avoid considering unknown fields
    during validation. It mostly prevents create tests from failing.

    Attributes:
        __model__ (callable): Model factory returning a new instance of a
            specific model

    """

    __model__ = None

    class Meta:
        unknown = EXCLUDE

    @post_load
    def create_model(self, data, **kwargs):
        # kwargs necessary for unused additional parameters
        if self.__model__:
            # Use None value for every excluded field
            excluded = {key: None for key in self.exclude}
            return self.__model__(**data, **excluded)
        return data


_native_to_marshmallow = {
    int: fields.Integer,
    bool: fields.Boolean,
    str: fields.String,
    float: fields.Float,
    dict: fields.Dict,
    datetime: fields.DateTime,
    date: fields.Date,
}


def field_for_schema(type_, default=dataclasses.MISSING, **metadata):
    """Create a corresponding :class:`marshmallow.fields.Field` for the passed
    type.

    If ``metadata`` contains ``marshmallow_field`` key, the value will be used
    directly as field.

    Args:
        type_ (type): Type of the field
        default (optional): Default value of the field
        **metadata (dict): Any additional keyword argument that will be passed
            to the field

    Returns:
        marshmallow.fields.Field: Serialization field for the passed type

    Raises:
        NotImplementedError: If the marshmallow field cannot not be determined
            for the passed type
    """
    if "marshmallow_field" in metadata:
        return metadata["marshmallow_field"]

    # Keyword arguments for the marshmallow field
    if default is not dataclasses.MISSING:
        metadata.setdefault("missing", default)

    if metadata.get("readonly", False):
        metadata.setdefault("missing", None)

    if metadata.get("missing", missing) == missing:
        metadata.setdefault("required", True)

    if type_ in _native_to_marshmallow:
        return _native_to_marshmallow[type_](**metadata)

    if issubclass(type_, Enum):
        return EnumField(type_, **metadata)

    if issubclass(type_, List):
        inner_type = type_.__args__[0]
        inner_serializer = field_for_schema(inner_type)
        return fields.List(inner_serializer, **metadata)

    if hasattr(type_, "Schema"):
        return fields.Nested(type_.Schema, **metadata)

    raise NotImplementedError(f"No serializer found for {type_!r}")


def readonly_fields(cls, prefix=None):
    """Return the name of all read-only fields. Nested fields are returned
    with dot-notation

    Args:
        cls (type): Dataclass from which fields should be loaded
        prefix (str, optional): Used for internal recursion

    Returns:
        set: Set of field names that are marked as with ``readonly`` in their
        metadata.

    """
    found = set()

    for field in dataclasses.fields(cls):
        if dataclasses.is_dataclass(field.type):
            if prefix is None:
                found |= readonly_fields(field.type, prefix=field.name)
            else:
                found |= readonly_fields(field.type, prefix=f"{prefix}.{field.name}")
        elif field.metadata.get("readonly", False):
            if prefix is None:
                found.add(field.name)
            else:
                found.add(f"{prefix}.{field.name}")

    return found


class SerializableMeta(type):
    """Metaclass for :class:`Serializable`. It automatically converts a
    specified class into an dataclass (see :func:`dataclasses.dataclass`) and
    creates a corresponding :class:`marshmallow.Schema` class. The schema
    class is assigned to the :attr:`Schema` attribute.
    """

    def __new__(mcls, name, bases, attrs, **kwargs):
        cls = super().__new__(mcls, name, bases, attrs, **kwargs)
        cls = dataclasses.dataclass(cls, init=False)

        # Check if the class defines an own "Schema" attribute but not its
        # parant classes. Therefore, we use the "__dict__" attribute directly
        # here instead of "hasattr()".
        if "Schema" not in cls.__dict__:
            schema_attrs = {
                "__module__": cls.__module__,
                "__qualname__": f"{cls.__qualname__}.Schema",
                "__model__": cls,
            }

            for field in dataclasses.fields(cls):
                if field.default_factory != dataclasses.MISSING:
                    default = field.default_factory
                else:
                    default = field.default
                serializer = field_for_schema(field.type, default, **field.metadata)
                schema_attrs[field.name] = serializer

            cls.Schema = type("Schema", (ModelizedSchema,), schema_attrs)

        return cls


class Serializable(metaclass=SerializableMeta):
    """Base class for declarative serialization API.

    Fields can be marked with the ``metadata`` attribute of
    :class:`dataclasses.Field`. Currently the following markers exists:

    readonly
        A field marked as "readonly" is automatically generated by the
        API server and not controlled by the user. The user cannot update
        this field. The corresponing marshmallow field allows ``None`` as
        valid value.

    subresource
        A field marked as "subresource" is ignored in update request of
        a resource. Extra REST call are required to update a subresource.
        A well known subresource is "status".

    All field metadata attributes are also passed to the
    :class:`marshmallow.fields.Field` instance. This means the user can
    control the generated marshmallow field with the metadata attributes.

    The class also defines a custom ``__init__`` method accepting every
    attribute as keyword argument in arbitrary order in contrast to the
    standard init method of dataclasses.

    Example:
        .. code:: python

            from krake.data.serializable import Serializable

            class Book(Serializable):
                author: str
                title: str
                isbn: str = fields(metadata={"readonly": True})

            assert hasattr(Book, "Schema")

    Attributes:
        Schema (ModelizedSchema): Schema for this dataclass

    """

    def __init__(self, **kwargs):
        for field in dataclasses.fields(self):
            if field.name in kwargs:
                value = kwargs.pop(field.name)
            elif field.default is not dataclasses.MISSING:
                value = field.default
            elif field.default_factory is not dataclasses.MISSING:
                value = field.default_factory()
            else:
                raise TypeError(f"Missing keyword argument {field.name!r}")
            setattr(self, field.name, value)
        if kwargs:
            key, _ = kwargs.popitem()
            raise TypeError(f"Got unexpected keyword argument {key!r}")

    def serialize(self, subresources=None, readonly=True):
        """Serialize the object using the generated :attr:`Schema`.

        Args:
            subresources (set, optional): Set of fields marked as
                subresources that should be included. If None, all
                subresources are included.
            readonly (bool, optional): If False, all fields marked as readonly
                will be excluded from serialization.

        Returns:
            dict: JSON representation of the object

        """
        exclude = set()

        # Exclude all subresources that are not named in the set of subresource
        if subresources:
            exclude = set(
                field.name
                for field in dataclasses.fields(self)
                if field.metadata.get("subresource", False)
                and field.name not in subresources
            )
        # Exclude all read-only fields
        if not readonly:
            exclude |= readonly_fields(self)

        return self.Schema(exclude=exclude).dump(self)

    @classmethod
    def deserialize(cls, data):
        """Loading an instance of the class from JSON-encoded data.

        Args:
            value (dict): Either JSON dictionary that should deserialized.

        Raises:
            marshmallow.ValidationError: If the data is invalid

        """
        return cls.Schema().load(data)


class ApiObject(Serializable):
    """Base class for objects manipulated via REST API.

    :attr:`api` and :attr:`kind` should be defined as simple string class
    :variables. They are automatically converted into dataclass fields with
    :corresponding validators.

    Attributes:
        api (str): Name of the API the object belongs to
        kind (str): String name describing the kind (type) of the object
        metadata (Metadata): Metadata defining the name, namespace, uid and
            several other fields of the object
        spec: The specification descibes the desired state of the object
            and is defined by the user.
        status: The status attribute describes the current ("real world")
            state of the object. It is a subresource and cannot be manipulated
            by the user. The system will work to bring status into line with
            spec.

    Example:
        .. code:: python

            from krake.data.serializable import ApiObject
            from krake.data.core import Metadata, Status

            class Book(ApiObject):
                api: str = "shelf"  # The book resource belongs to the "shelf api"
                kind: str = "Book"

                metadata: Metadata
                spec: BookSpec
                status: Status

    """

    def __init_subclass__(cls):
        api = cls.api
        kind = cls.kind

        cls.api = dataclasses.field(default=api, metadata={"validate": Equal(api)})
        cls.kind = dataclasses.field(default=kind, metadata={"validate": Equal(kind)})


class PolymorphicSchema(Schema):
    """Schema that is used by :class:`PolymorphicSerializable`

    It declares just one string field :attr:`type` which is used as
    discriminator for the different types.

    There should be a field called exactly like the type. The value of this
    field is passed to the registered schema for deserialziation.

    .. code:: yaml

        ---
        type: float
        float:
            min: 0
            max: 1.0
        ---
        type: int
        int:
            min: 0
            max: 100

    """

    type = fields.String(required=True)

    class Meta:
        # Include unknwon fields. They will be forwared to the subfield schema.
        unknown = INCLUDE

    def __init_subclass__(cls):
        cls._registry = {}

    @classmethod
    def register(cls, type, dataclass):
        """Register a :class:`Serializable` for the given type string

        Args:
            type (str): Type name that should be

        """
        cls._registry[type] = dataclass

    @validates("type")
    def validate_type(self, data, **kwargs):
        if data not in self._registry:
            raise ValidationError(f"Unknown type {data!r}")

    @validates_schema
    def require_data_for_subschema(self, data, **kwargs):
        type_ = data["type"]
        dataclass = self._registry[type_]
        if dataclass.__dataclass_fields__ and type_ not in data:
            raise ValidationError(f"Field is required", type_)

    @post_load
    def load_subschema(self, data, **kwargs):
        type_ = data["type"]
        subschema = self._registry[type_].Schema
        subdata = data.get(type_, {})
        subfields = {type_: subschema().load(subdata)}
        return self.__model__(type=type_, **subfields)

    def _serialize(self, obj, *, many=False):
        if many and obj is not None:
            return [self._serialize(d, many=False) for d in obj]

        ret = self.dict_class()

        for attr_name, field_obj in self.dump_fields.items():
            value = field_obj.serialize(attr_name, obj, accessor=self.get_attribute)

            if value is missing:
                continue

            key = field_obj.data_key if field_obj.data_key is not None else attr_name
            ret[key] = value

        # Add the subfield
        type_ = ret["type"]
        subschema = self._registry[type_].Schema
        value = getattr(obj, type_)
        ret[type_] = subschema().dump(value)

        return ret


class PolymorphicSerializable(Serializable):
    type: str

    @classmethod
    def register(cls, name):
        def decorator(dataclass):
            cls._registry[name] = dataclass
            cls.Schema.register(name, dataclass)
            return dataclass

        return decorator

    def __init_subclass__(cls):
        cls._registry = {}
        cls.Schema = type(
            "Schema",
            (PolymorphicSchema,),
            {"__qualname__": f"{cls.__name__}.Schema", "__model__": cls},
        )

    def __init__(self, **kwargs):
        # Add the subfield as attribute
        type_ = kwargs["type"]
        try:
            value = kwargs.pop(type_)
        except KeyError:
            raise TypeError(f"Missing required keyword argument {type_!r}")
        setattr(self, type_, value)

        super().__init__(**kwargs)
