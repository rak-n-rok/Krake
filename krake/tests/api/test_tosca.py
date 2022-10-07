"""This module contains unit tests for TOSCA parser,
validator and translator to Kubernetes manifests.
"""
import os
from zipfile import ZipFile

import pytest
from marshmallow import ValidationError

from krake.data.kubernetes import Application
from krake.api.tosca import ToscaParser, ToscaParserException
from tests.factories import fake
from tests.factories.kubernetes import (
    ApplicationFactory,
)


# Test app serialize/deserialize using TOSCA/CSAR


def test_tosca_template_serialize_deserialize(tosca_pod, tosca):
    """Ensure that valid TOSCA template could be serialized and then deserialized."""
    app = ApplicationFactory(
        spec__manifest=[tosca_pod],
        spec__tosca=tosca,
    )
    serialized = app.serialize()
    assert Application.deserialize(serialized)


def test_csar_serialize_deserialize(tosca_pod):
    """Ensure that CSAR field could be serialized and then deserialized."""
    app = ApplicationFactory(
        spec__manifest=[tosca_pod], spec__csar=fake.file_name(extension="csar")
    )
    serialized = app.serialize()
    assert Application.deserialize(serialized)


def test_tosca_template_deserialize_error_handling(tosca):
    """Ensure that invalid TOSCA template is seen as invalid."""
    app = ApplicationFactory(
        spec__manifest=[],
        spec__tosca=tosca,
    )
    serialized = app.serialize()
    del serialized["spec"]["tosca"]["tosca_definitions_version"]

    with pytest.raises(
        ValidationError,
        match='Template is missing required field "tosca_definitions_version"',
    ):
        Application.deserialize(serialized)


# Test TOSCA/CSAR parser and validator


def test_tosca_validator_valid_tosca_template(tosca):
    """Test the validation with a valid TOSCA template."""
    parser = ToscaParser.from_dict(tosca)
    assert parser.tosca_template


def test_tosca_validator_missing_required_version_field(tosca):
    """Test the validation when version field missing."""
    del tosca["tosca_definitions_version"]

    with pytest.raises(
        ToscaParserException,
        match='Template is missing required field "tosca_definitions_version"',
    ):
        ToscaParser.from_dict(tosca)


def test_tosca_validator_missing_custom_type_definition(tosca):
    """Test the validation when custom type in not defined."""
    invalid_template = tosca
    del invalid_template["data_types"]

    with pytest.raises(
        ToscaParserException,
        match='Type "tosca.nodes.indigo.KubernetesObject" is not a valid type',
    ):
        ToscaParser.from_dict(tosca)


def test_tosca_validator_missing_spec_definition(tosca):
    """Test the validation when spec in not defined."""
    del tosca["topology_template"]["node_templates"]["example-pod"]["properties"][
        "spec"
    ]

    with pytest.raises(
        ToscaParserException,
        match="missing required field.*spec",
    ):
        ToscaParser.from_dict(tosca)


def test_tosca_validator_valid_csar(csar):
    """Test the validation with a valid CSAR file."""
    parser = ToscaParser.from_path(csar)
    assert parser.tosca_template


def test_tosca_validator_valid_csar_zip_suffix(csar):
    """Test the validation with a valid CSAR file with zip suffix."""
    csar_zip = csar.replace(".csar", ".zip")
    os.rename(csar, csar_zip)

    parser = ToscaParser.from_path(csar_zip)
    assert parser.tosca_template


def test_tosca_validator_invalid_suffix_csar(csar):
    """Test the validation with an invalid CSAR file suffix."""
    csar_gzip = csar.replace(".csar", ".gzip")
    os.rename(csar, csar_gzip)

    with pytest.raises(
        ToscaParserException,
        match=f'"{csar_gzip}" is not a valid file.',
    ):
        ToscaParser.from_path(csar_gzip)


def test_tosca_validator_missing_meta_csar(tmp_path, csar):
    """Test the validation with missing meta file."""
    csar_updated = tmp_path / "updated.csar"
    with ZipFile(csar) as csar_fd:
        with ZipFile(csar_updated, "w") as csar_updated_fd:
            for file in csar_fd.infolist():
                if file.filename == "TOSCA-Metadata/TOSCA.meta":
                    continue

                csar_updated_fd.writestr(file, csar_fd.read(file.filename))

    with pytest.raises(
        ToscaParserException,
        match=f'"{csar_updated}" is not a valid CSAR as it does not contain'
        ' the required file "TOSCA.meta" in the folder "TOSCA-Metadata".',
    ):
        ToscaParser.from_path(str(csar_updated))


# Test TOSCA/CSAR translator to Kubernetes manifest


def test_tosca_translator_valid_template(tosca, tosca_pod):
    """Test the translator with a valid TOSCA template."""
    parser = ToscaParser.from_dict(tosca)
    assert parser.translate_to_manifests() == [tosca_pod]


def test_tosca_translator_valid_csar(csar, tosca_pod):
    """Test the translator with a valid CSAR."""
    parser = ToscaParser.from_path(csar)
    assert parser.translate_to_manifests() == [tosca_pod]


def test_tosca_translator_missing_topology_template(tosca):
    """Test the translator when topology_template is not defined."""
    del tosca["topology_template"]

    parser = ToscaParser.from_dict(tosca)
    with pytest.raises(
        ToscaParserException,
        match="TOSCA does not contain any topology template.",
    ):
        parser.translate_to_manifests()


def test_tosca_translator_missing_node_template(tosca):
    """Test the translator when node_templates is not defined."""
    del tosca["topology_template"]["node_templates"]

    parser = ToscaParser.from_dict(tosca)
    with pytest.raises(
        ToscaParserException,
        match="TOSCA does not contain any node template.",
    ):
        parser.translate_to_manifests()


def test_tosca_translator_empty_spec(tosca):
    """Test the translator when spec is empty string."""
    tosca["topology_template"]["node_templates"]["example-pod"]["properties"][
        "spec"
    ] = ""

    parser = ToscaParser.from_dict(tosca)
    with pytest.raises(
        ToscaParserException,
        match="TOSCA node property `spec` must not be empty.",
    ):
        parser.translate_to_manifests()


def test_tosca_translator_with_unsupported_function(tosca):
    """Test the translator when spec contains unsupported tosca function."""
    tosca["topology_template"]["node_templates"]["example-pod"]["properties"][
        "spec"
    ] = {"token": ["test_token", ":", 1]}

    parser = ToscaParser.from_dict(tosca)
    with pytest.raises(
        ToscaParserException,
        match="Function token is not supported by Krake TOSCA engine yet.",
    ):
        parser.translate_to_manifests()
