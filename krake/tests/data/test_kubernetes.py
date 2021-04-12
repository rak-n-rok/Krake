import pytest
from krake.data.kubernetes import Application
from marshmallow import ValidationError
from tests.factories.kubernetes import ApplicationFactory


def test_application_constraints_null_error_handling():
    """Ensure that empty cluster constraints for Applications are seen as invalid."""
    app = ApplicationFactory(spec__constraints=None)

    serialized = app.serialize()

    with pytest.raises(
        ValidationError, match="'constraints': \\['Field may not be null.'\\]"
    ):
        Application.deserialize(serialized)


def test_application_cluster_constraints_null_error_handling():
    """Ensure that empty constraints for Applications are seen as invalid."""
    app = ApplicationFactory(spec__constraints__cluster=None)

    serialized = app.serialize()

    with pytest.raises(
        ValidationError,
        match="'constraints': {'cluster': \\['Field may not be null.'\\]}",
    ):
        Application.deserialize(serialized)
