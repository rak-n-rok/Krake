from typing import List
import pytest
from marshmallow import ValidationError

from krake.data.serializable import Serializable, ApiObject


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
    class Person(Serializable):
        given_name: str
        surname: str

        @property
        def fullname(self):
            return f"{self.given_name} {self.surname}"

    class Book(Serializable):
        id: int
        name: str
        author: Person

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
    class Character(Serializable):
        given_name: str
        surname: str

        @property
        def fullname(self):
            return f"{self.given_name} {self.surname}"

    class Book(Serializable):
        id: int
        name: str
        characters: List[Character]

    book = Book(
        id=42,
        name="The Hitchhiker's Guide to the Galaxy",
        characters=[
            Character(given_name="Arthur", surname="Dent"),
            Character(given_name="Ford", surname="Perfect"),
        ],
    )
    data = book.serialize()

    assert data["id"] == 42
    assert data["name"] == "The Hitchhiker's Guide to the Galaxy"
    assert isinstance(data["characters"], list)
    assert len(data["characters"]) == 2

    assert data["characters"][0]["given_name"] == "Arthur"
    assert data["characters"][0]["surname"] == "Dent"

    assert data["characters"][1]["given_name"] == "Ford"
    assert data["characters"][1]["surname"] == "Perfect"


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
