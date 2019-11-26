import pytest

from krake.data.constraints import (
    LabelConstraint,
    EqualConstraint,
    NotEqualConstraint,
    InConstraint,
    NotInConstraint,
)


@pytest.mark.parametrize(
    "expression", ["location == DE", "location = DE", "location is DE"]
)
def test_parse_equal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, EqualConstraint)
    assert constraint.value == "DE"


@pytest.mark.parametrize("expression", ["location != DE", "location is not DE"])
def test_parse_notequal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, NotEqualConstraint)
    assert constraint.value == "DE"


@pytest.mark.parametrize(
    "expression", ["location in (DE, SK)", "location in (DE, SK,)"]
)
def test_parse_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE", "SK")


@pytest.mark.parametrize("expression", ["location in (DE)", "location in (DE,)"])
def test_parse_single_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE",)


@pytest.mark.parametrize(
    "expression", ["location not in (DE, SK)", "location not in (DE, SK,)"]
)
def test_parse_notin_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert isinstance(constraint, NotInConstraint)
    assert constraint.values == ("DE", "SK")


def test_equal_constraint_match():
    assert LabelConstraint.parse("location is DE").match({"location": "DE"})
    assert not LabelConstraint.parse("location is DE").match({"location": "SK"})


def test_notequal_constraint_match():
    assert LabelConstraint.parse("location is not DE").match({"location": "SK"})
    assert not LabelConstraint.parse("location is not DE").match({"location": "DE"})


def test_in_constraint_match():
    assert LabelConstraint.parse("location in (DE, SK)").match({"location": "SK"})
    assert not LabelConstraint.parse("location in (DE, SK)").match({"location": "EU"})


def test_notin_constraint_match():
    assert LabelConstraint.parse("location not in (DE, SK)").match({"location": "EU"})
    assert not LabelConstraint.parse("location not in (DE, SK)").match(
        {"location": "DE"}
    )


def test_str_equal_constraint():
    constraint = EqualConstraint(label="location", value="DE")
    assert str(constraint) == "location is DE"


def test_str_notequal_constraint():
    constraint = NotEqualConstraint(label="location", value="DE")
    assert str(constraint) == "location is not DE"


def test_str_in_constraint():
    constraint = InConstraint(label="location", values=("DE", "SK"))
    assert str(constraint) == "location in (DE, SK)"


def test_str_notin_constraint():
    constraint = NotInConstraint(label="location", values=("DE", "SK"))
    assert str(constraint) == "location not in (DE, SK)"
