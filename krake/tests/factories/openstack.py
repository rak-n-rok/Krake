from dataclasses import MISSING
from factory import Factory, SubFactory, lazy_attribute, fuzzy, Maybe, Iterator
from itertools import cycle

from .fake import fake
from .core import MetadataFactory, ReasonFactory, MetricRefFactory
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
    Constraints,
    ProjectConstraints,
    ProjectStatus,
)
from krake.data.constraints import (
    EqualConstraint,
    NotEqualConstraint,
    InConstraint,
    NotInConstraint,
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


label_constraints = cycle(
    (
        EqualConstraint(label="location", value="EU"),
        NotEqualConstraint(label="location", value="DE"),
        InConstraint(label="location", values=("SK", "DE")),
        NotInConstraint(label="location", values=("SK", "DE")),
    )
)


class ProjectConstraintsFactory(Factory):
    class Meta:
        model = ProjectConstraints

    labels = Iterator(map(lambda constraint: [constraint], label_constraints))


class ConstraintsFactory(Factory):
    class Meta:
        model = Constraints

    project = SubFactory(ProjectConstraintsFactory)


class ProjectSpecFactory(Factory):
    class Meta:
        model = ProjectSpec

    class Params:
        metric_count = 3

    url = "http://localhost:5000/v3"
    auth = SubFactory(AuthMethodFactory)
    template = fuzzy.FuzzyAttribute(fake.uuid4)

    @lazy_attribute
    def metrics(self):
        return [MetricRefFactory() for _ in range(self.metric_count)]


class ProjectStatusFactory(Factory):
    class Meta:
        model = ProjectStatus

    @lazy_attribute
    def metrics_reasons(self):
        return dict()


class ProjectFactory(Factory):
    class Meta:
        model = Project

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(ProjectSpecFactory)
    status = SubFactory(ProjectStatusFactory)


class MagnumClusterSpecFactory(Factory):
    class Meta:
        model = MagnumClusterSpec

    class Params:
        metric_count = 3

    constraints = SubFactory(ConstraintsFactory)
    master_count = fuzzy.FuzzyChoice([None, 1, 2])
    node_count = fuzzy.FuzzyChoice([None, 2, 3])

    @lazy_attribute
    def metrics(self):
        return [MetricRefFactory() for _ in range(self.metric_count)]


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
    def template(self):
        if not self.is_scheduled:
            return None

        return fake.uuid4()

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
