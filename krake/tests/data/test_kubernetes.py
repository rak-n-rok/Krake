import pytest
import yaml

from copy import deepcopy
from marshmallow import ValidationError

from krake.data.kubernetes import Application, ObserverSchemaError
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


kubernetes_manifest = list(
    yaml.safe_load_all(
        """---
apiVersion: v1
kind: Service
metadata:
  name: nginx-demo
  namespace: default
spec:
  type: NodePort
  selector:
    app: nginx
  ports:
  - port: 80
    protocol: TCP
    targetPort: 80
"""
    )
)


def test_observer_schema_init_valid_custom():
    """Validate that custom observer_schema are correctly initialized when they are valid
    """

    # In this custom observer schema:
    # - `spec.type` is present in the manifest but not observed
    # - `spec.clusterIP` is not present in the manifest but is observed.
    # - the `spec.ports` lists has a first element partially observed, and accept up to
    # 2 additional elements.
    # The observer schema is correctly formed.
    valid_custom_observer_schema1 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 3
      clusterIP: null
    """
        )
    )

    # Set the observer_schema_list_max_length to 0, meaning that the list doesn't have a
    # maximum length
    valid_custom_observer_schema2 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 0
    """
        )
    )

    # Minimum valid observer_schema for a resource
    valid_custom_observer_schema3 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    """
        )
    )

    app = ApplicationFactory(
        spec__manifest=kubernetes_manifest,
        spec__observer_schema=valid_custom_observer_schema1,
    )

    assert app.spec.observer_schema == valid_custom_observer_schema1

    app = ApplicationFactory(
        spec__manifest=kubernetes_manifest,
        spec__observer_schema=valid_custom_observer_schema2,
    )

    assert app.spec.observer_schema == valid_custom_observer_schema2

    app = ApplicationFactory(
        spec__manifest=kubernetes_manifest,
        spec__observer_schema=valid_custom_observer_schema3,
    )

    assert app.spec.observer_schema == valid_custom_observer_schema3


def test_observer_schema_init_invalid_custom():
    """Validate that invalid custom observer_schema are raising an Exception
    """

    # Invalid as it doesn't contain the special list control dictionary
    invalid_custom_observer_schema1 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - null
    """
        )
    )

    # Missing observer_schema_list_max_length
    invalid_custom_observer_schema2 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: 1
    """
        )
    )

    # Missing observer_schema_list_min_length
    invalid_custom_observer_schema3 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_max_length: 1
    """
        )
    )

    # Invalid value for observer_schema_list_min_length
    invalid_custom_observer_schema4 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: invalidstring
        observer_schema_list_max_length: 1
    """
        )
    )

    # Invalid value for observer_schema_list_max_length
    invalid_custom_observer_schema5 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: 0
        observer_schema_list_max_length: invalidstring
    """
        )
    )

    # Invalid value for observer_schema_list_min_length
    invalid_custom_observer_schema6 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: -1
        observer_schema_list_max_length: 1
    """
        )
    )

    # Invalid value for observer_schema_list_max_length
    invalid_custom_observer_schema7 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: 0
        observer_schema_list_max_length: -3
    """
        )
    )

    # Invalid as the list_max_length is inferior to the number of observed elements
    invalid_custom_observer_schema8 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - port: null
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 1
    """
        )
    )

    # Invalid as the list_max_length is inferior to list_min_length
    invalid_custom_observer_schema9 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: 5
        observer_schema_list_max_length: 2
    """
        )
    )

    # Invalid as it doesn't contain an apiVersion
    invalid_custom_observer_schema10 = list(
        yaml.safe_load_all(
            """---
    not_the_apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    """
        )
    )

    # Invalid as it doesn't contain a kind
    invalid_custom_observer_schema11 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    not_the_kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    """
        )
    )

    # Invalid as it doesn't contain a metadata dictionary with the name and namespace
    invalid_custom_observer_schema12 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    not_the_metadata:
      name: nginx-demo
      namespace: null
    """
        )
    )

    # Invalid as it doesn't contain a metadata dictionary with the name
    invalid_custom_observer_schema13 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      not_the_name: nginx-demo
    """
        )
    )

    # Invalid as the port value is not "None" (dict key)
    invalid_custom_observer_schema14 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    ports:
      - port: 8080
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 1
    """
        )
    )

    # Invalid as the port value is not "None" (list element)
    invalid_custom_observer_schema15 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    ports:
      - 8080
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 1

    """
        )
    )

    # Test a valid observer schema, but the resource is not present in the manifest.
    valid_custom_observer_schema = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
      namespace: null
    """
        )
    )

    with pytest.raises(
        ObserverSchemaError, match=r"Special list control dictionary not found"
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema1,
        )

    with pytest.raises(
        ObserverSchemaError, match=r"Special list control dictionary malformed"
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema2,
        )

    with pytest.raises(
        ObserverSchemaError, match=r"Special list control dictionary malformed"
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema3,
        )

    with pytest.raises(
        ObserverSchemaError,
        match=r"observer_schema_list_min_length should be an integer",
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema4,
        )

    with pytest.raises(
        ObserverSchemaError,
        match=r"observer_schema_list_max_length should be an integer",
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema5,
        )

    with pytest.raises(
        ObserverSchemaError, match=r"Invalid value for observer_schema_list_min_length"
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema6,
        )

    with pytest.raises(
        ObserverSchemaError, match=r"Invalid value for observer_schema_list_max_length"
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema7,
        )

    msg = (
        "observer_schema_list_max_length is inferior to the number of observed elements"
    )
    with pytest.raises(ObserverSchemaError, match=msg):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema8,
        )

    msg = (
        "observer_schema_list_max_length is inferior to observer_schema_list_min_length"
    )
    with pytest.raises(ObserverSchemaError, match=msg):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema9,
        )

    with pytest.raises(ObserverSchemaError, match="apiVersion is not defined"):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema10,
        )

    with pytest.raises(ObserverSchemaError, match="kind is not defined"):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema11,
        )

    with pytest.raises(ObserverSchemaError, match="metadata dictionary is not defined"):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema12,
        )

    with pytest.raises(
        ObserverSchemaError, match="name is not defined in the metadata dictionary"
    ):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema13,
        )

    with pytest.raises(ObserverSchemaError, match="Value of 'port' is not 'None'"):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema14,
        )

    with pytest.raises(ObserverSchemaError, match="Element of a list is not 'None'"):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_observer_schema15,
        )

    with pytest.raises(
        ObserverSchemaError, match="Observed resource must be in manifest"
    ):
        ApplicationFactory(
            spec__manifest=[], spec__observer_schema=valid_custom_observer_schema
        )
