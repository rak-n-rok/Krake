from datetime import datetime
from typing import List, Dict, Union
from dataclasses import field
import pytest
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


class Person(Serializable):
    given_name: str
    surname: str

    @property
    def fullname(self):
        return f"{self.given_name} {self.surname}"


class Book(Serializable):
    id: int = field(metadata={"immutable": True})
    created: datetime = field(default_factory=datetime.now, metadata={"readonly": True})
    name: str
    author: Person
    characters: List[Person] = field(default_factory=list)


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


def test_update():
    book = Book(
        id=42,
        created=datetime(1979, 10, 12),
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    update = Book(
        id=9780465025275,
        name="Six Easy Pieces",
        created=datetime(2011, 3, 11),
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
        created=datetime(1979, 10, 12),
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    update = Book(
        id=9780465025275,
        name="Six Easy Pieces",
        created=datetime(2011, 3, 11),
        author=None,
    )
    book.update(update)

    assert book.author is None


def test_update_replacing_none_with_value():
    book = Book(
        id=9780465025275,
        name="Six Easy Pieces",
        created=datetime(2011, 3, 11),
        author=None,
    )
    update = Book(
        id=42,
        created=datetime(1979, 10, 12),
        name="The Hitchhiker's Guide to the Galaxy",
        author=Person(given_name="Douglas", surname="Adams"),
    )
    book.update(update)

    assert book.author is update.author
    assert book.author.given_name == "Douglas"
    assert book.author.surname == "Adams"


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

    assert not is_generic_subtype(List[int], Dict)
    assert not is_generic_subtype(List[int], List[str])
    assert not is_generic_subtype(List, List[int])
