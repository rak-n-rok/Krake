import pytest

from krake.data.constraints import (
    LabelConstraint,
    EqualConstraint,
    NotEqualConstraint,
    InConstraint,
    NotInConstraint,
    MetricConstraint,
    EqualMetricConstraint,
    NotEqualMetricConstraint,
    LesserThanMetricConstraint,
    LesserThanOrEqualMetricConstraint,
    GreaterThanMetricConstraint,
    GreaterThanOrEqualMetricConstraint
)
from krake.data.kubernetes import ClusterConstraints
from krake.data.core import MetricRef
import lark
from marshmallow import ValidationError


def test_label_constraint_class_methods():
    """Verify the base methods of the LabelConstraint class (__eq__, __hash__...)"""
    lc_de = LabelConstraint.parse("location is DE")
    lc_not_de = LabelConstraint.parse("location is not DE")
    assert lc_de != lc_not_de

    lc_fr = LabelConstraint.parse("location is FR")
    assert lc_de != lc_fr

    lc_de_2 = LabelConstraint.parse("location is DE")
    assert lc_de == lc_de_2

    # Check label constraints hashing
    label_constraints = set()
    label_constraints.add(lc_de)
    label_constraints.add(lc_fr)
    label_constraints.add(lc_not_de)
    label_constraints.add(lc_de_2)

    # As lc_de_2 is equal to lc_de, only 3 elements have actually been added.
    assert len(label_constraints) == 3

    # Check representation
    assert repr(lc_de) == "<EqualConstraint 'location is DE'>"
    assert repr(lc_not_de) == "<NotEqualConstraint 'location is not DE'>"

    lc_eq_de = LabelConstraint.parse("location == DE")
    assert repr(lc_eq_de) == "<EqualConstraint 'location is DE'>"
    lc_not_eq_de = LabelConstraint.parse("location != DE")
    assert repr(lc_not_eq_de) == "<NotEqualConstraint 'location is not DE'>"

    lc_in_de_sk = LabelConstraint.parse("location in (DE, SK)")
    assert repr(lc_in_de_sk) == "<InConstraint 'location in (DE, SK)'>"
    lc_in_de_sk = LabelConstraint.parse("location not in (DE, SK)")
    assert repr(lc_in_de_sk) == "<NotInConstraint 'location not in (DE, SK)'>"

    lc_in_de_sk_comma = LabelConstraint.parse("location in (DE, SK,)")
    assert repr(lc_in_de_sk_comma) == "<InConstraint 'location in (DE, SK)'>"
    lc_not_in_de_sk_comma = LabelConstraint.parse("location not in (DE, SK,)")
    assert repr(lc_not_in_de_sk_comma) == "<NotInConstraint 'location not in (DE, SK)'>"


def test_label_constraint_deserialization():
    """Ensure that a label constraint as string cannot be deserialized
    if it is invalid.
    """
    serialized_constraints = {
        "labels": ["location is not valid DE"],
        "custom_resources": [],
    }
    with pytest.raises(ValidationError, match="Invalid label constraint"):
        ClusterConstraints.deserialize(serialized_constraints)


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
    assert not LabelConstraint.parse("location is DE").match({"country": "SK"})
    assert not LabelConstraint.parse("location is DE").match({"country": "DE"})


def test_notequal_constraint_match():
    assert LabelConstraint.parse("location is not DE").match({"location": "SK"})

    assert not LabelConstraint.parse("location is not DE").match({"location": "DE"})
    assert not LabelConstraint.parse("location is not DE").match({"country": "DE"})
    assert not LabelConstraint.parse("location is not DE").match({"country": "SK"})


def test_in_constraint_match():
    assert LabelConstraint.parse("location in (DE, SK)").match({"location": "SK"})

    assert not LabelConstraint.parse("location in (DE, SK)").match({"location": "EU"})
    assert not LabelConstraint.parse("location in (DE, SK)").match({"country": "EU"})
    assert not LabelConstraint.parse("location in (DE, SK)").match({"country": "SK"})


def test_notin_constraint_match():
    assert LabelConstraint.parse("location not in (DE, SK)").match({"location": "EU"})

    assert not LabelConstraint.parse("location not in (DE, SK)").match(
        {"location": "DE"}
    )
    assert not LabelConstraint.parse("location not in (DE, SK)").match(
        {"country": "DE"}
    )
    assert not LabelConstraint.parse("location not in (DE, SK)").match(
        {"country": "SK"}
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


def test_metric_constraint_class_methods():
    """Verify the base methods of the LabelConstraint class (__eq__, __hash__...)"""
    mc_five = MetricConstraint.parse("load is 5")
    mc_not_five = MetricConstraint.parse("load is not 5")
    assert mc_five != mc_not_five

    mc_six = MetricConstraint.parse("load is 6")
    assert mc_five != mc_six

    mc_five_2 = MetricConstraint.parse("load is 5")
    assert mc_five == mc_five_2

    # Check label constraints hashing
    metric_constraints = set()
    metric_constraints.add(mc_five)
    metric_constraints.add(mc_six)
    metric_constraints.add(mc_not_five)
    metric_constraints.add(mc_five_2)

    # As lc_de_2 is equal to lc_de, only 3 elements have actually been added.
    assert len(metric_constraints) == 3

    # Check representation
    assert repr(mc_five) == "<EqualMetricConstraint 'load is 5'>"
    assert repr(mc_not_five) == "<NotEqualMetricConstraint 'load is not 5'>"

    mc_eq_five = MetricConstraint.parse("load == 5")
    assert repr(mc_eq_five) == "<EqualMetricConstraint 'load is 5'>"
    mc_not_eq_five = MetricConstraint.parse("load != 5")
    assert repr(mc_not_eq_five) == "<NotEqualMetricConstraint 'load is not 5'>"

    mc_lt_five = MetricConstraint.parse("load < 5")
    assert repr(mc_lt_five) == "<LesserThanMetricConstraint 'load lesser than 5'>"
    mc_lte_five = MetricConstraint.parse("load <= 5")
    assert repr(mc_lte_five) == \
           "<LesserThanOrEqualMetricConstraint 'load lesser than or equal 5'>"

    mc_gt_five = MetricConstraint.parse("load > 5")
    assert repr(mc_gt_five) == "<GreaterThanMetricConstraint 'load greater than 5'>"
    mc_gte_five = MetricConstraint.parse("load >= 5")
    assert repr(mc_gte_five) == \
           "<GreaterThanOrEqualMetricConstraint 'load greater than or equal 5'>"


def test_metric_constraint_deserialization():
    """Ensure that a metric constraint as a string cannot be deserialized
    if it is invalid.
    """
    serialized_constraints = {
        "labels": [],
        "custom_resources": [],
        "metrics": [
            "load is over 9000"
        ]
    }
    with pytest.raises(ValidationError, match="Invalid metric constraint"):
        ClusterConstraints.deserialize(serialized_constraints)


def valid_metric_serialization(constraint):
    """Attempt the serialization and deserialization processes of the given constraint
    to trigger a validation of its content.


    Args:
        constraint (MetricConstraint): the constraint to serialize and deserialize.

    Returns:
        bool: True if the constraint is valid, False otherwise.

    """
    try:
        constraints = ClusterConstraints(metrics=[constraint])
        ClusterConstraints.deserialize(constraints.serialize())
        return True
    except ValidationError:
        return False


@pytest.mark.parametrize(
    "expression",
    [
        "load == 5",
        "load = 5",
        "load is 5",
        "load==5",
        "load=5",
    ],
)
def test_parse_equal_metric_constraint(expression):
    constraint = MetricConstraint.parse(expression)

    assert constraint.metric == "load"

    assert valid_metric_serialization(constraint)
    assert isinstance(constraint, EqualMetricConstraint)
    assert constraint.value == "5"


@pytest.mark.parametrize(
    "expression",
    [
        "load != 5",
        "load!=5",
        "load is not 5"
    ]
)
def test_parse_notequal_constraint(expression):
    constraint = MetricConstraint.parse(expression)

    assert constraint.metric == "load"

    assert valid_metric_serialization(constraint)
    assert isinstance(constraint, NotEqualMetricConstraint)
    assert constraint.value == "5"


@pytest.mark.parametrize(
    "expression",
    [
        "load < 5",
        "load lesser than 5",
        "load lt 5",
    ],
)
def test_parse_lesser_than_metric_constraint(expression):
    constraint = MetricConstraint.parse(expression)

    assert constraint.metric == "load"

    assert valid_metric_serialization(constraint)
    assert isinstance(constraint, LesserThanMetricConstraint)
    assert constraint.value == "5"


@pytest.mark.parametrize(
    "expression",
    [
        "load <= 5",
        "load lesser than or equal 5",
        "load lte 5",
    ],
)
def test_parse_lesser_than_or_equal_metric_constraint(expression):
    constraint = MetricConstraint.parse(expression)

    assert constraint.metric == "load"

    assert valid_metric_serialization(constraint)
    assert isinstance(constraint, LesserThanOrEqualMetricConstraint)
    assert constraint.value == "5"


@pytest.mark.parametrize(
    "expression",
    [
        "load > 5",
        "load greater than 5",
        "load gt 5",
    ],
)
def test_parse_greater_than_metric_constraint(expression):
    constraint = MetricConstraint.parse(expression)

    assert constraint.metric == "load"

    assert valid_metric_serialization(constraint)
    assert isinstance(constraint, GreaterThanMetricConstraint)
    assert constraint.value == "5"


@pytest.mark.parametrize(
    "expression",
    [
        "load >= 5",
        "load greater than or equal 5",
        "load gte 5",
    ],
)
def test_parse_greater_than_or_equal_metric_constraint(expression):
    constraint = MetricConstraint.parse(expression)

    assert constraint.metric == "load"

    assert valid_metric_serialization(constraint)
    assert isinstance(constraint, GreaterThanOrEqualMetricConstraint)
    assert constraint.value == "5"


def test_equal_metric_constraint_match():
    assert MetricConstraint.parse("load is 5").match(
        {"load": MetricRef(name="load", weight=5.0, namespaced=False)}
    )

    assert not MetricConstraint.parse("load is 5").match(
        {"load": MetricRef(name="load", weight=6.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load is 5").match(
        {"throughput": MetricRef(name="throughput", weight=6.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load is 5").match(
        {"throughput": MetricRef(name="throughput", weight=5.0, namespaced=False)}
    )


def test_notequal_metric_constraint_match():
    assert MetricConstraint.parse("load is not 5").match(
        {"load": MetricRef(name="load", weight=6.0, namespaced=False)}
    )

    assert not MetricConstraint.parse("load is not 5").match(
        {"load": MetricRef(name="load", weight=5.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load is not 5").match(
        {"throughput": MetricRef(name="throughput", weight=5.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load is not 5").match(
        {"throughput": MetricRef(name="throughput", weight=6.0, namespaced=False)}
    )


def test_lesser_than_metric_constraint_match():
    assert MetricConstraint.parse("load lt 5").match(
        {"load": MetricRef(name="load", weight=4.0, namespaced=False)}
    )

    assert not MetricConstraint.parse("load lt 5").match(
        {"load": MetricRef(name="load", weight=6.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load lt 5").match(
        {"throughput": MetricRef(name="throughput", weight=6.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load lt 5").match(
        {"throughput": MetricRef(name="throughput", weight=5.0, namespaced=False)}
    )


def test_lesser_than_or_equal_metric_constraint_match():
    assert MetricConstraint.parse("load lte 5").match(
        {"load": MetricRef(name="load", weight=5.0, namespaced=False)}
    )

    assert not MetricConstraint.parse("load lte 5").match(
        {"load": MetricRef(name="load", weight=6.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load lte 5").match(
        {"throughput": MetricRef(name="troughput", weight=6.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load lte 5").match(
        {"throughput": MetricRef(name="throughput", weight=5.0, namespaced=False)}
    )


def test_greater_than_metric_constraint_match():
    assert MetricConstraint.parse("load gt 5").match(
        {"load": MetricRef(name="load", weight=6.0, namespaced=False)}
    )

    assert not MetricConstraint.parse("load gt 5").match(
        {"load": MetricRef(name="load", weight=5.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load gt 5").match(
        {"throughput": MetricRef(name="throughput", weight=6.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load gt 5").match(
        {"throughput": MetricRef(name="throughput", weight=5.0, namespaced=False)}
    )


def test_greater_than_or_equal_metric_constraint_match():
    assert MetricConstraint.parse("load gte 5").match(
        {"load": MetricRef(name="load", weight=5.0, namespaced=False)}
    )

    assert not MetricConstraint.parse("load gte 5").match(
        {"load": MetricRef(name="load", weight=4.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load gte 5").match(
        {"throughput": MetricRef(name="throughput", weight=4.0, namespaced=False)}
    )
    assert not MetricConstraint.parse("load gte 5").match(
        {"throughput": MetricRef(name="throughput", weight=5.0, namespaced=False)}
    )


def test_str_equal_metric_constraint():
    constraint = EqualMetricConstraint(metric="load", value="5")
    assert str(constraint) == "load is 5"


def test_str_notequal_metric_constraint():
    constraint = NotEqualMetricConstraint(metric="load", value="5")
    assert str(constraint) == "load is not 5"


def test_str_lesser_than_metric_constraint():
    constraint = LesserThanMetricConstraint(metric="load", value="5")
    assert str(constraint) == "load lesser than 5"


def test_str_lesser_than_or_equal_metric_constraint():
    constraint = LesserThanOrEqualMetricConstraint(metric="load", value="5")
    assert str(constraint) == "load lesser than or equal 5"


def test_str_greater_than_metric_constraint():
    constraint = GreaterThanMetricConstraint(metric="load", value="5")
    assert str(constraint) == "load greater than 5"


def test_str_greater_than_or_equal_metric_constraint():
    constraint = GreaterThanOrEqualMetricConstraint(metric="load", value="5")
    assert str(constraint) == "load greater than or equal 5"


@pytest.mark.parametrize(
    "expression",
    [
        "load! == 5",
        "load == 5!",
        "load == (5, 7)",
        "a load == (5, 7)",
        "load = (5, 7)",
        "a load = (5, 7)",
        "a load = 5",
        "load is (5, 7)",
        "load inf (5, 7)",
        "load is",
        " in (5, 7)",
        "load in ()",
        "load not in ()",
        "load in [5, 7)",
        "load in 5, 7",
        "load not in (5, 7]",
        "load not in (5, 7",
        "load not in (5 a, 7)",
        "load not in (5, 7 a)",
        "load not inf (5, 7)",
        "load not in 5, 7",
        "load = (5, 7)",
    ],
)
def test_invalid_grammar_parse_equal_metric_constraint(expression):
    # Test that wrongly built constraints raise a grammar parsing exception.
    with pytest.raises(lark.exceptions.LarkError):
        MetricConstraint.parse(expression)


@pytest.mark.parametrize(
    "expression",
    [
        ". == 5",
        "-k = 5",
        "url/com/load != 5",
        "url.com/ is not 5",
    ],
)
def test_invalid_key_parse_equal_metric_constraint(expression):
    # Test that constraints with an invalid key raise a serialization exception.
    with pytest.raises(ValidationError):
        MetricConstraint.parse(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "url.com/load = $LOAD",
        "url.com/load is .",
        "url/com/load != 5",
        "url.com/ is not 5",
    ],
)
def test_invalid_value_parse_equal_metric_constraint(expression):
    # Test that constraints with an invalid label raise a serialization exception.
    with pytest.raises(ValidationError):
        MetricConstraint.parse(expression)
