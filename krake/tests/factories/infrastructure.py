from dataclasses import MISSING
from factory import Factory, SubFactory, lazy_attribute, Maybe, fuzzy

from krake.data.infrastructure import (
    InfrastructureProvider,
    GlobalInfrastructureProvider,
    InfrastructureProviderSpec,
    ImSpec,
    GlobalCloud,
    Cloud,
    CloudSpec,
    OpenstackSpec,
    InfrastructureProviderRef,
    OpenstackAuthMethod,
    Password,
    UserReference,
    ProjectReference,
    CloudState,
    CloudStatus,
)

from . import fake
from .core import MetadataFactory, BaseNonNamespaced, MetricRefFactory


class ImSpecFactory(Factory):
    class Meta:
        model = ImSpec

    url = fuzzy.FuzzyAttribute(fake.url)
    username = fuzzy.FuzzyAttribute(fake.word)
    password = fuzzy.FuzzyAttribute(fake.pystr)
    token = None


class InfrastructureProviderSpecFactory(Factory):
    class Meta:
        model = InfrastructureProviderSpec

    class Params:
        @lazy_attribute
        def is_im(self):
            return self.type == "im"

    im = Maybe("is_im", SubFactory(ImSpecFactory), MISSING)

    @lazy_attribute
    def type(self):
        return fake.random.choice(
            list(InfrastructureProviderSpec.Schema._registry.keys())
        )

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Remove MISSING attributes
        for key in list(kwargs.keys()):
            if kwargs[key] is MISSING:
                del kwargs[key]

        return model_class(*args, **kwargs)


class GlobalInfrastructureProviderFactory(BaseNonNamespaced, Factory):
    class Meta:
        model = GlobalInfrastructureProvider

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(InfrastructureProviderSpecFactory)


class InfrastructureProviderFactory(Factory):
    class Meta:
        model = InfrastructureProvider

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(InfrastructureProviderSpecFactory)


class InfrastructureProviderRefFactory(Factory):
    class Meta:
        model = InfrastructureProviderRef

    name = fuzzy.FuzzyAttribute(fake.word)


class ProjectReferenceFactory(Factory):
    class Meta:
        model = ProjectReference

    name = fuzzy.FuzzyAttribute(fake.word)
    domain_id = fuzzy.FuzzyAttribute(fake.word)
    comment = fuzzy.FuzzyAttribute(fake.word)


class UserReferenceFactory(Factory):
    class Meta:
        model = UserReference

    username = fuzzy.FuzzyAttribute(fake.word)
    password = fuzzy.FuzzyAttribute(fake.pystr)
    domain_name = fuzzy.FuzzyAttribute(fake.word)
    comment = fuzzy.FuzzyAttribute(fake.word)


class PasswordFactory(Factory):
    class Meta:
        model = Password

    version = str(fake.pyint(1, 3))
    user = SubFactory(UserReferenceFactory)
    project = SubFactory(ProjectReferenceFactory)


class OpenstackAuthMethodFactory(Factory):
    class Meta:
        model = OpenstackAuthMethod

    class Params:
        @lazy_attribute
        def is_password(self):
            return self.type == "password"

    password = Maybe("is_password", SubFactory(PasswordFactory), MISSING)

    @lazy_attribute
    def type(self):
        return fake.random.choice(list(OpenstackAuthMethod.Schema._registry.keys()))

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Remove MISSING attributes
        for key in list(kwargs.keys()):
            if kwargs[key] is MISSING:
                del kwargs[key]

        return model_class(*args, **kwargs)


class OpenstackSpecFactory(Factory):
    class Meta:
        model = OpenstackSpec

    class Params:
        metric_count = 3

    url = fuzzy.FuzzyAttribute(fake.url)
    auth = SubFactory(OpenstackAuthMethodFactory)
    infrastructure_provider = SubFactory(InfrastructureProviderRefFactory)

    @lazy_attribute
    def metrics(self):
        return [MetricRefFactory() for _ in range(self.metric_count)]


class CloudSpecFactory(Factory):
    class Meta:
        model = CloudSpec

    class Params:
        @lazy_attribute
        def is_openstack(self):
            return self.type == "openstack"

    openstack = Maybe("is_openstack", SubFactory(OpenstackSpecFactory), MISSING)

    @lazy_attribute
    def type(self):
        return fake.random.choice(list(CloudSpec.Schema._registry.keys()))

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Remove MISSING attributes
        for key in list(kwargs.keys()):
            if kwargs[key] is MISSING:
                del kwargs[key]

        return model_class(*args, **kwargs)


class CloudStatusFactory(Factory):
    class Meta:
        model = CloudStatus

    state = fuzzy.FuzzyChoice(list(CloudState.__members__.values()))

    @lazy_attribute
    def metrics_reasons(self):
        return dict()


class GlobalCloudFactory(BaseNonNamespaced, Factory):
    class Meta:
        model = GlobalCloud

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(CloudSpecFactory)
    status = SubFactory(CloudStatusFactory)


class CloudFactory(Factory):
    class Meta:
        model = Cloud

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(CloudSpecFactory)
    status = SubFactory(CloudStatusFactory)
