from dataclasses import MISSING
from factory import Factory, SubFactory, lazy_attribute, fuzzy, Maybe

from .fake import fake
from .core import MetadataFactory, ReasonFactory
from krake.data.core import ResourceRef
from krake.data.openstack import (
    UserReference,
    ProjectReference,
    Password,
    ApplicationCredential,
    AuthMethod,
    ProjectSpec,
    Project,
    MagnumClusterSpec,
    MagnumClusterStatus,
    MagnumClusterState,
    MagnumCluster,
)


class ApplicationCredentialFactory(Factory):
    class Meta:
        model = ApplicationCredential

    id = fuzzy.FuzzyAttribute(fake.uuid4)
    secret = fuzzy.FuzzyAttribute(fake.pystr)


class UserReferenceFactory(Factory):
    class Meta:
        model = UserReference

    id = fuzzy.FuzzyAttribute(fake.uuid4)
    password = fuzzy.FuzzyText()
    comment = fuzzy.FuzzyAttribute(fake.sentence)


class ProjectReferenceFactory(Factory):
    class Meta:
        model = ProjectReference

    id = fuzzy.FuzzyAttribute(fake.uuid4)
    comment = fuzzy.FuzzyAttribute(fake.sentence)


class PasswordFactory(Factory):
    class Meta:
        model = Password

    user = SubFactory(UserReferenceFactory)
    project = SubFactory(ProjectReferenceFactory)


class AuthMethodFactory(Factory):
    class Meta:
        model = AuthMethod

    class Params:
        @lazy_attribute
        def is_password(self):
            return self.type == "password"

        @lazy_attribute
        def is_application_credential(self):
            return self.type == "application_credential"

    password = Maybe("is_password", SubFactory(PasswordFactory), MISSING)
    application_credential = Maybe(
        "is_application_credential", SubFactory(ApplicationCredentialFactory), MISSING
    )

    @lazy_attribute
    def type(self):
        return fake.random.choice(list(AuthMethod.Schema._registry.keys()))

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Remove MISSING attributes
        for key in list(kwargs.keys()):
            if kwargs[key] is MISSING:
                del kwargs[key]

        return model_class(*args, **kwargs)


class ProjectSpecFactory(Factory):
    class Meta:
        model = ProjectSpec

    url = "http://localhost:5000/v3"
    auth = SubFactory(AuthMethodFactory)


class ProjectFactory(Factory):
    class Meta:
        model = Project

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(ProjectSpecFactory)


class MagnumClusterSpecFactory(Factory):
    class Meta:
        model = MagnumClusterSpec

    template = fuzzy.FuzzyAttribute(fake.uuid4)
    master_count = fuzzy.FuzzyChoice([None, 1, 2])
    node_count = fuzzy.FuzzyChoice([None, 2, 3])


class MagnumClusterStatusFactory(Factory):
    class Meta:
        model = MagnumClusterStatus

    class Params:
        @lazy_attribute
        def is_scheduled(self):
            return self.state != MagnumClusterState.PENDING

    state = fuzzy.FuzzyChoice(list(MagnumClusterState.__members__.values()))

    @lazy_attribute
    def project(self):
        if not self.is_scheduled:
            return None

        return ResourceRef(
            api="kubernetes", kind="Project", namespace=fake.name(), name=fake.name()
        )

    @lazy_attribute
    def cluster_id(self):
        if self.state == MagnumClusterState.PENDING:
            return None
        return fake.uuid4()

    @lazy_attribute
    def reason(self):
        if self.state != MagnumClusterState.FAILED:
            return None
        return ReasonFactory()

    @lazy_attribute
    def cluster(self):
        if self.state == MagnumClusterState.PENDING:
            return None

        return ResourceRef(
            api="kubernetes",
            kind="Cluster",
            name=self.factory_parent.metadata.name,
            namespace=self.factory_parent.metadata.namespace,
        )


class MagnumClusterFactory(Factory):
    class Meta:
        model = MagnumCluster

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(MagnumClusterSpecFactory)
    status = SubFactory(MagnumClusterStatusFactory)
