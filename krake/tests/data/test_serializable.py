from datetime import datetime
from typing import List, Dict, Union
import pytest
from dataclasses import field
from krake.data.config import HooksConfiguration
from krake.data.core import Metadata
from krake.data.kubernetes import ClusterList
from marshmallow import ValidationError

from krake.data.serializable import (
    Serializable,
    ApiObject,
    PolymorphicContainer,
    is_generic,
    is_base_generic,
    is_qualified_generic,
    is_generic_subtype,
)
from krake import utils
from tests.factories.core import MetadataFactory, GlobalMetricFactory
from tests.factories.kubernetes import ApplicationFactory, ClusterFactory
from tests.factories.openstack import ProjectFactory


class Person(Serializable):
    given_name: str
    surname: str

    @property
    def fullname(self):
        return f"{self.given_name} {self.surname}"


class Book(Serializable):
    id: int = field(metadata={"immutable": True})
    created: datetime = field(default_factory=utils.now, metadata={"readonly": True})
    name: str
    author: Person
    characters: List[Person] = field(default_factory=list)
    edition: Union[str, dict] = field(default=None)


def test_serializable():
    class Application(Serializable):
        id: int
        name: str
        optional: str = "optional"
        kind: str = "app"

        __metadata__ = {"discriminator": "kind"}

    assert Application.Schema is not None

    app = Application(id=42, name="Arthur Dent")
    assert app.id == 42
    assert app.name == "Arthur Dent"
    assert app.kind == "app"
    assert app.optional == "optional"

    data = app.serialize()

    assert data["id"] == 42
    assert data["name"] == "Arthur Dent"
    assert data["kind"] == "app"
    assert data["optional"] == "optional"

    # Missing keyword arguments
    with pytest.raises(TypeError):
        Application(id=42)

    # Additional keyword arguments
    with pytest.raises(TypeError):
        Application(id=42, name="My fancy model", value=72)

    instance = Application.deserialize(data)
    assert isinstance(instance, Application)
    assert instance.id == app.id
    assert instance.name == app.name
    assert instance.kind == app.kind
    assert instance.optional == app.optional


def test_nested_attrs():
    book = Book(
        id=42,
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    data = book.serialize()

    assert data["id"] == 42
    assert data["name"] == "The Hitchhiker's Guide to the Galaxy"

    assert isinstance(data["author"], dict)
    assert data["author"]["given_name"] == "Douglas"
    assert data["author"]["surname"] == "Adams"


def test_list_attr():
    book = Book(
        id=42,
        name="The Hitchhiker's Guide to the Galaxy",
        author=None,
        characters=[
            Person(given_name="Arthur", surname="Dent"),
            Person(given_name="Ford", surname="Perfect"),
        ],
    )
    data = book.serialize()

    assert data["id"] == 42
    assert data["name"] == "The Hitchhiker's Guide to the Galaxy"
    assert data["author"] is None
    assert isinstance(data["characters"], list)
    assert len(data["characters"]) == 2

    assert data["characters"][0]["given_name"] == "Arthur"
    assert data["characters"][0]["surname"] == "Dent"

    assert data["characters"][1]["given_name"] == "Ford"
    assert data["characters"][1]["surname"] == "Perfect"


def test_union_attr():
    book_first_edition = Book(
        id=42,
        name="The Hitchhiker's Guide to the Galaxy",
        author=None,
        edition="First",
    )
    book_second_edition = Book(
        id=42,
        name="The Hitchhiker's Guide to the Galaxy",
        author=None,
        edition={"edition": "Second"},
    )
    data_first_edition = book_first_edition.serialize()
    data_second_edition = book_second_edition.serialize()

    assert data_first_edition["id"] == data_second_edition["id"] == 42
    assert (
        data_first_edition["name"]
        == data_second_edition["name"]
        == "The Hitchhiker's Guide to the Galaxy"
    )
    assert data_first_edition["author"] == data_first_edition["author"] is None
    assert data_first_edition["edition"] == "First"
    assert data_second_edition["edition"] == "{'edition': 'Second'}"


def test_update():
    book = Book(
        id=42,
        created=datetime(1979, 10, 12).astimezone(),
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    update = Book(
        id=42,
        name="Six Easy Pieces",
        created=datetime(2011, 3, 11).astimezone(),
        author=Person(given_name="Richard", surname="Feynman"),
    )

    book.update(update)

    assert book.id == 42
    assert book.created == book.created
    assert book.name == "Six Easy Pieces"
    assert book.author is not update.author
    assert book.author.given_name == "Richard"
    assert book.author.surname == "Feynman"


def test_update_replacing_value_with_none():
    book = Book(
        id=42,
        created=datetime(1979, 10, 12).astimezone(),
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    update = Book(
        id=42,
        name="Six Easy Pieces",
        created=datetime(2011, 3, 11).astimezone(),
        author=None,
    )
    book.update(update)

    assert book.author is None


def test_update_replacing_none_with_value():
    book = Book(
        id=42,
        name="Six Easy Pieces",
        created=datetime(2011, 3, 11).astimezone(),
        author=None,
    )
    update = Book(
        id=42,
        created=datetime(1979, 10, 12).astimezone(),
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    book.update(update)

    assert book.author is update.author
    assert book.author.given_name == "Douglas"
    assert book.author.surname == "Adams"


def test_update_read_only_field():
    book = Book(
        id=42,
        created=datetime(1979, 10, 12).astimezone(),
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    update = book
    update.created = datetime(2021, 2, 11).astimezone()

    book.update(update)

    assert book.id == 42
    assert book.created == book.created
    assert book.name == "The Hitchhiker's Guide to the Galaxy"
    assert book.author is update.author
    assert book.author.given_name == "Douglas"
    assert book.author.surname == "Adams"


def test_update_immutable_field():
    book = Book(
        id=42,
        name="The Hitchhiker's Guide to the Galaxy",
        created=datetime(1979, 10, 12).astimezone(),
        author=Person(given_name="Douglas", surname="Adams"),
    )
    update = Book(
        id=1,
        name="Six Easy Pieces",
        created=datetime(2011, 3, 11).astimezone(),
        author=Person(given_name="Richard", surname="Feynman"),
    )
    with pytest.raises(ValueError, match="Trying to update an immutable field: id"):
        book.update(update)


def test_api_object():
    class Book(ApiObject):
        api: str = "shelf"
        kind: str = "Book"

    book = Book()
    assert book.api == "shelf"
    assert book.kind == "Book"

    book = Book.deserialize({})
    assert book.api == "shelf"
    assert book.kind == "Book"

    with pytest.raises(ValidationError):
        Book.deserialize({"api": "wrong-api"})

    with pytest.raises(ValidationError):
        Book.deserialize({"kind": "Letter"})


def test_creation_ignored():
    class Status(Serializable):
        state: str

    class Metadata(Serializable):
        created: str = field(metadata={"readonly": True})
        name: str = field(metadata={"readonly": True})
        changing: str

    class Annotations(Serializable):
        metadata: Metadata

    class Application(Serializable):
        id: int
        kind: str = "app"
        status: Status = field(metadata={"subresource": True})
        metadata: Metadata
        annotations: List[Annotations]

    annotation_1 = Annotations(
        metadata=Metadata(created=None, name="annot_1", changing="foo")
    )
    annotation_2 = Annotations(
        metadata=Metadata(created="yes", name="annot_2", changing="bar")
    )
    app = Application(
        id=42,
        status=None,
        metadata=Metadata(created=None, name="name", changing="foobar"),
        annotations=[annotation_1, annotation_2],
    )
    serialized = app.serialize()

    assert serialized["metadata"]["changing"] == "foobar"
    assert serialized["metadata"]["created"] is None
    assert serialized["annotations"][0]["metadata"]["created"] is None
    assert serialized["annotations"][1]["metadata"]["created"] == "yes"

    # The readonly and subresources are ignored
    deserialized = Application.deserialize(serialized, creation_ignored=True)

    assert deserialized.status is None
    assert deserialized.metadata.created is None
    assert deserialized.annotations[0].metadata.created is None
    assert deserialized.annotations[1].metadata.created is None

    # Do not ignore the readonly and subresources
    with pytest.raises(ValidationError) as err:
        Application.deserialize(serialized)

    error_messages = err.value.messages

    assert "status" in error_messages
    assert "metadata" in error_messages
    assert "created" in error_messages["metadata"]
    assert "name" not in error_messages["metadata"]
    assert "created" in error_messages["annotations"][0]["metadata"]
    assert 1 not in error_messages["annotations"]


def test_api_object_repr():
    """Verify the representation of the instances of :class:`ApiObject`."""
    app = ApplicationFactory(metadata__name="my-app", metadata__namespace="my-ns")
    app_repr = (
        f"<kubernetes.Application namespace='my-ns'"
        f" name='my-app' uid={app.metadata.uid!r}>"
    )
    assert repr(app) == app_repr

    project = ProjectFactory(metadata__name="my-project", metadata__namespace="other")
    project_repr = (
        f"<openstack.Project namespace='other'"
        f" name='my-project' uid={project.metadata.uid!r}>"
    )
    assert repr(project) == project_repr

    # Non-namespaced
    metric = GlobalMetricFactory(metadata__name="my-metric")
    metric_repr = f"<core.GlobalMetric name='my-metric' uid={metric.metadata.uid!r}>"
    assert repr(metric) == metric_repr

    # List
    items = [ClusterFactory()] * 10
    cluster_list = ClusterList(items=items)
    cluster_list_repr = "<kubernetes.ClusterList length=10>"
    assert repr(cluster_list) == cluster_list_repr


class DataSpec(PolymorphicContainer):
    pass


@DataSpec.register("float")
class FloatSpec(Serializable):
    min: float
    max: float


@DataSpec.register("bool")
class BoolSpec(Serializable):
    pass


def test_polymorphic_serialize():
    assert DataSpec(type="float", float=FloatSpec(min=0, max=1.0)).serialize() == {
        "type": "float",
        "float": {"min": 0, "max": 1.0},
    }
    assert DataSpec(type="bool", bool=BoolSpec()).serialize() == {
        "type": "bool",
        "bool": {},
    }


def test_polymorphic_deserialize():
    spec = DataSpec.deserialize({"type": "float", "float": {"min": 0, "max": 1.0}})
    assert isinstance(spec, DataSpec)
    assert hasattr(spec, "float")
    assert isinstance(spec.float, FloatSpec)
    assert spec.float.min == 0
    assert spec.float.max == 1.0

    spec = DataSpec.deserialize({"type": "bool"})
    assert isinstance(spec, DataSpec)
    assert hasattr(spec, "bool")
    assert isinstance(spec.bool, BoolSpec)


def test_polymorphic_multiple_subfields():
    with pytest.raises(TypeError) as err:
        DataSpec(type="float", float=None, bool=None)
    assert "Got unexpected keyword argument 'bool'" == str(err.value)


def test_polymorphic_update():
    spec = DataSpec(type="float", float=FloatSpec(min=0, max=1.0))
    update = DataSpec(type="bool", bool=BoolSpec())

    spec.update(update)

    assert spec.type == "bool"
    assert spec.bool == update.bool
    assert spec.bool is update.bool


def test_polymorphic_equality():
    """Verify the equality check of the :class:`PolymorphicContainer`."""
    # Inequality checks
    spec1 = DataSpec(type="float", float=FloatSpec(min=0, max=1.0))
    spec2 = DataSpec(type="float", float=FloatSpec(min=100, max=200))
    assert spec1 != spec2
    assert spec2 != spec1

    spec3 = DataSpec(type="bool", bool=BoolSpec())
    assert spec2 != spec3
    assert spec3 != spec2

    # Equality checks
    spec4 = DataSpec(type="float", float=FloatSpec(min=0, max=1.0))
    assert spec1 == spec4

    spec5 = DataSpec(type="bool", bool=BoolSpec())
    assert spec3 == spec5


def test_polymorphic_creation_error_handling():
    """Verify that creating a :class:`PolyMorphicContainer` without the `type` attribute
    also raises an error.
    """
    with pytest.raises(TypeError, match="Missing required keyword argument 'type'"):
        DataSpec(float=FloatSpec(min=0, max=1.0))


def test_polymorphic_register_error_handling():
    """Verify that adding a :class:`PolyMorphicContainerSpec` with an already registered
    type to a :class:`PolyMorphicContainer` leads to an exception."""
    with pytest.raises(ValueError, match="'bool' already registered by "):

        @DataSpec.register("bool")
        class OtherSpec(Serializable):
            pass


def test_polymorphic_validate_type_error_handling():
    """Verify that deserializing an instance of :class:`PolyMorphicContainerSpec` where
    the "type" attribute is removed will lead to an exception.
    """
    serialized = DataSpec(type="float", float=FloatSpec(min=0, max=1.0)).serialize()

    serialized["type"] = "non-existing"
    with pytest.raises(ValidationError, match="Unknown type 'non-existing'"):
        DataSpec.deserialize(serialized)


def test_polymorphic_validate_subschema_error_handling():
    """Verify that deserializing an instance of :class:`PolyMorphicContainerSpec` where
    the container attribute is removed will lead to an exception.
    """
    serialized = DataSpec(type="float", float=FloatSpec(min=0, max=1.0)).serialize()

    del serialized["float"]
    with pytest.raises(ValidationError, match="Field is required"):
        DataSpec.deserialize(serialized)


def test_is_generic():
    assert is_generic(List)
    assert is_generic(List[int])
    assert is_generic(Union)
    assert is_generic(Union[int, None])
    assert is_generic(Dict)
    assert is_generic(Dict[str, int])

    assert not is_generic(str)
    assert not is_generic(int)
    assert not is_generic(object)


def test_is_base_generic():
    assert is_base_generic(List)
    assert is_base_generic(Dict)
    assert is_base_generic(Union)

    assert not is_base_generic(List[int])
    assert not is_base_generic(Union[int, None])
    assert not is_base_generic(Dict[int, str])


def test_is_qualified_generic():
    assert is_qualified_generic(List[int])
    assert is_qualified_generic(Union[int, None])
    assert is_qualified_generic(Dict[int, str])

    assert not is_qualified_generic(List)
    assert not is_qualified_generic(Dict)
    assert not is_qualified_generic(Union)


def test_is_generic_subtype():
    assert is_generic_subtype(List[int], List)
    assert is_generic_subtype(List[int], List[int])
    assert is_generic_subtype(List, List)
    assert is_generic_subtype(Union, Union)
    assert is_generic_subtype(Union[int, dict], Union)
    assert is_generic_subtype(Union[int, dict], Union[int, dict])

    assert not is_generic_subtype(List[int], Dict)
    assert not is_generic_subtype(List[int], List[str])
    assert not is_generic_subtype(List, List[int])
    assert not is_generic_subtype(Union[int, dict], Union[int, str])
    assert not is_generic_subtype(Union, Union[int, dict])
    assert not is_generic_subtype(Union[int, dict], Dict)
    assert not is_generic_subtype(List, Union[int, dict])


def test_schema_validation():
    class Interval(Serializable):
        max: int
        min: int

        def __post_init__(self):
            if self.min > self.max:
                raise ValidationError("'min' must not be greater than 'max'")

    with pytest.raises(ValidationError) as excinfo:
        Interval.deserialize({"min": 72, "max": 42})

    assert "_schema" in excinfo.value.messages


@pytest.mark.parametrize(
    "label_value",
    [
        [{"key": "key",                 "value": "value"}],
        [{"key": "key1",                "value": "value"}],
        [{"key": "key",                 "value": "value1"}],
        [{"key": "key-one",             "value": "value"}],
        [{"key": "key",                 "value": "value-one"}],
        [{"key": "key-1",               "value": "value"}],
        [{"key": "key",                 "value": "value-1"}],
        [{"key": "k",                   "value": "value"}],
        [{"key": "key",                 "value": "v"}],
        [{"key": "kk",                  "value": "value"}],
        [{"key": "key",                 "value": "vv"}],
        [{"key": "k.k",                 "value": "value"}],
        [{"key": "key",                 "value": "v-v"}],
        [{"key": "key_one.one",         "value": "value"}],
        [{"key": "key",                 "value": "value.one_one"}],
        [{"key": "url.com/name",        "value": "value"}],
        [{"key": "url1.com/name",       "value": "value"}],
        [{"key": "url-suffix/name",     "value": "value"}],
        [{"key": "url.com/name-one",    "value": "value"}],
        [{"key": "url1.com/name-one",   "value": "value"}],
        [{"key": "url-suffix/name-one", "value": "value"}],
    ],
)
def test_label_validation(label_value):
    # Test that valid label keys and values are accepted.
    data = MetadataFactory(labels=label_value)

    Metadata.deserialize(data.serialize())


@pytest.mark.parametrize(
    "label_value",
    [
        [{"key": "key!",           "value": "value"}],
        [{"key": "key.",           "value": "value"}],
        [{"key": "-key",           "value": "value"}],
        [{"key": "-k",             "value": "value"}],
        [{"key": "-",              "value": "value"}],
        [{"key": "url/second/key", "value": "value"}],
        [{"key": "url/",           "value": "value"}],
        [{"key": "/key",           "value": "value"}],
        [{"key": "k" * 70,         "value": "value"}],
        [{"key": "p" * 300 + "/" + "k" * 60, "value": "value"}],
    ],
)
def test_label_validation_reject_str_key(label_value):
    # Test that invalid strings as label keys raise an exception.
    data = MetadataFactory(labels=label_value)
    with pytest.raises(ValidationError, match="Label key"):
        Metadata.deserialize(data.serialize())


@pytest.mark.parametrize(
    "label_value", [
        [{"key": True, "value": "value"}],
        [{"key": None, "value": "value"}],
        [{"key": 10,   "value": "value"}],
        [{"key": 0.1,  "value": "value"}]
    ]
)
def test_label_validation_reject_key(label_value):
    """Test that invalid types as label keys raise an exception."""
    # supplying the label to MetadataFactory would lead to implicit type conversion
    data = MetadataFactory().serialize()
    data["labels"] = label_value
    with pytest.raises(ValidationError):
        Metadata.deserialize(data)


@pytest.mark.parametrize(
    "label_value",
    [
        [{"key": "key", "value": "value$"}],
        [{"key": "key", "value": "value."}],
        [{"key": "key", "value": "-value"}],
        [{"key": "key", "value": "v-"}],
        [{"key": "key", "value": "."}],
        [{"key": "key", "value":  "url.com/value"}],
        [{"key": "key", "value": "v" * 70}],
    ],
)
def test_label_validation_reject_str_value(label_value):
    # Test that invalid strings as label values raise an exception.
    data = MetadataFactory(labels=label_value)

    with pytest.raises(ValidationError, match="Label value"):
        Metadata.deserialize(data.serialize())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://1.2.3.4",
        "http://1.2.3.4:8080",
        "http://host.com",
        "http://host.com:8080",
    ],
)
def test_external_endpoint_validation_valid(hooks_config, endpoint):
    """Test the validation of the external endpoint used in the "complete" hook with
    URL that are valid.
    """
    config_dict = hooks_config.serialize()

    config_dict["complete"]["external_endpoint"] = endpoint
    HooksConfiguration.deserialize(config_dict)


@pytest.mark.parametrize(
    "endpoint",
    [
        "host.com",
        "http:/host.com",
        # With port
        "$host.com:8080",
        "http:/host.com:8080",
        "$host.com:8080",
        # With path
        "$host.com/path/to/krake",
        "http:/host.com/path/to/krake",
        "$host.com/path/to/krake",
        # With port and path
        "$host.com:8080/path/to/krake",
        "http:/host.com:8080/path/to/krake",
        "$host.com:8080/path/to/krake",
    ],
)
def test_external_endpoint_validation_invalid(hooks_config, endpoint):
    """Test the validation of the external endpoint used in the "complete" hook with
    URL that are invalid.
    """
    config_dict = hooks_config.serialize()

    config_dict["complete"]["external_endpoint"] = endpoint
    with pytest.raises(ValidationError, match="A scheme should be provided"):
        HooksConfiguration.deserialize(config_dict)


@pytest.mark.parametrize(
    "endpoint",
    [
        "socket://host.com",
        # With port
        "socket://host.com:8080",
        # With path
        "socket://host.com/path/to/krake",
        # With port and path
        "socket://host.com:8080/path/to/krake",
    ],
)
def test_external_endpoint_validation_invalid_scheme(hooks_config, endpoint):
    config_dict = hooks_config.serialize()

    config_dict["complete"]["external_endpoint"] = endpoint
    with pytest.raises(ValidationError, match="scheme 'socket' is not supported"):
        HooksConfiguration.deserialize(config_dict)


@pytest.mark.parametrize(
    "label_value",
    [
        [{"key": "key", "value": True}],
        [{"key": "key", "value": None}],
        [{"key": "key", "value": []}],
        [{"key": "key", "value": [None, True]}],
        [{"key": "key", "value": ["foo", "bar"]}],
        [{"key": "key", "value": {"invalid": "value"}}],
    ],
)
def test_label_validation_reject_value(label_value):
    """Test that invalid types as label values raise an exception."""
    data = MetadataFactory().serialize()
    data["labels"] = label_value

    with pytest.raises(ValidationError):
        Metadata.deserialize(data)


def test_label_multiple_errors():
    """ "Test that invalid types as label values raise an exception."""
    # 1. Label value is wrong
    data = MetadataFactory().serialize()
    data["labels"] = [{"key": "key1", "value": [None, True]}]
    with pytest.raises(ValidationError) as info:
        Metadata.deserialize(data)

    label_errors = info.value.messages["labels"]
    assert len(label_errors) == 1
    all_keys = list(label_errors[0].values())
    assert len(all_keys) == 1
    assert all_keys[0] == ['Not a valid string.']

    # 2. Label key and value are wrong
    data = MetadataFactory().serialize()
    data["labels"] = [{"key": False, "value": True}]
    with pytest.raises(ValidationError) as info:
        Metadata.deserialize(data)

    label_errors = info.value.messages["labels"]
    assert len(label_errors) == 1
    # Take the only key of each dictionary in list label_errors:
    # name of the invalid key or value
    assert label_errors[0] == {
        'key': ['Not a valid string.'],
        'value': ['Not a valid string.']}

    # 3. Different issues:
    #    - 1st label: invalid value
    #    - 2nd label: valid
    #    - 3rd label: invalid key
    data = MetadataFactory().serialize()
    data["labels"] = [
        {"key": "key1", "value":  ["a", "b"]},
        {"key": "key2", "value":  "valid"},
        {"key": "$$", "value": "valid"},
        {"key": True, "value": True}]
    with pytest.raises(ValidationError) as info:
        print(info)
        Metadata.deserialize(data)

    label_errors = info.value.messages["labels"]
    assert len(label_errors) == 3
    assert label_errors[0] == {'value': ['Not a valid string.']}
    assert label_errors[2] == {'_schema': [{'$$':
        "Label key '$$' does not match the regex '^((\\\\w|(\\\\w[\\\\w\\\\-_.]{0,251}\\\\w))\\\\/)?(\\\\w|(\\\\w[\\\\w\\\\-_.]{0,61}\\\\w))$'."}]}
    assert label_errors[3] == {
        'key': ['Not a valid string.'],
        'value': ['Not a valid string.']}
