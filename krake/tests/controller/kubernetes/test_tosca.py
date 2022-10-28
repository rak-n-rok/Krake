"""This module contains unit tests for TOSCA parser,
validator and translator to Kubernetes manifests.
"""
import pytest
import yaml
from marshmallow import ValidationError

from krake.data.kubernetes import Application
from krake.controller.kubernetes.tosca import ToscaParser, ToscaParserException
from tests.controller.kubernetes import deployment_manifest
from tests.factories import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
)

CSAR_META = """
TOSCA-Meta-File-Version: 1.0
CSAR-Version: 1.1
Created-By: Krake
Entry-Definitions: {entry_definition}
"""


def create_tosca_from_resources(resources, inputs=None):
    """Create TOSCA template from Kubernetes resources.

    Example:
        .. code:: python

            def test_tosca():

                resource = {
                    "apiVersion": "v1",
                    "kind": "Example",
                    "metadata": {
                        "name": "example"
                    }
                }
                assert create_tosca_from_resources([resource]) == {
                    "tosca_definitions_version": "tosca_simple_yaml_1_0",
                    "data_types": {
                        "tosca.nodes.indigo.KubernetesObject": {
                            "derived_from": "tosca.nodes.Root",
                            "properties": {
                                "spec": {
                                    "type": "string",
                                    "required": True
                                }
                            },
                        }
                    },
                    "topology_template": {
                        "inputs": {},
                        "node_templates": {
                            "example": {
                                "type": "tosca.nodes.indigo.KubernetesObject",
                                "properties": {
                                    "spec": {
                                        "apiVersion": "v1",
                                        "kind": "Example",
                                        "metadata": {"name": "example"},
                                    }
                                },
                            }
                        },
                    },
                }

    Args:
        resources (list): List of Kubernetes resources that will be
            wrapped to the TOSCA template.
        inputs (dict, optional): TOSCA template inputs.

    Returns:
        dict: TOSCA template that contains given k8s resources.

    """
    if inputs is None:
        inputs = {}

    node_templates = {}
    for resource in resources:
        node_templates.update(
            {
                resource["metadata"]["name"]: {
                    "type": "tosca.nodes.indigo.KubernetesObject",
                    "properties": {"spec": resource},
                }
            }
        )

    return {
        "tosca_definitions_version": "tosca_simple_yaml_1_0",
        "data_types": {
            "tosca.nodes.indigo.KubernetesObject": {
                "derived_from": "tosca.nodes.Root",
                "properties": {
                    "spec": {
                        "type": "string",
                        "required": True,
                    }
                },
            }
        },
        "topology_template": {
            "inputs": inputs,
            "node_templates": node_templates,
        },
    }


# Test app serialize/deserialize using TOSCA/CSAR


def test_tosca_template_dict_serialize_deserialize():
    """Ensure that valid TOSCA template dict could be serialized and
    then deserialized.
    """
    app = ApplicationFactory(
        spec__tosca=create_tosca_from_resources([deployment_manifest]),
    )
    serialized = app.serialize()
    assert Application.deserialize(serialized)


def test_tosca_template_url_serialize_deserialize():
    """Ensure that valid TOSCA template URL could be serialized and
    then deserialized.
    """
    app = ApplicationFactory(
        spec__tosca=fake.url() + "tosca.yaml",
    )
    serialized = app.serialize()
    assert Application.deserialize(serialized)


def test_csar_url_serialize_deserialize():
    """Ensure that CSAR field could be serialized and then deserialized."""
    app = ApplicationFactory(spec__csar=fake.url() + "archive.csar")
    serialized = app.serialize()
    assert Application.deserialize(serialized)


def test_tosca_template_dict_deserialize_error_handling():
    """Ensure that invalid TOSCA template dict is seen as invalid."""
    app = ApplicationFactory(
        spec__tosca=create_tosca_from_resources([deployment_manifest]),
    )
    serialized = app.serialize()
    del serialized["spec"]["tosca"]["tosca_definitions_version"]

    with pytest.raises(
        ValidationError,
        match="Invalid TOSCA template content.",
    ):
        Application.deserialize(serialized)


def test_tosca_template_url_deserialize_error_handling():
    """Ensure that invalid TOSCA template URL is seen as invalid."""
    app = ApplicationFactory(
        spec__tosca=fake.url() + "tosca.json",
    )
    serialized = app.serialize()

    with pytest.raises(
        ValidationError,
        match="Invalid TOSCA template URL.",
    ):
        Application.deserialize(serialized)


def test_csar_url_deserialize_error_handling():
    """Ensure that invalid CSAR URL is seen as invalid."""
    app = ApplicationFactory(
        spec__csar=fake.url() + "archive.gzip",
    )
    serialized = app.serialize()

    with pytest.raises(
        ValidationError,
        match="Invalid CSAR archive URL.",
    ):
        Application.deserialize(serialized)


# Test TOSCA/CSAR parser, validator and translator


def test_tosca_validator_valid_tosca_template_from_dict():
    """Test the validation with a valid TOSCA template from dict."""
    parser = ToscaParser.from_dict(create_tosca_from_resources([deployment_manifest]))
    assert parser.translate_to_manifests() == [deployment_manifest]


def test_tosca_validator_valid_tosca_template_from_url(file_server):
    """Test the validation with a valid TOSCA template from URL."""
    tosca_url = file_server(create_tosca_from_resources([deployment_manifest]))
    parser = ToscaParser.from_url(tosca_url)
    assert parser.translate_to_manifests() == [deployment_manifest]


def test_tosca_validator_valid_tosca_template_from_path(tmp_path):
    """Test the validation with a valid TOSCA template from path."""
    tosca_path = tmp_path / "tosca.yaml"
    with open(tosca_path, "w") as tosca_fd:
        yaml.safe_dump(create_tosca_from_resources([deployment_manifest]), tosca_fd)

    parser = ToscaParser.from_path(str(tosca_path))
    assert parser.translate_to_manifests() == [deployment_manifest]


def test_tosca_validator_valid_csar_from_url(archive_files, file_server):
    """Test the validation with a valid CSAR from URL."""
    tosca = create_tosca_from_resources([deployment_manifest])
    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("tosca.yaml", tosca),
            (
                "TOSCA-Metadata/TOSCA.meta",
                CSAR_META.format(entry_definition="tosca.yaml"),
            ),
        ],
    )
    csar_url = file_server(csar_path, file_name="example.csar")

    parser = ToscaParser.from_url(csar_url)
    assert parser.translate_to_manifests() == [deployment_manifest]


def test_tosca_validator_valid_csar_from_path(archive_files):
    """Test the validation with a valid CSAR from path."""
    tosca = create_tosca_from_resources([deployment_manifest])
    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("tosca.yaml", tosca),
            (
                "TOSCA-Metadata/TOSCA.meta",
                CSAR_META.format(entry_definition="tosca.yaml"),
            ),
        ],
    )
    parser = ToscaParser.from_path(str(csar_path))
    assert parser.translate_to_manifests() == [deployment_manifest]


def test_tosca_validator_missing_required_version_field():
    """Test the validation when version field missing."""
    invalid_tosca = create_tosca_from_resources([deployment_manifest])
    del invalid_tosca["tosca_definitions_version"]

    with pytest.raises(
        ToscaParserException,
        match='Template is missing required field "tosca_definitions_version"',
    ):
        ToscaParser.from_dict(invalid_tosca)


def test_tosca_validator_missing_custom_type_definition():
    """Test the validation when custom type in not defined."""
    invalid_tosca = create_tosca_from_resources([deployment_manifest])
    del invalid_tosca["data_types"]

    with pytest.raises(
        ToscaParserException,
        match='Type "tosca.nodes.indigo.KubernetesObject" is not a valid type',
    ):
        ToscaParser.from_dict(invalid_tosca)


def test_tosca_validator_missing_spec_definition():
    """Test the validation when spec in not defined."""
    invalid_tosca = create_tosca_from_resources([deployment_manifest])
    del invalid_tosca["topology_template"]["node_templates"][
        deployment_manifest["metadata"]["name"]
    ]["properties"]["spec"]

    with pytest.raises(
        ToscaParserException,
        match="missing required field.*spec",
    ):
        ToscaParser.from_dict(invalid_tosca)


def test_tosca_translator_missing_topology_template():
    """Test the translator when topology_template is not defined."""
    invalid_tosca = create_tosca_from_resources([deployment_manifest])
    del invalid_tosca["topology_template"]

    parser = ToscaParser.from_dict(invalid_tosca)
    with pytest.raises(
        ToscaParserException,
        match="TOSCA does not contain any topology template.",
    ):
        parser.translate_to_manifests()


def test_tosca_translator_missing_node_template():
    """Test the translator when node_templates is not defined."""
    invalid_tosca = create_tosca_from_resources([deployment_manifest])
    del invalid_tosca["topology_template"]["node_templates"]

    parser = ToscaParser.from_dict(invalid_tosca)
    with pytest.raises(
        ToscaParserException,
        match="TOSCA does not contain any node template.",
    ):
        parser.translate_to_manifests()


def test_tosca_translator_empty_spec():
    """Test the translator when spec is empty string."""
    invalid_tosca = create_tosca_from_resources([deployment_manifest])
    invalid_tosca["topology_template"]["node_templates"][
        deployment_manifest["metadata"]["name"]
    ]["properties"]["spec"] = ""

    parser = ToscaParser.from_dict(invalid_tosca)
    with pytest.raises(
        ToscaParserException,
        match="TOSCA node property `spec` must not be empty.",
    ):
        parser.translate_to_manifests()


def test_tosca_translator_with_unsupported_function():
    """Test the translator when spec contains unsupported tosca function."""
    invalid_tosca = create_tosca_from_resources([deployment_manifest])
    invalid_tosca["topology_template"]["node_templates"][
        deployment_manifest["metadata"]["name"]
    ]["properties"]["spec"] = {"token": ["test_token", ":", 1]}

    parser = ToscaParser.from_dict(invalid_tosca)
    with pytest.raises(
        ToscaParserException,
        match="Function token is not supported by the Krake TOSCA engine yet.",
    ):
        parser.translate_to_manifests()


def test_tosca_validator_missing_meta_csar(archive_files):
    """Test the validation with missing meta file."""
    tosca = create_tosca_from_resources([deployment_manifest])
    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("tosca.yaml", tosca),
        ],
    )

    with pytest.raises(
        ToscaParserException,
        match=f'"{csar_path}" is not a valid CSAR as it does not contain'
        ' the required file "TOSCA.meta" in the folder "TOSCA-Metadata".',
    ):
        ToscaParser.from_path(str(csar_path))
