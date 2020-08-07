import pytest

from krake.data.constraints import (
    LabelConstraint,
    EqualConstraint,
    NotEqualConstraint,
    InConstraint,
    NotInConstraint,
)
from krake.data.kubernetes import ClusterConstraints
import lark
from marshmallow import ValidationError


def valid_serialization(constraint):
    """Attempt the serialization and deserialization processes of the given constraint
    to trigger a validation of its content.


    Args:
        constraint (LabelConstraint): the constraint to serialize and deserialize.

    Returns:
        bool: True if the constraint is valid, False otherwise.

    """
    try:
        constraints = ClusterConstraints(labels=[constraint])
        ClusterConstraints.deserialize(constraints.serialize())
        return True
    except ValidationError:
        return False


@pytest.mark.parametrize(
    "expression",
    [
        "location == DE",
        "location = DE",
        "location is DE",
        "location==DE",
        "location=DE",
    ],
)
def test_parse_equal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, EqualConstraint)
    assert constraint.value == "DE"


@pytest.mark.parametrize(
    "expression", ["location != DE", "location!=DE", "location is not DE"]
)
def test_parse_notequal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, NotEqualConstraint)
    assert constraint.value == "DE"


@pytest.mark.parametrize(
    "expression", ["location in (DE, SK)", "location in (DE, SK,)"]
)
def test_parse_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE", "SK")


@pytest.mark.parametrize("expression", ["location in (DE)", "location in (DE,)"])
def test_parse_single_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE",)


@pytest.mark.parametrize(
    "expression", ["location not in (DE, SK)", "location not in (DE, SK,)"]
)
def test_parse_notin_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "location"

    assert valid_serialization(constraint)
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


@pytest.mark.parametrize(
    "expression",
    [
        "url.com/location == DE.GER",
        "url.com/location = DE.GER",
        "url.com/location==DE.GER",
        "url.com/location=DE.GER",
        "url.com/location is DE.GER",
    ],
)
def test_labels_parse_equal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "url.com/location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, EqualConstraint)
    assert constraint.value == "DE.GER"


@pytest.mark.parametrize(
    "expression",
    [
        "url.com/location != DE.GER",
        "url.com/location!=DE.GER",
        "url.com/location is not DE.GER",
    ],
)
def test_labels_parse_notequal_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "url.com/location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, NotEqualConstraint)
    assert constraint.value == "DE.GER"


@pytest.mark.parametrize(
    "expression",
    ["url.com/location in (DE.GER, SK.SLOV)", "url.com/location in (DE.GER, SK.SLOV,)"],
)
def test_labels_parse_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "url.com/location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE.GER", "SK.SLOV")


@pytest.mark.parametrize(
    "expression", ["url.com/location in (DE.GER)", "url.com/location in (DE.GER,)"]
)
def test_labels_parse_single_in_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "url.com/location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, InConstraint)
    assert constraint.values == ("DE.GER",)


@pytest.mark.parametrize(
    "expression",
    [
        "location! == DE",
        "location == DE!",
        "location == (DE, SK)",
        "a location == (DE, SK)",
        "location = (DE, SK)",
        "a location = (DE, SK)",
        "a location = DE",
        "location is (DE, SK)",
        "location inf (DE, SK)",
        "location is",
        " in (DE, SK)",
        "location in ()",
        "location not in ()",
        "location in [DE, SK)",
        "location in DE, SK",
        "location not in (DE, SK]",
        "location not in (DE, SK",
        "location not in (DE a, SK)",
        "location not in (DE, SK a)",
        "location not inf (DE, SK)",
        "location not in DE, SK",
        "location = (DE, SK)",
    ],
)
def test_invalid_grammar_parse_equal_constraint(expression):
    # Test that wrongly built constraints raise a grammar parsing exception.
    with pytest.raises(lark.exceptions.LarkError):
        LabelConstraint.parse(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "url.com/location not in (DE.GER, SK.SLOV)",
        "url.com/location not in (DE.GER, SK.SLOV,)",
    ],
)
def test_labels_parse_notin_constraint(expression):
    constraint = LabelConstraint.parse(expression)

    assert constraint.label == "url.com/location"

    assert valid_serialization(constraint)
    assert isinstance(constraint, NotInConstraint)
    assert constraint.values == ("DE.GER", "SK.SLOV")


@pytest.mark.parametrize(
    "expression",
    [
        ". == DE",
        "-k = DE",
        "url/com/location != DE",
        "url.com/ is not DE",
        "/location in (DE, SK)",
        "k" * 300 + "/location in (DE, SK,)",
        "url.com/" + "k" * 70 + " in (DE, SK,)",
        "url.com/location. in (DE.GER,)",
        "url.com/" + "k" * 70 + " in (DE, SK,)",
        "url.com/location. in (DE.GER,)",
    ],
)
def test_invalid_key_parse_equal_constraint(expression):
    # Test that constraints with an invalid key raise a serialization exception.
    with pytest.raises(ValidationError):
        LabelConstraint.parse(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "url.com/location = $DE",
        "url.com/location is .",
        "url/com/location != DE",
        "url.com/ is not DE",
        "/location in (DE, SK)",
        "url.com/location in (DE-, SK)",
        "url.com/location in (DE, /SK,)",
    ],
)
def test_invalid_value_parse_equal_constraint(expression):
    # Test that constraints with an invalid label raise a serialization exception.
    with pytest.raises(ValidationError):
        LabelConstraint.parse(expression)
