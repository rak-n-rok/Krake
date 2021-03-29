import pytest
from copy import deepcopy

from krake.data.kubernetes import Application
from marshmallow import ValidationError
from tests.controller.kubernetes import nginx_manifest
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


def test_application_manifest_empty_error_handling():
    """Ensure that empty manifests are seen as invalid."""
    app = ApplicationFactory(spec__manifest=[])

    serialized = app.serialize()

    with pytest.raises(ValidationError, match="The manifest file must not be empty."):
        Application.deserialize(serialized)


def test_application_manifest_invalid_structure_error_handling():
    """Ensure that manifests with important missing fields are seen as invalid."""
    app = ApplicationFactory()

    serialized = app.serialize()
    del serialized["spec"]["manifest"][0]["metadata"]

    with pytest.raises(
        ValidationError, match="Field 'metadata' not found in resource."
    ):
        Application.deserialize(serialized)

    for field in ["apiVersion", "kind", "metadata"]:
        app = ApplicationFactory()
        serialized = app.serialize()
        del serialized["spec"]["manifest"][0][field]

        with pytest.raises(
            ValidationError, match=f"Field '{field}' not found in resource."
        ):
            Application.deserialize(serialized)


def test_application_manifest_multiple_errors_handling():
    """Ensure that if several errors are present in a manifest, they are handled the
    right way.

    The test creates a manifest file with the following content (with the same order):
    1. an invalid Deployment without kind or apiVersion
    2. a valid Deployment
    3. an invalid Service, without name in the metadata field.

    """
    # Prepare the manifest

    # Insert a second version of the Deployment, free of errors.
    custom_manifest = deepcopy(nginx_manifest)
    custom_manifest.insert(1, deepcopy(custom_manifest[0]))
    app = ApplicationFactory(spec__manifest=custom_manifest)

    # Add errors in the first deployment
    serialized = app.serialize()
    deployment = serialized["spec"]["manifest"][0]
    del deployment["apiVersion"]
    del deployment["kind"]

    # Add one error in the service (last resource)
    service = serialized["spec"]["manifest"][2]
    del service["metadata"]["name"]

    # Verify the errors

    with pytest.raises(ValidationError) as info:
        Application.deserialize(serialized)

    validation_errors = info.value.messages
    manifest_errs = validation_errors["spec"]["manifest"]
    assert type(manifest_errs) is list
    assert len(manifest_errs) == 3

    # 2 errors on the first resource
    assert (
        manifest_errs[0] == "Field 'apiVersion' not found in resource at index 0"
        " (metadata.name: 'nginx-demo')"
    )
    assert (
        manifest_errs[1]
        == "Field 'kind' not found in resource at index 0 (metadata.name: 'nginx-demo')"
    )
    # 1 error on the last resource
    assert manifest_errs[2] == "Field 'metadata.name' not found in resource at index 2"
