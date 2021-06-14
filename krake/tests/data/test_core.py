import pytest

from marshmallow import ValidationError
from krake.data.core import _validate_resource_name
from krake.data.core import _validate_resource_namespace


@pytest.mark.parametrize(
    "expression",
    [
        "minikube cluster 1",
        " minikube_cluster_1",
        "minikube_cluster_1 ",
        "minikube cluster_1",
        "minikube_cluster-",
        "-minikube_cluster_1",
        "minikube_cluster_1.",
        "-",
        ".",
        "",
        "a" * 500,
        "b" * 256,
    ],
)
def test_validate_resource_name_invalid_character(expression):
    """Test that invalid characters in resource name raise a ValidationError."""
    with pytest.raises(
        ValidationError,
        match="Invalid character in resource name.",
    ):
        _validate_resource_name(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "minikube_cluster_1",
        "minikube-cluster-1",
        "_minikube_cluster_",
        "minikube_cluster",
        "1_minikube_cluster_1",
        "534_minikube_cluster",
        "minikube_cluster_89982",
        "5",
        "a" * 255,
        "aa",
    ],
)
def test_validate_resource_name_valid_character(expression):
    """Test that valid characters in resource name are passed and raise nothing."""
    assert _validate_resource_name(expression) is None


@pytest.mark.parametrize(
    "expression",
    [
        "minikube cluster 1",
        " minikube_cluster_1",
        "minikube_cluster_1 ",
        "minikube cluster_1",
        "minikube_cluster-",
        "-minikube_cluster_1",
        "minikube_cluster_1.",
        "-",
        ".",
        "",
        "a" * 500,
        "b" * 256,
    ],
)
def test_validate_resource_namespace_invalid_character(expression):
    """Test that invalid characters in resource namespace raise a ValidationError."""
    with pytest.raises(
        ValidationError,
        match="Invalid character in resource namespace.",
    ):
        _validate_resource_namespace(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "minikube_cluster_1",
        "minikube-cluster-1",
        "_minikube_cluster_",
        "minikube_cluster",
        "1_minikube_cluster_1",
        "534_minikube_cluster",
        "minikube_cluster_89982",
        "5",
        "a" * 255,
        "aa",
    ],
)
def test_validate_resource_namespace_valid_character(expression):
    """Test that valid characters in resource namespace are passed and raise nothing."""
    assert _validate_resource_namespace(expression) is None
