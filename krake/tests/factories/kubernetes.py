from datetime import datetime
import pytest
import pytz
import yaml
from factory import Factory, SubFactory, lazy_attribute, fuzzy

from .fake import fake
from krake.data.kubernetes import (
    ApplicationStatus,
    ApplicationState,
    Application,
    ClusterState,
    ClusterStatus,
    ClusterKind,
    Cluster,
    ClusterRef,
    MagnumCluster,
)


def fuzzy_name():
    return "-".join(fake.name().split()).lower()


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
            user = self.factory_parent.user
        else:
            user = fuzzy_name()
        return ClusterRef(name=fuzzy_name(), user=user)


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


class ApplicationFactory(Factory):
    class Meta:
        model = Application

    name = fuzzy.FuzzyAttribute(fuzzy_name)
    user = fuzzy.FuzzyAttribute(fuzzy_name)
    uid = fuzzy.FuzzyAttribute(fake.uuid4)
    status = SubFactory(ApplicationStatusFactory)

    @lazy_attribute
    def manifest(self):
        return kubernetes_manifest


class ClusterStatusFactory(Factory):
    class Meta:
        model = ClusterStatus

    class Params:
        cluster_kind = fuzzy.FuzzyChoice(list(ClusterKind.__members__.values()))

    state = fuzzy.FuzzyChoice(list(ClusterState.__members__.values()))
    created = fuzzy.FuzzyDateTime(datetime.now(tz=pytz.utc))

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


class ClusterFactory(Factory):
    name = fuzzy.FuzzyAttribute(fuzzy_name)
    user = fuzzy.FuzzyAttribute(fuzzy_name)
    kind = fuzzy.FuzzyChoice(list(ClusterKind.__members__.values()))
    uid = fuzzy.FuzzyAttribute(fake.uuid4)
    status = SubFactory(ClusterStatusFactory)

    @lazy_attribute
    def kubeconfig(self):
        return local_kubeconfig


class MagnumClusterFactory(ClusterFactory):
    class Meta:
        model = MagnumCluster

    kind = ClusterKind.MAGNUM
    master_ip = fuzzy.FuzzyAttribute(fake.ipv4)
