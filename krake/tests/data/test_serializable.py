from dataclasses import dataclass
from typing import List
import pytest

from krake.data.serializable import serialize, deserialize, Serializable, serializable


def test_functional_api():
    @serializable
    class Application(object):
        id: int
        name: str
        kind: str = "app"
        optional: str = "optional"

        __metadata__ = {"discriminator": "kind"}

        def __init__(self, id, name, kind=None, optional=None):
            if kind:
                assert kind == self.kind
            self.id = id
            self.name = name
            if optional is not None:
                self.optional = optional

    assert Application.Schema is not None
    assert Application.__metadata__["schema"] is not None
    assert Application.__metadata__["discriminator_map"]["app"] == Application

    app = Application(id=42, name="Arthur Dent")
    data = serialize(app)

    assert data["id"] == 42
    assert data["kind"] == "app"
    assert data["name"] == "Arthur Dent"
    assert data["optional"] == "optional"

    instance = deserialize(Application, data)
    assert isinstance(instance, Application)
    assert instance.id == app.id
    assert instance.name == app.name
    assert instance.kind == app.kind
    assert instance.optional == app.optional

    @serializable
    class FancyApplication(Application):
        number: int
        kind: str = "fancy-app"

        def __init__(self, id, name, number, kind=None, optional=None):
            super().__init__(id, name, kind, optional)
            self.number = number

    assert FancyApplication.Schema is not None
    assert "schema" in FancyApplication.__metadata__
    assert (
        FancyApplication.__metadata__["discriminator_map"]["fancy-app"]
        == FancyApplication
    )

    app = FancyApplication(id=72, name="Fancy name", number=42)
    data = serialize(app)

    assert data["id"] == 72
    assert data["kind"] == "fancy-app"
    assert data["name"] == "Fancy name"
    assert data["optional"] == "optional"
    assert data["number"] == 42

    instance = deserialize(FancyApplication, data)
    assert isinstance(instance, FancyApplication)

    # Test polymorphic deserialization
    instance = deserialize(Application, data)
    assert isinstance(instance, FancyApplication)

    assert instance.id == app.id
    assert instance.name == app.name
    assert instance.number == app.number
    assert instance.kind == app.kind


def test_functional_api_with_dataclasses():
    @serializable
    @dataclass
    class Application(object):
        id: int
        name: str
        optional: str = "optional"

    assert Application.Schema is not None
    assert "schema" in Application.__metadata__

    app = Application(id=42, name="Arthur Dent")
    data = serialize(app)

    assert data["id"] == 42
    assert data["name"] == "Arthur Dent"
    assert data["optional"] == "optional"


def test_inheritance():
    class Application(Serializable):
        id: int
        name: str
        optional: str = "optional"
        kind: str = "app"

        __metadata__ = {"discriminator": "kind"}

    assert Application.Schema is not None
    assert "schema" in Application.__metadata__
    assert Application.__metadata__["discriminator_map"]["app"] == Application

    app = Application(id=42, name="Arthur Dent")
    assert app.id == 42
    assert app.name == "Arthur Dent"
    assert app.kind == "app"
    assert app.optional == "optional"

    data = serialize(app)

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

    instance = deserialize(Application, data)
    assert isinstance(instance, Application)
    assert instance.id == app.id
    assert instance.name == app.name
    assert instance.kind == app.kind
    assert instance.optional == app.optional

    class FancyApplication(Application):
        number: int
        kind: str = "fancy-app"

    assert FancyApplication.Schema is not None
    assert "schema" in FancyApplication.__metadata__
    assert (
        FancyApplication.__metadata__["discriminator_map"]["fancy-app"]
        == FancyApplication
    )

    app = FancyApplication(id=72, name="Arthur Dent", number=42)
    assert app.id == 72
    assert app.name == "Arthur Dent"
    assert app.kind == "fancy-app"
    assert app.optional == "optional"
    assert app.number == 42

    data = serialize(app)

    assert data["id"] == 72
    assert data["name"] == "Arthur Dent"
    assert data["kind"] == "fancy-app"
    assert data["optional"] == "optional"
    assert data["number"] == 42

    instance = deserialize(FancyApplication, data)
    assert isinstance(instance, FancyApplication)

    # Test polymorphic deserialization
    instance = deserialize(Application, data)
    assert isinstance(instance, FancyApplication)

    assert instance.id == app.id
    assert instance.name == app.name
    assert instance.kind == app.kind
    assert instance.optional == app.optional
    assert instance.number == app.number


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
    data = serialize(book)

    assert data["id"] == 42
    assert data["name"] == "The Hitchhiker's Guide to the Galaxy"

    assert isinstance(data["author"], dict)
    assert data["author"]["given_name"] == "Douglas"
    assert data["author"]["surname"] == "Adams"


def test_list():
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
    data = serialize(book)

    assert data["id"] == 42
    assert data["name"] == "The Hitchhiker's Guide to the Galaxy"
    assert isinstance(data["characters"], list)
    assert len(data["characters"]) == 2

    assert data["characters"][0]["given_name"] == "Arthur"
    assert data["characters"][0]["surname"] == "Dent"

    assert data["characters"][1]["given_name"] == "Ford"
    assert data["characters"][1]["surname"] == "Perfect"
