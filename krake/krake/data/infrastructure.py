from enum import auto, Enum
from typing import List, Dict

from dataclasses import field

from marshmallow import ValidationError

from . import persistent
from .core import Metadata, Reason, MetricRef, ResourceRef
from .serializable import ApiObject, Serializable, PolymorphicContainer


class InfrastructureProviderSpec(PolymorphicContainer):
    type: str


@InfrastructureProviderSpec.register("im")
class ImSpec(Serializable):
    """IMSpec should contain access data to the IM provider instance.

    Attributes:
        url (str): endpoint of the IM provider instance.
        username (str, optional): IM provider instance username.
        password (str, optional): IM provider instance password.
        token (str, optional): IM provider instance token.
    """

    url: str
    username: str = None
    password: str = None
    token: str = None

    def __post_init__(self):
        """Method automatically ran at the end of the :meth:`__init__` method, used to
        validate dependent attributes.

        Validations:
        - At least one of the attributes from the following should be defined:
          - :attr:`username` and :attr:`password`
          - :attr:`token`
        """
        if self.token is None and (self.username is None or self.password is None):
            raise ValidationError(
                "At least one authentication should be defined in"
                " the IM infrastructure provider spec."
            )


@persistent("/infrastructure/globalinfrastructureproviders/{name}")
class GlobalInfrastructureProvider(ApiObject):
    api: str = "infrastructure"
    kind: str = "GlobalInfrastructureProvider"
    metadata: Metadata
    spec: InfrastructureProviderSpec


class GlobalInfrastructureProviderList(ApiObject):
    api: str = "infrastructure"
    kind: str = "GlobalInfrastructureProviderList"
    items: List[GlobalInfrastructureProvider]


@persistent("/infrastructure/infrastructureproviders/{namespace}/{name}")
class InfrastructureProvider(ApiObject):
    api: str = "infrastructure"
    kind: str = "InfrastructureProvider"
    metadata: Metadata
    spec: InfrastructureProviderSpec


class InfrastructureProviderList(ApiObject):
    api: str = "infrastructure"
    kind: str = "InfrastructureProviderList"
    items: List[InfrastructureProvider]


class InfrastructureProviderRef(Serializable):
    name: str
    namespaced: bool = False


class CloudBinding(ApiObject):
    api: str = "infrastructure"
    kind: str = "CloudBinding"
    cloud: ResourceRef


class OpenstackAuthMethod(PolymorphicContainer):
    """Container for the different authentication strategies of OpenStack
    Identity service (Keystone).
    """


class UserReference(Serializable):
    """Reference to the OpenStack user that is used by the :class:`Password`
    authentication strategy.

    Attributes:
        username (str): Username or UUID of the OpenStack user
        password (str): Password of the OpenStack user
        domain_name (str, optional): Domain name of the OpenStack user.
            Defaults to `Default`
        comment (str, optional): Arbitrary string for user-defined
            information, e.g. semantic names

    """

    username: str
    password: str
    domain_name: str = "Default"
    comment: str = None


class ProjectReference(Serializable):
    """Reference to the OpenStack project that is used by the :class:`Password`
    authentication strategy.

    Attributes:
        name (str): Name or UUID of the OpenStack project
        domain_id (str, optional): Domain ID of the OpenStack project.
            Defaults to `default`
        comment (str, optional): Arbitrary string for user-defined
            information, e.g. semantic names

    """

    name: str
    domain_id: str = "default"
    comment: str = None


@OpenstackAuthMethod.register("password")
class Password(Serializable):
    """Data for the password authentication strategy of the OpenStack
    identity service (Keystone).

    Attributes:
        version (str): OpenStack identity API version used for authentication
        user (UserReference): OpenStack user that will be used for authentication
        project (ProjectReference): OpenStack project that will be used by Krake

    """

    version: str = "3"
    user: UserReference
    project: ProjectReference


class CloudSpec(PolymorphicContainer):
    type: str


@CloudSpec.register("openstack")
class OpenstackSpec(Serializable):
    url: str
    auth: OpenstackAuthMethod
    metrics: List[MetricRef] = field(default_factory=list)
    infrastructure_provider: InfrastructureProviderRef


class CloudState(Enum):
    ONLINE = auto()
    FAILING_METRICS = auto()


class CloudStatus(Serializable):
    """Status subresource of :class:`GlobalCloud` and :class:`Cloud`.

    Attributes:
        state (CloudState): Current state of the cloud.
        metrics_reasons (dict[str, Reason]): Mapping of the name of the metrics for
            which an error occurred to the reason for which it occurred.

    """

    state: CloudState = CloudState.ONLINE
    metrics_reasons: Dict[str, Reason] = field(default_factory=dict)


@persistent("/infrastructure/globalclouds/{name}")
class GlobalCloud(ApiObject):
    api: str = "infrastructure"
    kind: str = "GlobalCloud"
    metadata: Metadata
    spec: CloudSpec
    status: CloudStatus = field(metadata={"subresource": True})

    def __post_init__(self):
        """Method automatically ran at the end of the :meth:`__init__` method, used to
        validate dependent attributes.

        Validations:
         1. A non-namespaced `GlobalCloud` resource cannot reference the namespaced
           `InfrastructureProvider` resource, see #499 for details
         2. A non-namespaced `GlobalCloud` resource cannot reference the namespaced
           `Metric` resource, see #499 for details

        Note: This validation cannot be achieved directly using the ``validate``
         metadata, since ``validate`` must be a zero-argument callable, with
         no access to the other attributes of the dataclass.

        """
        if self.spec.openstack.infrastructure_provider.namespaced:
            raise ValidationError(
                "A non-namespaced global cloud resource cannot reference the namespaced"
                " infrastructure provider resource."
            )

        if any([metric for metric in self.spec.openstack.metrics if metric.namespaced]):
            raise ValidationError(
                "A non-namespaced global cloud resource cannot reference the namespaced"
                " metric resource."
            )


class GlobalCloudList(ApiObject):
    api: str = "infrastructure"
    kind: str = "GlobalCloudList"
    items: List[GlobalCloud]


@persistent("/infrastructure/clouds/{namespace}/{name}")
class Cloud(ApiObject):
    api: str = "infrastructure"
    kind: str = "Cloud"
    metadata: Metadata
    spec: CloudSpec
    status: CloudStatus = field(metadata={"subresource": True})


class CloudList(ApiObject):
    api: str = "infrastructure"
    kind: str = "CloudList"
    items: List[Cloud]
