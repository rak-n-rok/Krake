import pytest

from krake.data.infrastructure import (
    Cloud,
    GlobalCloud,
    InfrastructureProvider,
    GlobalInfrastructureProvider,
)
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
