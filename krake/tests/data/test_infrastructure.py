import pytest
from marshmallow import ValidationError

from krake.data.core import MetricRef
from krake.data.infrastructure import (
    Cloud,
    GlobalCloud,
    InfrastructureProvider,
    GlobalInfrastructureProvider,
    InfrastructureProviderRef,
)
from tests.factories import fake
from tests.factories.infrastructure import (
    CloudFactory,
    GlobalCloudFactory,
    GlobalInfrastructureProviderFactory,
    InfrastructureProviderFactory,
)


@pytest.mark.parametrize(
    "resource,factory",
    [
        (GlobalInfrastructureProvider, GlobalInfrastructureProviderFactory),
        (InfrastructureProvider, InfrastructureProviderFactory),
        (GlobalCloud, GlobalCloudFactory),
        (Cloud, CloudFactory),
    ],
)
def test_resources_serialization_deserialization(resource, factory):
    """Ensure that infrastructure resources could be serialized
    and then deserialized."""
    instance = factory()
    serialized = instance.serialize()
    resource.deserialize(serialized)


@pytest.mark.parametrize(
    "infrastructure_provider_type,infrastructure_provider_resource",
    [
        ("im", GlobalInfrastructureProviderFactory),
        ("im", InfrastructureProviderFactory),
    ],
)
def test_infrastructure_provider_spec_empty_error_handling(
    infrastructure_provider_type, infrastructure_provider_resource
):
    """Ensure that empty token or, username or password are seen as invalid."""
    with pytest.raises(
        ValidationError,
        match="At least one authentication should be defined in"
        " the IM infrastructure provider spec.",
    ):
        infrastructure_provider_resource(
            **{
                "spec__type": infrastructure_provider_type,
                f"spec__{infrastructure_provider_type}__username": None,
                f"spec__{infrastructure_provider_type}__password": None,
                f"spec__{infrastructure_provider_type}__token": None,
            }
        )


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", GlobalCloudFactory),
    ],
)
def test_global_cloud_infrastructure_provider_reference_error_handling(
    cloud_type, cloud_resource
):
    """Ensure that a non-namespaced `GlobalCloud` resource cannot
    reference the namespaced `InfrastructureProvider` resource.
    """
    with pytest.raises(
        ValidationError,
        match="A non-namespaced global cloud resource cannot"
        " reference the namespaced infrastructure provider resource.",
    ):
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__infrastructure_provider": InfrastructureProviderRef(  # noqa: E501
                    name=fake.word(),
                    namespaced=True,
                ),
            }
        )


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", GlobalCloudFactory),
    ],
)
def test_global_cloud_metric_reference_error_handling(cloud_type, cloud_resource):
    """Ensure that a non-namespaced `GlobalCloud` resource cannot
    reference the namespaced `Metric` resource.
    """
    with pytest.raises(
        ValidationError,
        match="A non-namespaced global cloud resource cannot"
        " reference the namespaced metric resource.",
    ):
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(
                        name=fake.word(),
                        weight=1,
                        namespaced=False,
                    ),
                    MetricRef(
                        name=fake.word(),
                        weight=1,
                        namespaced=True,  # namespaced metric
                    ),
                    MetricRef(
                        name=fake.word(),
                        weight=1,
                        namespaced=False,
                    ),
                ],
            }
        )
