from datetime import datetime
import pytest
import pytz
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
    MagnumCluster,
)




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
        return fake.uuid4()


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

    id = fuzzy.FuzzyAttribute(fake.uuid4)
    status = SubFactory(ApplicationStatusFactory)
    user_id = fuzzy.FuzzyAttribute(fake.uuid4)

    @lazy_attribute
    def manifest(self):
        return kubernetes_manifest


class ClusterStatusFactory(Factory):
    class Meta:
        model = ClusterStatus

    class Params:
        cluster_kind = fuzzy.FuzzyChoice(
            list(ClusterKind.__members__.values())
        )

    state = fuzzy.FuzzyChoice(list(ClusterState.__members__.values()))
    created = fuzzy.FuzzyDateTime(datetime.now(tz=pytz.utc))

    @lazy_attribute
    def reason(self):
        if self.state != ApplicationState.FAILED:
            return None
        return fake.sentence()


class ClusterFactory(Factory):
    id = fuzzy.FuzzyAttribute(fake.uuid4)
    status = SubFactory(ClusterStatusFactory)
    kind = fuzzy.FuzzyChoice(list(ClusterKind.__members__.values()))


class MagnumClusterFactory(ClusterFactory):
    class Meta:
        model = MagnumCluster

    kind = ClusterKind.MAGNUM
    master_ip = fuzzy.FuzzyAttribute(fake.ipv4)
