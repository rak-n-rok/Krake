from datetime import datetime
import pytest
import pytz
import yaml
from factory import Factory, SubFactory, Trait, lazy_attribute, fuzzy

from .fake import fake
from krake.data.metadata import Metadata
from krake.data.kubernetes import (
    ApplicationSpec,
    ApplicationStatus,
    ApplicationState,
    Application,
    ClusterSpec,
    ClusterState,
    ClusterStatus,
    ClusterKind,
    Cluster,
    MagnumClusterSpec,
)


def fuzzy_name():
    return "-".join(fake.name().split()).lower()


class MetadataFactory(Factory):
    class Meta:
        model = Metadata

    name = fuzzy.FuzzyAttribute(fuzzy_name)
    # namespace = fuzzy.FuzzyAttribute(fuzzy_name)
    namespace = "testing"
    uid = fuzzy.FuzzyAttribute(fake.uuid4)
    user = fuzzy.FuzzyAttribute(fuzzy_name)


class ApplicationStatusFactory(Factory):
    class Meta:
        model = ApplicationStatus

    state = fuzzy.FuzzyChoice(list(ApplicationState.__members__.values()))
    created = fuzzy.FuzzyDateTime(datetime.now(tz=pytz.utc))

    @lazy_attribute
    def modified(self):
        if self.state == ApplicationState.PENDING:
            return self.created

        delta = fake.time_delta()
        return self.created + delta

    @lazy_attribute
    def reason(self):
        if self.state != ApplicationState.FAILED:
            return None
        return fake.sentence()

    @lazy_attribute
    def cluster(self):
        if self.state == ApplicationState.PENDING:
            return None
        if self.factory_parent:
            namespace = self.factory_parent.metadata.user
        else:
            namespace = fuzzy_name()
        name = fuzzy_name()
        return f"/namespaces/{namespace}/kubernetes/clusters/{name}"
        # return create_key(Cluster, namespace=user, name=fuzzy_name())


kubernetes_manifest = """---
apiVersion: v1
kind: Service
metadata:
  name: wordpress-mysql
  labels:
    app: wordpress
spec:
  ports:
    - port: 3306
  selector:
    app: wordpress
    tier: mysql
  clusterIP: None
"""


class ApplicationSpecFactory(Factory):
    class Meta:
        model = ApplicationSpec

    @lazy_attribute
    def manifest(self):
        return kubernetes_manifest

    @lazy_attribute
    def cluster(self):
        if self.factory_parent:
            if self.factory_parent.status.state == ApplicationState.PENDING:
                return None
            namespace = self.factory_parent.metadata.user
        else:
            if not fake.pybool():
                return None
            namespace = fuzzy_name()
        name = fuzzy_name()
        return f"/namespaces/{namespace}/kubernetes/clusters/{name}"


class ApplicationFactory(Factory):
    class Meta:
        model = Application

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(ApplicationSpecFactory)
    status = SubFactory(ApplicationStatusFactory)


class ClusterSpecFactory(Factory):
    class Meta:
        model = ClusterSpec


class ClusterStatusFactory(Factory):
    class Meta:
        model = ClusterStatus

    class Params:
        cluster_kind = fuzzy.FuzzyChoice(list(ClusterKind.__members__.values()))

    state = fuzzy.FuzzyChoice(list(ClusterState.__members__.values()))
    created = fuzzy.FuzzyDateTime(datetime.now(tz=pytz.utc))

    @lazy_attribute
    def modified(self):
        if self.state == ApplicationState.PENDING:
            return self.created

        delta = fake.time_delta()
        return self.created + delta

    @lazy_attribute
    def reason(self):
        if self.state != ApplicationState.FAILED:
            return None
        return fake.sentence()


local_kubeconfig = yaml.safe_load(
    """---
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: REMOVED
    server: https://127.0.0.1:8080
  name: minikube
contexts:
- context:
    cluster: minikube
    user: minikube
  name: minikube
current-context: minikube
kind: Config
preferences: {}
users:
- name: minikube
  user:
    client-certificate-data: REMOVED
    client-key-data: REMOVED
"""
)


class ClusterSpecFactory(ClusterSpecFactory):
    class Meta:
        model = ClusterSpec

    @lazy_attribute
    def kubeconfig(self):
        return local_kubeconfig


class MagnumClusterSpecFactory(ClusterSpecFactory):
    class Meta:
        model = MagnumClusterSpec

    kind = ClusterKind.MAGNUM
    master_ip = fuzzy.FuzzyAttribute(fake.ipv4)


class ClusterFactory(Factory):
    class Params:
        magnum = Trait(spec=SubFactory(MagnumClusterSpecFactory))

    class Meta:
        model = Cluster

    metadata = SubFactory(MetadataFactory)
    status = SubFactory(ClusterStatusFactory)
    spec = SubFactory(ClusterSpecFactory)
