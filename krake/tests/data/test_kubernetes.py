import pytest
import yaml

from krake.data.kubernetes import ApplicationSpec

kubernetes_manifest = list(
    yaml.safe_load_all(
        """---
apiVersion: v1
kind: Service
metadata:
  name: nginx-demo
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

    valid_custom_observer_schema1 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
    spec:
      ports:
      - port: null
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 3
      clusterIP: null
    """
        )
    )

    # Minimum valid observer_schema for a resource
    valid_custom_observer_schema2 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
    """
        )
    )

    application_spec = ApplicationSpec(
        manifest=kubernetes_manifest, observer_schema=valid_custom_observer_schema1
    )

    assert application_spec.observer_schema == valid_custom_observer_schema1

    application_spec = ApplicationSpec(
        manifest=kubernetes_manifest, observer_schema=valid_custom_observer_schema2
    )

    assert application_spec.observer_schema == valid_custom_observer_schema2


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
    """
        )
    )

    # Invalid as it doesn't contain a metadata dictionary with the name
    invalid_custom_observer_schema12 = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    not_the_metadata:
      name: nginx-demo
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
    ports:
      - 8080
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 1

    """
        )
    )

    valid_custom_observer_schema = list(
        yaml.safe_load_all(
            """---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-demo
    """
        )
    )

    with pytest.raises(SyntaxError, match=r"Special list control dictionary not found"):
        app_spec_1 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema1,
        )
        ApplicationSpec.deserialize(app_spec_1.serialize())

    with pytest.raises(SyntaxError, match=r"Special list control dictionary malformed"):
        app_spec_2 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema2,
        )
        ApplicationSpec.deserialize(app_spec_2.serialize())

    with pytest.raises(SyntaxError, match=r"Special list control dictionary malformed"):
        app_spec_3 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema3,
        )
        ApplicationSpec.deserialize(app_spec_3.serialize())

    with pytest.raises(
        SyntaxError, match=r"observer_schema_list_min_length should be an integer"
    ):
        app_spec_4 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema4,
        )
        ApplicationSpec.deserialize(app_spec_4.serialize())

    with pytest.raises(
        SyntaxError, match=r"observer_schema_list_max_length should be an integer"
    ):
        app_spec_5 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema5,
        )
        ApplicationSpec.deserialize(app_spec_5.serialize())

    with pytest.raises(
        SyntaxError, match=r"Invalid value for observer_schema_list_min_length"
    ):
        app_spec_6 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema6,
        )
        ApplicationSpec.deserialize(app_spec_6.serialize())

    with pytest.raises(
        SyntaxError, match=r"Invalid value for observer_schema_list_max_length"
    ):
        app_spec_7 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema7,
        )
        ApplicationSpec.deserialize(app_spec_7.serialize())

    msg = (
        "observer_schema_list_max_length is inferior to the number of observed elements"
    )
    with pytest.raises(SyntaxError, match=msg):
        app_spec_8 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema8,
        )
        ApplicationSpec.deserialize(app_spec_8.serialize())

    msg = (
        "observer_schema_list_max_length is inferior to observer_schema_list_min_length"
    )
    with pytest.raises(SyntaxError, match=msg):
        app_spec_9 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema9,
        )
        ApplicationSpec.deserialize(app_spec_9.serialize())

    with pytest.raises(SyntaxError, match="apiVersion is not defined"):
        app_spec_10 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema10,
        )
        ApplicationSpec.deserialize(app_spec_10.serialize())

    with pytest.raises(SyntaxError, match="kind is not defined"):
        app_spec_11 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema11,
        )
        ApplicationSpec.deserialize(app_spec_11.serialize())

    with pytest.raises(SyntaxError, match="metadata dictionary is not defined"):
        app_spec_12 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema12,
        )
        ApplicationSpec.deserialize(app_spec_12.serialize())

    with pytest.raises(
        SyntaxError, match="name is not defined in the metadata dictionary"
    ):
        app_spec_13 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema13,
        )
        ApplicationSpec.deserialize(app_spec_13.serialize())

    with pytest.raises(SyntaxError, match="Value of 'port' is not 'None'"):
        app_spec_14 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema14,
        )
        ApplicationSpec.deserialize(app_spec_14.serialize())

    with pytest.raises(SyntaxError, match="Element of a list is not 'None'"):
        app_spec_15 = ApplicationSpec(
            manifest=kubernetes_manifest,
            observer_schema=invalid_custom_observer_schema15,
        )
        ApplicationSpec.deserialize(app_spec_15.serialize())

    with pytest.raises(SyntaxError, match="Observed resource must be in manifest"):
        app_spec_17 = ApplicationSpec(
            manifest=[], observer_schema=valid_custom_observer_schema
        )
        ApplicationSpec.deserialize(app_spec_17.serialize())
