import dataclasses
import json
from enum import Enum
from datetime import datetime, date
from typing import get_type_hints, List
from functools import singledispatch
from webargs import fields
from marshmallow import Schema, post_load
from marshmallow_enum import EnumField


default_serializers = {
    int: fields.Integer,
    bool: fields.Boolean,
    str: fields.String,
    float: fields.Float,
    datetime: fields.DateTime,
    date: fields.Date,
}


class ModelizedSchema(Schema):
    __model__ = None

    @post_load
    def create_model(self, data):
        if self.__model__:
            return self.__model__(**data)
        return data


@singledispatch
def serialize(value):
    if hasattr(value, "serialize"):
        return value.serialize()
    raise NotImplementedError(
        "No serialize function registered for type " f"{type(value)}"
    )


def deserialize(cls, value, **kwargs):
    if isinstance(value, bytes):
        value = value.decode()

    if isinstance(value, str):
        value = json.loads(value)

    # Overwrite values by keyword arguments
    if kwargs:
        value = dict(value, **kwargs)

    if hasattr(cls, "__discriminator__"):
        try:
            discriminator = value[cls.__discriminator__]
            cls = cls.__discriminator_map__[discriminator]
        except KeyError:
            pass

    instance, errors = cls.__schema__.load(value)
    if errors:
        raise ValueError(errors)
    assert isinstance(instance, cls)
    return instance


def serializable(cls=None, serializers=default_serializers):
    def wrap(cls):
        schema_attrs = {
            "__module__": cls.__module__,
            "__qualname__": f"{cls.__qualname__}.Schema",
            "__model__": cls,
        }

        if dataclasses.is_dataclass(cls):
            fields = ((f.name, f.type, f.default) for f in dataclasses.fields(cls))
        else:
            fields = (
                (name, type_, getattr(cls, name, dataclasses.MISSING))
                for name, type_ in get_type_hints(cls).items()
            )

        for name, type_, default in fields:
            serializer = resolve_serializer(type_, serializers, default)
            schema_attrs[name] = serializer

        cls.Schema = type("Schema", (ModelizedSchema,), schema_attrs)
        cls.__schema__ = cls.Schema()

        @serialize.register(cls)
        def _(value):
            data, errors = cls.__schema__.dump(value)
            if errors:
                raise ValueError(errors)
            return data

        if hasattr(cls, "__discriminator__"):
            # This initializes the discriminator map at the top most
            # inheritance level.
            if not hasattr(cls, "__discriminator_map__"):
                cls.__discriminator_map__ = {}

            if hasattr(cls, cls.__discriminator__):
                discriminator = getattr(cls, cls.__discriminator__)

                # Special case:
                #     Use the name of enumeration fields
                if isinstance(discriminator, Enum):
                    discriminator = discriminator.name

                # Ensure that the discrimniator value is not already used
                if discriminator in cls.__discriminator_map__:
                    mapped = cls.__discriminator_map__[discriminator]
                    raise ValueError(
                        f"Discriminator {discriminator!r} is "
                        f"already mapped to {mapped!r}"
                    )

                cls.__discriminator_map__[discriminator] = cls

        return cls

    if cls is None:
        return wrap

    return wrap(cls)


def resolve_serializer(type_, serializers, default):
    required = default is dataclasses.MISSING
    allow_none = default is None

    for origin, serializer in serializers.items():
        if issubclass(type_, origin):
            return serializer(allow_none=allow_none, required=required)

    # FIXME: This should be more generic
    if issubclass(type_, Enum):
        return EnumField(type_, allow_none=allow_none, required=required)

    if hasattr(type_, "Schema"):
        return fields.Nested(type_.Schema, allow_none=allow_none, required=required)

    # Special case:
    #     The inner type annotation of the list is used to infer the
    #     inner serialization schema.
    if issubclass(type_, List):
        inner_type = type_.__args__[0]
        inner_serializer = resolve_serializer(
            inner_type, serializers, default=dataclasses.MISSING
        )
        return fields.List(inner_serializer, allow_none=allow_none, required=required)

    raise NotImplementedError(f"No serializer found for {type_!r}")


class SerializableMeta(type):
    def __new__(mcls, name, bases, attrs, init=False):
        cls = super().__new__(mcls, name, bases, attrs)
        cls = dataclasses.dataclass(cls, init=init)
        cls = serializable(cls, serializers=mcls.gather_serializers(cls))

        return cls

    @classmethod
    def gather_serializers(mcls, cls):
        serializers = {}

        for base in reversed(cls.mro()):
            serializers.update(getattr(base, "__serializers__", {}))

        return serializers


class Serializable(metaclass=SerializableMeta):
    __serializers__ = default_serializers

    def __init__(self, **kwargs):
        for field in dataclasses.fields(self):
            value = kwargs.pop(field.name, field.default)
            if value is dataclasses.MISSING:
                raise TypeError(f"Missing keyword argument {field.name!r}")
            setattr(self, field.name, value)
        if kwargs:
            key, _ = kwargs.popitem()
            raise TypeError(f"Got unexpected keyword argument {key!r}")
