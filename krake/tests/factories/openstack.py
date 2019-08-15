from factory import Factory, SubFactory, lazy_attribute, fuzzy

from .fake import fake
from .core import MetadataFactory
from krake.data.core import ResourceRef
from krake.data.openstack import (
    ApplicationCredential,
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

    @lazy_attribute
    def id(self):
        return fake.uuid4().replace("-", "")

    secret = fuzzy.FuzzyAttribute(fake.pystr)


class ProjectSpecFactory(Factory):
    class Meta:
        model = ProjectSpec

    auth_url = "http://localhost:5000"
    application_credential = SubFactory(ApplicationCredentialFactory)


class ProjectFactory(Factory):
    class Meta:
        model = Project

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(ProjectSpecFactory)


class MagnumClusterSpecFactory(Factory):
    class Meta:
        model = MagnumClusterSpec

    template = fuzzy.FuzzyText(length=7)
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


class MagnumClusterFactory(Factory):
    class Meta:
        model = MagnumCluster

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(MagnumClusterSpecFactory)
    status = SubFactory(MagnumClusterStatusFactory)
