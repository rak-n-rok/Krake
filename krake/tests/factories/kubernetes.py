from base64 import b64encode
from itertools import cycle
from copy import deepcopy
from factory import (
    Factory,
    SubFactory,
    lazy_attribute,
    fuzzy,
    Iterator,
    post_generation,
)
import yaml
import pytz

from .fake import fake
from .core import MetadataFactory, ReasonFactory, MetricRefFactory
from krake.data.core import ResourceRef
from krake.data.kubernetes import (
    ApplicationSpec,
    ApplicationStatus,
    ApplicationState,
    Application,
    ClusterSpec,
    Cluster,
    Constraints,
    ClusterConstraints,
    ClusterState,
    ClusterStatus,
    ClusterNode,
    ClusterNodeStatus,
    ClusterNodeCondition,
)
from krake.data.constraints import (
    EqualConstraint,
    NotEqualConstraint,
    InConstraint,
    NotInConstraint,
    EqualMetricConstraint,
    NotEqualMetricConstraint,
    GreaterThanMetricConstraint,
    GreaterThanOrEqualMetricConstraint,
    LesserThanMetricConstraint,
    LesserThanOrEqualMetricConstraint,
)


def fuzzy_name():
    return "-".join(fake.name().split()).lower()


def fuzzy_dict():
    return {fake.word(): fake.word()}


label_constraints = cycle(
    (
        EqualConstraint(label="location", value="EU"),
        NotEqualConstraint(label="location", value="DE"),
        InConstraint(label="location", values=("SK", "DE")),
        NotInConstraint(label="location", values=("SK", "DE")),
    )
)

metric_constraints = cycle(
    (
        EqualMetricConstraint(metric="load", value="5"),
        NotEqualMetricConstraint(metric="load", value="5"),
        GreaterThanMetricConstraint(metric="load", value="5"),
        GreaterThanOrEqualMetricConstraint(metric="load", value="5"),
        LesserThanMetricConstraint(metric="load", value="5"),
        LesserThanOrEqualMetricConstraint(metric="load", value="5"),
    )
)


class ClusterConstraintsFactory(Factory):
    class Meta:
        model = ClusterConstraints

    labels = Iterator(map(lambda constraint: [constraint], label_constraints))
    metrics = Iterator(map(lambda constraint: [constraint], metric_constraints))

    @lazy_attribute
    def custom_resources(self):
        return [fuzzy_name() for _ in range(fake.pyint(1, 3))]


class ConstraintsFactory(Factory):
    class Meta:
        model = Constraints

    cluster = SubFactory(ClusterConstraintsFactory)


class ApplicationStatusFactory(Factory):
    class Meta:
        model = ApplicationStatus

    class Params:
        """
        Attributes:
            is_scheduled (bool): Is used to control whether the
                ``.status.scheduled`` timestamp of before or after the
                ``.metadata.modified`` timestamp. If the application is in
                *PENDING* state, ``.status.scheduled`` is set to :data:`None`.

        """

        is_scheduled = fuzzy.FuzzyChoice([True, False])

    state = fuzzy.FuzzyChoice(list(ApplicationState.__members__.values()))

    @lazy_attribute
    def reason(self):
        if self.state != ApplicationState.FAILED:
            return None
        return ReasonFactory()

    @lazy_attribute
    def scheduled(self):
        if not self.factory_parent:
            return fake.date_time(tzinfo=pytz.utc)

        created = self.factory_parent.metadata.created
        modified = self.factory_parent.metadata.modified

        assert created <= modified

        if self.is_scheduled:
            return fake.date_time_between(start_date=modified, tzinfo=pytz.utc)
        elif self.state == ApplicationState.PENDING:
            return None  # Application was never scheduled
        else:
            return fake.date_time_between(
                start_date=created,
                end_date=self.kube_controller_triggered,
                tzinfo=pytz.utc,
            )

    @lazy_attribute
    def kube_controller_triggered(self):
        if not self.factory_parent:
            return fake.date_time()

        created = self.factory_parent.metadata.created
        modified = self.factory_parent.metadata.modified

        assert created <= modified

        if self.is_scheduled:
            return fake.date_time_between(start_date=self.scheduled, tzinfo=pytz.utc)
        elif self.state == ApplicationState.PENDING:
            return None  # Application was never scheduled
        else:
            return fake.date_time_between(
                start_date=created, end_date=modified, tzinfo=pytz.utc
            )

    @lazy_attribute
    def scheduled_to(self):
        if self.state == ApplicationState.PENDING:
            return None
        if self.factory_parent:
            namespace = self.factory_parent.metadata.namespace
        else:
            namespace = fuzzy_name()
        name = fuzzy_name()
        return ResourceRef(
            api="kubernetes", kind="Cluster", name=name, namespace=namespace
        )

    @lazy_attribute
    def running_on(self):
        if self.state == ApplicationState.PENDING:
            return None

        # If application is not migrating, the application is running on the
        # same cluster to which it was scheduled.
        if self.state != ApplicationState.MIGRATING:
            return self.scheduled_to

        if self.factory_parent:
            namespace = self.factory_parent.metadata.namespace
        else:
            namespace = fuzzy_name()
        name = fuzzy_name()
        return ResourceRef(
            api="kubernetes", kind="Cluster", name=name, namespace=namespace
        )


kubernetes_manifest = list(
    yaml.safe_load_all(
        """---
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
    )
)


class ApplicationSpecFactory(Factory):
    class Meta:
        model = ApplicationSpec

    @lazy_attribute
    def manifest(self):
        return deepcopy(kubernetes_manifest)

    constraints = SubFactory(ConstraintsFactory)


class ApplicationFactory(Factory):
    class Meta:
        model = Application

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(ApplicationSpecFactory)
    status = SubFactory(ApplicationStatusFactory)

    @post_generation
    def add_owners(app, created, extracted, **kwargs):
        if app.status is None:
            return

        if app.status.scheduled_to:
            if app.status.scheduled_to not in app.metadata.owners:
                app.metadata.owners.append(app.status.scheduled_to)

        if app.status.running_on:
            if app.status.running_on not in app.metadata.owners:
                app.metadata.owners.append(app.status.running_on)


ca_cert = b"""-----BEGIN CERTIFICATE-----
MIIC5zCCAc+gAwIBAgIBATANBgkqhkiG9w0BAQsFADAVMRMwEQYDVQQDEwptaW5p
a3ViZUNBMB4XDTE5MDYyNTExNDQxNloXDTI5MDYyMzExNDQxNlowFTETMBEGA1UE
AxMKbWluaWt1YmVDQTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBANvG
O38eqYA/mUiFmrfpE24QuE8hxYRVDbSMgTzWfpbaa7GD01u8e+8yfW3CSQmu+l+8
6XTKCp7+/Ln/mDlkpLRRqy3nj1OBt2cXGcMHTPJKoyzi/Z/GszTjO2ZmjMoYm3eT
9LvXefC1CWfgJXF+fPHvCrsIxyqzqvqktS3rF4kJ2t2VrrfMtwCEru8jVKjUT3Fa
ucTZo+pxFzb/+Rum/ozluMIi/BKZHPBOEwPl4wokS+VHq8gkuAj0dwu511VoaQZl
3m1KGJKOl1dJ7k0ba7qC6Gcpw612XiADoaWG8dUlyzR+fDH5mAWJzyNrxpvBPkJn
QLc4ExHtqRUMsFw5XgsCAwEAAaNCMEAwDgYDVR0PAQH/BAQDAgKkMB0GA1UdJQQW
MBQGCCsGAQUFBwMCBggrBgEFBQcDATAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3
DQEBCwUAA4IBAQBFis+3ylwL4bJqbOb/BeSdKEaErASqsunPqfxwqJFMBoqFp1Ho
/D7a8A/pu4aZBrl59YQ3fYjXVhm+ToTHHYXveCMLdewPyihYHSQF0hYd2W908BUK
bbQoda95uOaSWtRtvxtBelR5dxg39K3v6lPpg1T3uXJR3zc09Ijhtb1RY+czrco7
kHdG7J+Gsud/WjrIOGIy0PvRSw+PnSF8ZnMwmZHZNwDuvYLkfgb7H1U5YqY0ktAO
koaNrNGWbi8NPWUgMqNNE1XPY5vGpn5mJaBiYJjE9wg8Kq0Tdpg4jE08ZpqEne1a
eVmse9WasH3Ru/20kCkN+9nYixp11q8hYmtv
-----END CERTIFICATE-----
"""

client_key = b"""-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAydTcvd4d37FaFbWGYkEMgSiD/vroUf+nHRWQUCLO2R8Yrf66
PhmC+9cEWlmXwOLcayHgVKjGID7Ue6ffUUwhOo9oWjMiohdwaHlk6p1PpEeu5P0A
Xzey6YxkVRFRq6/hu2rs2YWMm3KyN8wYwv5boIbOlpKa2ifH3LuwJzI8e72tG3DK
i8vG7cuEC4pR7lF2IFyYIDd/l5KKBL5VVVyBARs/h+H6T2d2h9WZweRFmW6GUeKB
x2OqHXIrBrRsz1pHcGaaabeN3DMQq9kmKhkjiw9BzcMrG8n1yfnJ4SIb/KeFPxdr
vmXHAJtNhiHr1sQS8GsxKB0J/lT4ZpxEAC5JmQIDAQABAoIBAGKLw2gVTqLNFn4p
Dr9koXVi0egqnEqFOBRUVg06oaKTs1opWMg/bpwGZUK0Igt0+Uh51u2fJnXSF690
zO4F7OeJ49q+wvc/2Iu6UhLX0m4U7gkymv7i1EGCYe7DMQxSKTZ4Q8MFmRzBSNFD
nwd+aECd8brFRESmTcix/5VzyuJjYUtv6hju4TPzFJM1YAMizwRxFOqv6k7tdzUu
MQENp9U5ciXd5YmNZdYNpOUjLJ71huZp/7aE7xsF3HrqLXNDNfD/3UqTl93+V/vO
oPcWsIsc+hN8qEjNcXcM0Ck7fmTBuDpMKBiTL/AbMun5AKxJS8EPBVvHqqoCqw9s
/oeUkfECgYEA6yc38aHui4sVOCX1/ZoM7FmlrWQaygiVvBtUG3GXLfrau3mKtrY9
9HviO1x48frcCGbLT005q6P3Nido1gLlYV0rvF2SgoAgm6Ip0hLdKyl9c2T1DqEh
+rnmy5FO9nn3dlJ+UmG5nbnLer6rZi3GyNZGC3gG8jZJXNaueh9bnsUCgYEA27lp
Gb2jlMH8HEbpLaTU6NNAB8UCgBwxmM8XRy8m4VmOb2/W7cao+xpUzd+XK4FOXvEb
jF0mY5DnwYMu4Zj0KDYlBDBpJ6r4CFRIRWWE+8RN8lfCO5KKAneSOkoRP1lr6YwC
CQL6vE+UOKk06jaDmvc/8+VYAN8NKL3r/zQKbMUCgYBhDtzuZPH6srtdY3224OC4
pP/XI1xTS1vSOk1qzmWh2spxWudAJtRHluJ3seFRr0MmTJdZ8fv9tj2RIo8I1kUq
/LPSmaShLJVI55PvW03iRMu810y2bxeBTz3Ng/pdjVXwhngRNLjSOx+bWBuSnw5P
UvGyRiZHztRU918olMzSKQKBgCgEfL/TaheNvPzpbU6C1sQQtXi0yN/MQrwx+2tb
ixk/1lE1bU+g/uW8xfU4469ovX1NLFdEH9nCanM0ETXFRbKNKfC5YG15FfNuZjs9
Yhr4hbm9ggKXjcslO9yh4MJI5v6CIVzCzie91qD7MEf35cAzh9JD0uNVvG/PJ0wz
jjKBAoGBAIceghlIdYmtOC+Qd69hDfl1zFI5mOCEYexS4k8CZRIyhTkUQVYwGl9b
poVfVc7Ig9o3+OeRXQKEiHXIo3DuQcxR4xlIZWcR4G/xZoZ88LX4t/LXTQPm1Jd+
qSBN1kHWzsFhbECptW03cCE2sx5SO0WIF4omhMeagKnOvePGUqMd
-----END RSA PRIVATE KEY-----
"""

client_crt = b"""-----BEGIN CERTIFICATE-----
MIIDADCCAeigAwIBAgIBAjANBgkqhkiG9w0BAQsFADAVMRMwEQYDVQQDEwptaW5p
a3ViZUNBMB4XDTE5MDYyNTExNDQxN1oXDTIwMDYyNTExNDQxN1owMTEXMBUGA1UE
ChMOc3lzdGVtOm1hc3RlcnMxFjAUBgNVBAMTDW1pbmlrdWJlLXVzZXIwggEiMA0G
CSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDJ1Ny93h3fsVoVtYZiQQyBKIP++uhR
/6cdFZBQIs7ZHxit/ro+GYL71wRaWZfA4txrIeBUqMYgPtR7p99RTCE6j2haMyKi
F3BoeWTqnU+kR67k/QBfN7LpjGRVEVGrr+G7auzZhYybcrI3zBjC/lughs6Wkpra
J8fcu7AnMjx7va0bcMqLy8bty4QLilHuUXYgXJggN3+XkooEvlVVXIEBGz+H4fpP
Z3aH1ZnB5EWZboZR4oHHY6odcisGtGzPWkdwZpppt43cMxCr2SYqGSOLD0HNwysb
yfXJ+cnhIhv8p4U/F2u+ZccAm02GIevWxBLwazEoHQn+VPhmnEQALkmZAgMBAAGj
PzA9MA4GA1UdDwEB/wQEAwIFoDAdBgNVHSUEFjAUBggrBgEFBQcDAQYIKwYBBQUH
AwIwDAYDVR0TAQH/BAIwADANBgkqhkiG9w0BAQsFAAOCAQEAUxCWO5hgN7kcETHw
APN1zTe6jYxPza65b6Msc4Ips5+bASvkkOmPTtR8alQgs0ukP6bL2YuE+CnCccEA
amN1Al3eK/Wl271+G5MGIAkLklGSfMxlUKxvNnZowA8Kk+BQp2Jpw/fH5fscT9ML
0AYCdQpsKj27d5MB9TFfN7lx24JbPUZKbrGqzUZJcRvK0XXw4yUQj9XRQaBSogAU
HSZP1TWNvIis8iQs9Ym6nrvz1joqEbMEKkwZOpdIsIFxqMuIhf1qwHaAUqKyK53G
ouNnyuYzGEdVrp1s828cSB+8vCcYAzM1fyq+4xjWH59VMHClB00S10QximZW1dg5
twb31Q==
-----END CERTIFICATE-----
"""


local_kubeconfig = yaml.safe_load(
    f"""---
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: {b64encode(ca_cert).decode()}
    server: https://127.0.0.1:8080
  name: minikube
contexts:
- context:
    cluster: minikube
    user: minikube
  name: minikube
current-context: minikube
kind: Config
preferences:
users:
- name: minikube
  user:
    client-certificate-data: {b64encode(client_crt).decode()}
    client-key-data: {b64encode(client_key).decode()}
"""
)


def make_kubeconfig(server):
    return {
        "apiVersion": "v1",
        "clusters": [
            {
                "cluster": {"server": f"{server.scheme}://{server.host}:{server.port}"},
                "name": "test-cluster",
            }
        ],
        "contexts": [
            {
                "context": {"cluster": "test-cluster", "user": "test-user"},
                "name": "test-context",
            }
        ],
        "current-context": "test-context",
        "kind": "Config",
        "preferences": None,
        "users": [
            {
                "name": "test-user",
                "user": {"client-certificate-data": None, "client-key-data": None},
            }
        ],
    }


class ClusterSpecFactory(Factory):
    class Meta:
        model = ClusterSpec

    class Params:
        metric_count = 3

    @lazy_attribute
    def kubeconfig(self):
        return deepcopy(local_kubeconfig)

    @lazy_attribute
    def metrics(self):
        return [MetricRefFactory() for _ in range(self.metric_count)]

    @lazy_attribute
    def custom_resources(self):
        return [fuzzy_name() for _ in range(fake.pyint(1, 3))]


class ClusterNodeStatusFactory(Factory):
    class Meta:
        model = ClusterNodeStatus

    @lazy_attribute
    def conditions(self):
        return [
            ClusterNodeCondition(
                type="Ready",
                message="kubelet is posting ready status",
                reason="KubeletReady",
                status="True",
            ),
            ClusterNodeCondition(
                type="DiskPressure",
                message="kubelet has no disk pressure",
                reason="KubeletHasNoDiskPressure",
                status="False",
            ),
            ClusterNodeCondition(
                type="PIDPressure",
                message="kubelet has sufficient PID available",
                reason="KubeletHasSufficientPID",
                status="False",
            ),
            ClusterNodeCondition(
                type="MemoryPressure",
                message="kubelet has sufficient memory available",
                reason="KubeletHasSufficientMemory",
                status="False",
            ),
        ]


class ClusterNodeFactory(Factory):
    class Meta:
        model = ClusterNode

    status = SubFactory(ClusterNodeStatusFactory)


class ClusterStatusFactory(Factory):
    class Meta:
        model = ClusterStatus

    class Params:
        nodes_count = 3

    @lazy_attribute
    def metrics_reasons(self):
        return dict()

    @lazy_attribute
    def nodes(self):
        return [ClusterNodeFactory() for _ in range(self.nodes_count)]


class ClusterFactory(Factory):
    class Meta:
        model = Cluster

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(ClusterSpecFactory)
    status = SubFactory(ClusterStatusFactory)
