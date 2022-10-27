import pytest
import yaml

from copy import deepcopy
from marshmallow import ValidationError

from krake.data.kubernetes import Application, Cluster, ObserverSchemaError
from tests.controller.kubernetes import nginx_manifest
from tests.factories.kubernetes import ApplicationFactory, ClusterFactory


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
    """Ensure that empty manifests and tosca and csar are seen as invalid."""
    with pytest.raises(
        ValidationError,
        match="The application should be defined by"
        " a manifest file, a TOSCA template or a CSAR file.",
    ):
        ApplicationFactory(
            spec__manifest=[],
            spec__tosca={},
            spec__csar=None,
        )


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


async def test_kubeconfig_validation_context_error_handling():
    """Ensure that if the kubeconfig file in a Cluster's spec has more that one context,
    an validation error is raised.
    """
    cluster = ClusterFactory()

    cluster.spec.kubeconfig["contexts"].append(
        {"context": {"cluster": "foo", "user": "bar"}, "name": "other-context"}
    )
    assert len(cluster.spec.kubeconfig["contexts"]) == 2
    serialized = cluster.serialize()

    with pytest.raises(ValidationError, match="Only one context is allowed"):
        Cluster.deserialize(serialized)


async def test_kubeconfig_validation_user_error_handling():
    """Ensure that if the kubeconfig file in a Cluster's spec has more that one user,
    an validation error is raised.
    """
    cluster = ClusterFactory()

    cluster.spec.kubeconfig["users"].append(
        {
            "name": "other-user",
            "user": {"client-certificate-data": "<cert>", "client-key-data": "<key>"},
        }
    )
    assert len(cluster.spec.kubeconfig["users"]) == 2
    serialized = cluster.serialize()

    with pytest.raises(ValidationError, match="Only one user is allowed"):
        Cluster.deserialize(serialized)


async def test_kubeconfig_validation_cluster_error_handling():
    """Ensure that if the kubeconfig file in a Cluster's spec has more that one cluster,
    an validation error is raised.
    """
    cluster = ClusterFactory()

    cluster.spec.kubeconfig["clusters"].append(
        {
            "cluster": {
                "certificate-authority-data": "<CA>",
                "server": "https://127.0.0.1:8080",
            },
            "name": "other-cluster",
        }
    )
    assert len(cluster.spec.kubeconfig["clusters"]) == 2
    serialized = cluster.serialize()

    with pytest.raises(ValidationError, match="Only one cluster is allowed"):
        Cluster.deserialize(serialized)


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


@pytest.mark.parametrize(
    "schema",
    [
        # In this custom observer schema:
        # - `spec.type` is present in the manifest but not observed
        # - `spec.clusterIP` is not present in the manifest but is observed.
        # - the `spec.ports` lists has a first element partially observed, and accept up
        #   to 2 additional elements.
        # The observer schema is correctly formed.
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
        """,
        # Set the observer_schema_list_max_length to 0, meaning that the list doesn't
        # have a maximum length
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
        """,
        # Minimum valid observer_schema for a resource
        """---
        apiVersion: v1
        kind: Service
        metadata:
          name: nginx-demo
        namespace: null
        """,
    ],
)
def test_observer_schema_init_valid_custom(schema):
    """Validate that custom observer_schema are correctly initialized when they are
    valid.
    """
    valid_custom_observer_schema = list(yaml.safe_load_all(schema))

    app = ApplicationFactory(
        spec__manifest=kubernetes_manifest,
        spec__observer_schema=valid_custom_observer_schema,
    )

    assert app.spec.observer_schema == valid_custom_observer_schema


@pytest.mark.parametrize(
    "schema_msg",
    [
        (
            """---
            apiVersion: v1
            kind: Service
            metadata:
              name: nginx-demo
            namespace: null
            spec:
              ports:
              - null
            """,
            "Special list control dictionary not found",
        ),
        (
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
            """,
            "Special list control dictionary malformed",
        ),
        (
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
            """,
            "Special list control dictionary malformed",
        ),
        (
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
            """,
            "observer_schema_list_min_length should be an integer",
        ),
        (
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
            """,
            "observer_schema_list_max_length should be an integer",
        ),
        (
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
            """,
            "Invalid value for observer_schema_list_min_length",
        ),
        (
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
            """,
            "Invalid value for observer_schema_list_max_length",
        ),
        (
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
            """,
            "observer_schema_list_max_length is inferior to the number of observed"
            " elements",
        ),
        (
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
            """,
            "observer_schema_list_max_length is inferior to"
            " observer_schema_list_min_length",
        ),
        (
            """---
            not_the_apiVersion: v1
            kind: Service
            metadata:
              name: nginx-demo
              namespace: null
            """,
            "apiVersion is not defined",
        ),
        (
            """---
            apiVersion: v1
            not_the_kind: Service
            metadata:
              name: nginx-demo
              namespace: null
            """,
            "kind is not defined",
        ),
        (
            """---
            apiVersion: v1
            kind: Service
            not_the_metadata:
              name: nginx-demo
              namespace: null
            """,
            "metadata dictionary is not defined",
        ),
        (
            """---
            apiVersion: v1
            kind: Service
            metadata:
              not_the_name: nginx-demo
            """,
            "name is not defined in the metadata dictionary",
        ),
        (
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
            """,
            "Value of 'port' is not 'None'",
        ),
        (
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
            """,
            "Element of a list is not 'None'",
        ),
    ],
)
def test_observer_schema_init_invalid_custom(schema_msg):
    """Validate that invalid custom observer_schema are raising an Exception"""

    schema, message = schema_msg
    invalid_custom_schema = list(yaml.safe_load_all(schema))

    with pytest.raises(ObserverSchemaError, match=message):
        ApplicationFactory(
            spec__manifest=kubernetes_manifest,
            spec__observer_schema=invalid_custom_schema,
        )


def test_observer_schema_init_invalid_custom_not_in_manifest():
    """Validate that a custom observer_schema which matches a resource not present in
    the manifest file should raise an exception.
    """

    invalid_custom_schema = list(
        yaml.safe_load_all(
            """---
            apiVersion: v1
            kind: UnknownResource
            metadata:
              name: resource
              namespace: null
            """
        )
    )

    with pytest.raises(
        ObserverSchemaError, match="Observed resource must be in manifest"
    ):
        ApplicationFactory(spec__observer_schema=invalid_custom_schema)
