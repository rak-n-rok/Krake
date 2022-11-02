"""This module defines a declarative API for defining data models that are
JSON-serializable and JSON-deserializable.
"""
import sys
import dataclasses
from enum import Enum
from datetime import datetime, date
import typing
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
from marshmallow_union import Union as UnionField
from marshmallow.validate import Equal
from marshmallow_enum import EnumField


class ModelizedSchema(Schema):
    """Simple marshmallow schema constructing Python objects in a
    ``post_load`` hook.

    Subclasses can specify a callable attribute ``__model__`` which is
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


def is_generic(cls):
    """Detects any kind of generic, for example `List` or `List[int]`. This
    includes "special" types like Union and Tuple - anything that's subscriptable,
    basically.

    Args:
        cls: Type annotation that should be checked

    Returns:
        bool: True if the passed type annotation is a generic.

    """
    return _is_generic(cls)


def is_base_generic(cls):
    """Detects generic base classes, for example ``List`` but not
    ``List[int]``.

    Args:
        cls: Type annotation that should be checked

    Returns:
        bool: True if the passed type annotation is a generic base.

    """
    return _is_base_generic(cls)


def is_qualified_generic(cls):
    """Detects generics with arguments, for example ``List[int]`` but not
    ``List``

    Args:
        cls: Type annotation that should be checked

    Returns:
        bool: True if the passed type annotation is a qualified generic.
    .
    """
    return is_generic(cls) and not is_base_generic(cls)


def is_generic_subtype(cls, base):
    """Check if a given generic class is a subtype of another generic class

    If the base is a qualified generic, e.g. ``List[int]``, it is checked if
    the types are equal.
    If the base or cls does not have the attribute `__origin__`, e.g. Union, Optional,
    it is checked, if the type of base or cls is equal to the opponent. This is done
    for every possible case.
    If the base and cls have the attribute `__origin__`, e.g. :class:`list`
    for :class:`typing.List`, it is checked if the class is equal to the
    original type of the generic base class.

    Args:
        cls: Generic type
        base: Generic type that should be the base of the given generic type.

    Returns:
        bool: True of the given generic type is a subtype of the given base
        generic type.

    """
    if is_qualified_generic(base):
        return cls == base

    if not has_origin(cls) and not has_origin(base):
        return cls == base

    if not has_origin(cls):
        return cls == _get_origin(base)

    if not has_origin(base):
        return _get_origin(cls) == base

    return _get_origin(cls) == _get_origin(base)


def has_origin(cls):
    return hasattr(cls, "__origin__")


if sys.version_info >= (3, 9):

    def _is_generic(cls):
        if hasattr(cls, "__origin__"):
            return cls.__origin__ is not None

        return isinstance(cls, typing._SpecialForm)

    def _is_base_generic(cls):
        if hasattr(cls, "__args__"):
            return False

        if not hasattr(cls, "__origin__"):
            if not isinstance(cls, typing._SpecialForm):
                return False

        return True

    def _get_origin(cls):
        return cls.__origin__

elif sys.version_info >= (3, 7):

    def _is_generic(cls):
        if isinstance(cls, typing._GenericAlias):
            return True

        if isinstance(cls, typing._SpecialForm):
            return cls not in {typing.Any}

        return False

    def _is_base_generic(cls):
        if isinstance(cls, typing._GenericAlias):
            if cls.__origin__ == typing.Generic:
                return False

            if isinstance(cls, typing._VariadicGenericAlias):
                return True

            return len(cls.__parameters__) > 0

        if isinstance(cls, typing._SpecialForm):
            return cls._name in {"ClassVar", "Union", "Optional"}

        return False

    def _get_origin(cls):
        return cls.__origin__

else:  # Python 3.6

    def _is_generic(cls):
        if isinstance(
            cls, (typing.GenericMeta, typing._Union, typing._Optional, typing._ClassVar)
        ):
            return True

        return False

    def _is_base_generic(cls):
        if isinstance(cls, (typing.GenericMeta, typing._Union)):
            return cls.__args__ in {None, ()}

        if isinstance(cls, typing._Optional):
            return True

        return False

    def _get_origin(cls):
        return cls.__extra__


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

    If ``type_`` has a ``Schema`` attribute which should be a subclass of
    :class:`marshmallow.Schema` a :class.`marshmallow.fields.Nested` field
    will be returned wrapping the schema.

    If ``type_`` has a ``Field`` attribute which should be a subclass of
    :class:`marshmallow.fields.Field` an instance of this attribute will be
    returned.

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

    # If no default value is given in the class definition,
    # it means this field needs to be given
    if metadata.get("missing", missing) is missing:
        metadata.setdefault("required", True)

    if hasattr(type_, "Schema"):
        return fields.Nested(type_.Schema, **metadata)

    if hasattr(type_, "Field"):
        return type_.Field(**metadata)

    if type_ in _native_to_marshmallow:
        return _native_to_marshmallow[type_](**metadata)

    if is_qualified_generic(type_):
        if is_generic_subtype(type_, typing.Union):
            _fields_union = []
            for inner_type in type_.__args__:
                _fields_union.append(field_for_schema(inner_type))
            # Warning: marshmallow-union library does not keep the track
            # of the value type. This may lead to a surprising behavior.
            # e.g.:
            #   # the Integer field accepts string representations of integers
            #   u = Union(fields=[fields.Integer(), fields.String()])
            #   type(u.deserialize('0'))  # -> int
            # See https://github.com/adamboche/python-marshmallow-union#warning
            return UnionField(_fields_union, **metadata)

        if is_generic_subtype(type_, typing.List):
            inner_type = type_.__args__[0]
            inner_serializer = field_for_schema(inner_type)
            return fields.List(inner_serializer, **metadata)

        if is_generic_subtype(type_, typing.Dict):
            keys_field = field_for_schema(type_.__args__[0])
            values_field = field_for_schema(type_.__args__[1])
            return fields.Dict(keys=keys_field, values=values_field, **metadata)

    elif isinstance(type_, type) and issubclass(type_, Enum):
        return EnumField(type_, **metadata)

    raise NotImplementedError(f"No serializer found for {type_!r}")


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
        # parent classes. Therefore, we use the "__dict__" attribute directly
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
        this field. The corresponding marshmallow field allows ``None`` as
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

    .. rubric: Schema-level Validation

    There are cases where multiple levels needs to be validated together. In
    this case, the ``validates`` metadata key for a single field is not
    sufficient anymore. One solution is to overwrite the auto-generated schema
    by a custom schema using the
    :func:`marshmallow.decorators.validates_schema` decorator.

    Another solution is leveraging the ``__post_init__()`` method of
    dataclasses. The fields can be validated in this method and a raised
    :class:`marshmallow.ValidationError` will propagate to the Schema
    deserialization method.

    .. code:: python

        from marshmallow import ValidationError

        class Interval(Serializable):
            max: int
            min: int

            def __post_init__(self):
                if self.min > self.max:
                    raise ValidationError("'min' must not be greater than 'max'")

        # This will raise a ValidationError
        interval = Interval.deserialize({"min": 2, "max": 1})

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

        self.__post_init__()

    def __post_init__(self):
        """The :meth:`__init__` method calls this method after all fields are
        initialized.

        It is mostly useful for schema-level validation (see above).

        For now, :class:`Serializable` does not support init-only variables
        because they do not make much sense for object stored in a database.
        This means no additional parameters are passed to this method.
        """
        pass

    @classmethod
    def readonly_fields(cls, prefix=None):
        """Return the name of all read-only fields. Nested fields are returned
        with dot-notation, for lists also. In this case, the argument is the one taken
        into account for looking at the read-only fields.

        Example:

        .. code:: python

            class Comment(Serializable):
                id: int = field(metadata={"readonly": True})
                content: str

            class BookMetadata(Serializable):
                name: str = field(metadata={"readonly": True})
                published: datetime = field(metadata={"readonly": True})
                last_borrowed: datetime

            class Book(Serializable):
                id: int = field(metadata={"readonly": True})
                metadata: BookMetadata
                status: str
                comments: List[Comment]

            expected = {'id', 'metadata.name', 'metadata.published', 'comment.id'}
            assert Book.readonly_fields() == expected

        Args:
            prefix (str, optional): Used for internal recursion

        Returns:
            set: Set of field names that are marked as with ``readonly`` in their
            metadata.

        """
        found = set()

        for field in dataclasses.fields(cls):
            # Update the prefix if needed
            new_prefix = field.name
            if prefix:
                new_prefix = f"{prefix}.{new_prefix}"

            if dataclasses.is_dataclass(field.type):
                # Go into the nested Serializable
                found |= field.type.readonly_fields(prefix=new_prefix)
            elif field.metadata.get("readonly", False):
                found.add(new_prefix)
            elif is_qualified_generic(field.type) and is_generic_subtype(
                field.type, typing.List
            ):
                inside = field.type.__args__[0]
                # For the lists of elements, go into the type listed,
                # if it is a Serializable
                if issubclass(field.type.__args__[0], Serializable):
                    found |= inside.readonly_fields(prefix=new_prefix)

        return found

    @classmethod
    def subresources_fields(cls):
        """Return the name of all fields that are defined as subresource.

        Returns:
            set: Set of field names that are marked as ``subresource`` in their
                metadata

        """
        return set(
            field.name
            for field in dataclasses.fields(cls)
            if field.metadata.get("subresource")
        )

    @classmethod
    def fields_ignored_by_creation(cls):
        """Return the name of all fields that do not have to be provided during the
        creation of an instance.

        Returns:
            set: Set of name of fields that are either subresources or read-only, or
            nested read-only fields.

        """
        return cls.readonly_fields() | cls.subresources_fields()

    def serialize(self, creation_ignored=False):
        """Serialize the object using the generated :attr:`Schema`.

        Args:
            creation_ignored (bool): if True, all attributes not needed at the
                creation are ignored. This contains the read-only and subresources,
                which can only be created by the API.

        Returns:
            dict: JSON representation of the object

        """
        exclude = set()

        if creation_ignored:
            exclude = self.fields_ignored_by_creation()

        return self.Schema(exclude=exclude).dump(self)

    @classmethod
    def deserialize(cls, data, creation_ignored=False):
        """Loading an instance of the class from JSON-encoded data.

        Args:
            data (dict): JSON dictionary that should be deserialized.
            creation_ignored (bool): if True, all attributes not needed at the
                creation are ignored. This contains the read-only and subresources,
                which can only be created by the API.

        Raises:
            marshmallow.ValidationError: If the data is invalid

        """
        exclude = set()
        if creation_ignored:
            exclude = cls.fields_ignored_by_creation()

        return cls.Schema(exclude=exclude).load(data)

    def update(self, overwrite):
        """Update data class fields with corresponding fields from the
        overwrite object.

        If a field is marked as _subresource_ or _readonly_ it is
        not modified. If a field is marked as _immutable_ and there is
        an attempt to update the value, the :class:`ValueError` is raised.
        Otherwise, attributes from overwrite will replace
        attributes from the current object.

        The :meth:`update` must ignore the _subresource_ and _readonly_ fields,
        to avoid accidentally overwriting e.g. status fields in
        read-modify-write scenarios.

        The function works recursively for nested :class:`Serializable`
        attributes which means the :meth:`update` method of the attribute will
        be used. This means the identity of a :class:`Serializable` attribute
        will not change unless the current attribute or the overwrite
        attribute is :data:`None`.

        All other attributes are updated by assigning **references** from the
        overwrite attributes to the current object. This leads to a behavior
        similar to "shallow copying" (see :func:`copy.copy`). If the attribute
        is mutable, e.g. :class:`list` or :class:`dict`, the attribute in the
        current object will reference the same object as in the overwrite
        object.

        Args:
            overwrite (Serializable): Serializable object will be merged with
                the current object.
        Raises:
            ValueError: If there is an attempt to update an _immutable_ field.

        """
        for field in dataclasses.fields(self):

            if any(
                (
                    field.metadata.get("subresource", False),
                    field.metadata.get("readonly", False),
                )
            ):
                continue

            if field.metadata.get("immutable", False):
                if getattr(self, field.name) != getattr(overwrite, field.name):
                    raise ValueError(
                        f"Trying to update an immutable field: {field.name}"
                    )

                continue

            value = getattr(overwrite, field.name)

            if isinstance(field.type, type) and issubclass(field.type, Serializable):
                # Overwrite value is None, just set it directly
                if value is None:
                    setattr(self, field.name, None)
                # Current attribute is None, copy the whole attribute
                elif getattr(self, field.name) is None:
                    setattr(self, field.name, value)
                # Update field by field
                else:
                    getattr(self, field.name).update(value)
            else:
                # We do not make copies from attributes. This leads to
                # behavior similar to "shallow copying". If the overwrite
                # attribute is mutable, e.g. a dict, list, it will be just
                # referenced here.
                setattr(self, field.name, value)


class ApiObject(Serializable):
    """Base class for objects manipulated via REST API.

    :attr:`api` and :attr:`kind` should be defined as simple string class
    :variables. They are automatically converted into dataclass fields with
    :corresponding validators.

    Attributes:
        api (str): Name of the API the object belongs to
        kind (str): String name describing the kind (type) of the object

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

        # HACK:
        #   dataclasses.dataclass() checks if the class implements its own
        #   __repr__ method (by checking directly its presence in __dict__). We
        #   want to use the same __repr__() implementation for every subclass.
        #   Therefore, we put an explicit reference to ApiObject.__repr__()
        #   into the class' __dict__.
        if "__repr__" not in cls.__dict__:
            cls.__repr__ = ApiObject.__repr__

    def __repr__(self):
        representation = [f"{self.api}.{self.kind}"]

        if hasattr(self.metadata, "namespace") and self.metadata.namespace:
            representation.append(f"namespace={self.metadata.namespace!r}")

        if hasattr(self.metadata, "name"):
            representation.append(f"name={self.metadata.name!r}")

        if hasattr(self.metadata, "uid"):
            representation.append(f"uid={self.metadata.uid!r}")

        if hasattr(self, "items"):
            representation.append(f"length={len(self.items)}")

        return f"<{' '.join(representation)}>"


class PolymorphicContainerSchema(Schema):
    """Schema that is used by :class:`PolymorphicContainer`

    It declares just one string field :attr:`type` which is used as
    discriminator for the different types.

    There should be a field called exactly like the type. The value of this
    field is passed to the registered schema for deserialization.

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

    Every subclass will create its own internal subtype registry.

    """

    type = fields.String(required=True)

    class Meta:
        # Include unknown fields. They will be forwarded to the subfield schema.
        unknown = INCLUDE

    def __init_subclass__(cls):
        cls._registry = {}

    @classmethod
    def register(cls, type, dataclass):
        """Register a :class:`Serializable` for the given type string

        Args:
            type (str): Type name that should be used as discriminator
            dataclass (object): Dataclass that will be used when the type
                field equals the specified name.

        Raises:
            ValueError: If the type name is already registered

        """
        if type in cls._registry:
            raise ValueError(f"{type!r} already registered by {cls._registry[type]!r}")

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
            raise ValidationError("Field is required", type_)

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


class PolymorphicContainer(Serializable):
    """Base class for polymorphic serializable objects.

    The polymorphic serializable has a string attribute :attr:`type` which is
    used as discriminator for the different types. There is an attribute named
    exactly like the value of the :attr:`type` attribute containing the
    deserialized subtype.

    Every new subclass will create its own :attr:`Schema` attribute. This
    means every subclass has its own internal subtype registry.

    Attributes:
        Schema (PolymorphicContainerSchema): Schema that will be used for
            (de-)serialization of the class.

    Example:

    .. code:: python

        from krake.data.serializable import Serializable, PolymorphicContainer

        class ValueSpec(PolymorphicContainer):
            pass

        @ProviderSpec.register("float")
        class FloatSpec(Serializable):
            min: float
            max: float

        @ProviderSpec.register("bool")
        class BoolSpec(Serializable):
            pass

        # Deserialization
        spec = ProviderSpec.deserialize({
            "type": "float",
            "float": {
                "min": 0,
                "max": 1.0,
            },
        })
        assert isinstance(spec.float, FloatSpec)

        # Serialization
        assert ProviderSpec(type="bool", bool=BoolSpec()).serialize() == {
            "type": bool,
            "bool": {},
        }

    """

    type: str

    @classmethod
    def register(cls, name):
        """Decorator function for registering a class under a unique name.

        Args:
            name (str): Name that will be used as value for the :attr:`type`
                field to identify the decorated class.

        Returns:
            callable: Decorator that will register the decorated class in
            the polymorphic schema (see
            :meth:`PolymorphicContainerSchema.register`).

        """

        def decorator(dataclass):
            cls.Schema.register(name, dataclass)
            return dataclass

        return decorator

    def __init_subclass__(cls):
        # Create a new Schema attribute for every subclass. Hence, every
        # subclass will use its very own subtype registry.
        cls.Schema = type(
            "Schema",
            (PolymorphicContainerSchema,),
            {"__qualname__": f"{cls.__name__}.Schema", "__model__": cls},
        )

        # HACK:
        #   dataclasses.dataclass() checks if the class implements its own
        #   __eq__ method (by checking directly its presence in __dict__). We
        #   want to use the same __eq__() implementation for every subclass.
        #   Therefore, we put an explicit reference to PolymorphicContainer.__eq__()
        #   into the class' __dict__.
        if "__eq__" not in cls.__dict__:
            cls.__eq__ = PolymorphicContainer.__eq__

    def __init__(self, **kwargs):
        # Add the subfield as attribute
        try:
            type_ = kwargs["type"]
            value = kwargs.pop(type_)
        except KeyError as err:
            raise TypeError("Missing required keyword argument 'type'") from err
        setattr(self, type_, value)

        super().__init__(**kwargs)

    def update(self, overwrite):
        """Update the polymorphic container with fields from the overwrite
        object.

        A reference to the polymorphic field – the field called like the value
        of the :attr:`type` attribute – of the overwrite object is assigned to
        the current object even if the types of the current object and the
        overwrite object are identical.

        Args:
            overwrite (Serializable): Serializable object will be merged with
                the current object.

        """
        # Clear current type
        delattr(self, self.type)

        # Copy new type
        self.type = overwrite.type
        value = getattr(overwrite, overwrite.type)
        setattr(self, overwrite.type, value)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False

        # If the other element has no "type", it cannot be a PolymorphicContainer.
        # If it has no container with the same type as the current object, then it is
        # not a container of the same type, thus they are different.
        if not hasattr(other, "type") or not hasattr(other, self.type):
            return False

        return self.type == other.type and getattr(self, self.type) == getattr(
            other, other.type
        )
