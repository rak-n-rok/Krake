from base64 import b64encode
import yaml
from factory import Factory, SubFactory, lazy_attribute, fuzzy, List
from copy import deepcopy

from .fake import fake
from .core import MetadataFactory, ReasonFactory
from krake.data.core import ResourceRef
from krake.data.kubernetes import (
    ApplicationSpec,
    ApplicationStatus,
    ApplicationState,
    Application,
    ClusterSpec,
    ClusterState,
    ClusterStatus,
    Cluster,
    Constraints,
)


def fuzzy_name():
    return "-".join(fake.name().split()).lower()


def fuzzy_dict():
    return {fake.word(): fake.word()}


states = list(ApplicationState.__members__.values())
states.remove(ApplicationState.DELETED)


class ConstraintsFactory(Factory):
    class Meta:
        model = Constraints

    @lazy_attribute
    def labels(self):
        return [fuzzy_dict() for _ in range(3)]


class ApplicationStatusFactory(Factory):
    class Meta:
        model = ApplicationStatus

    state = fuzzy.FuzzyChoice(states)

    @lazy_attribute
    def reason(self):
        if self.state != ApplicationState.FAILED:
            return None
        return ReasonFactory()

    @lazy_attribute
    def cluster(self):
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
    def manifest(self):
        if self.state == ApplicationState.PENDING:
            return None

        if self.factory_parent:
            manifest = self.factory_parent.spec.manifest

            # Create a random sample of resources from the manifest
            k = fake.pyint(0, len(manifest))
            sample = fake.random.sample(manifest, k)

            return deepcopy(sample)
        return None


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
        return kubernetes_manifest

    constraints = SubFactory(ConstraintsFactory)


class ApplicationFactory(Factory):
    class Meta:
        model = Application

    metadata = SubFactory(MetadataFactory)
    spec = SubFactory(ApplicationSpecFactory)
    status = SubFactory(ApplicationStatusFactory)


class ClusterStatusFactory(Factory):
    class Meta:
        model = ClusterStatus

    state = fuzzy.FuzzyChoice(list(ClusterState.__members__.values()))

    @lazy_attribute
    def reason(self):
        if self.state != ApplicationState.FAILED:
            return None
        return ReasonFactory()


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

    @lazy_attribute
    def kubeconfig(self):
        return local_kubeconfig

    metrics = fuzzy.FuzzyAttribute(fake.words)


class ClusterFactory(Factory):
    class Meta:
        model = Cluster

    metadata = SubFactory(MetadataFactory)
    status = SubFactory(ClusterStatusFactory)
    spec = SubFactory(ClusterSpecFactory)
