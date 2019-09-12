import os
import random
import sys
import subprocess
import threading
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import NamedTuple
import time
import logging.config
from importlib import import_module
import json
import shutil
import requests
import pytest
from etcd3.aio_client import AioClient
from prometheus_client import Gauge, start_http_server

# Prepend package directory for working imports
package_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, package_dir)


logging.config.dictConfig(
    {
        "version": 1,
        "handlers": {"console": {"class": "logging.StreamHandler", "level": "DEBUG"}},
        "loggers": {"krake": {"handlers": ["console"]}},
    }
)


def pytest_addoption(parser):
    """Register :mod:`argparse`-style options and ini-style config values for pytest.

    Called once at the beginning of a test run.

    Args:
        parser (pytest.config.Parser): pytest parser

    """
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_configure(config):
    """Allows plugins and conftest files to perform initial configuration.

    Args:
        config (pytest.config.Config): config object

    """
    config.addinivalue_line("markers", "slow: mark test as slow to run")
    config.addinivalue_line(
        "markers", "require_module(name): skip test if module is not installed"
    )
    config.addinivalue_line(
        "markers", "require_executable(name): skip test if executable is not found"
    )
    config.addinivalue_line(
        "markers", "timeout(time): mark async test with maximal duration"
    )


def pytest_collection_modifyitems(config, items):
    """Called after pytest collection has been performed, may filter or
    re-order the items in-place.

    Args:
        session (pytest.main.Session): pytest session
        config (pytest.config.Config): config object
        items (List[pytest.nodes.Item]): list of test item objects

    """
    if not config.getoption("--runslow"):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)

    for item in items:
        if "require_module" in item.keywords:
            marker = item.get_closest_marker("require_module")
            module = marker.args[0]
            try:
                import_module(module)
            except ImportError:
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"Required module {module!r} is not installed"
                    )
                )
        if "require_executable" in item.keywords:
            marker = item.get_closest_marker("require_executable")
            executable = marker.args[0]
            if not shutil.which(executable):
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"Required executable {executable!r} was not found"
                    )
                )


def wait_for_url(url, response_fn=None, timeout=5):
    """Wait until an URL endpoint is reachable.

    Args:
        url (str): URL endpoint
        response_fn (:func:, optional): Response callback function
        timeout (int, optional): Timeout. Defaults to 5s

    Raises:
        TimeoutError: When timeout is reached

    """
    start = time.time()

    while True:
        try:
            resp = requests.get(url)
            assert resp.status_code == 200
            if response_fn:
                assert response_fn(resp)
        except (requests.ConnectionError, AssertionError):
            time.sleep(0.1)
            if time.time() - start > timeout:
                raise TimeoutError(f"Can not connect to {url}")
        else:
            return


etcd_host = "127.0.0.1"
etcd_port = 3379


@pytest.fixture("session")
def etcd_server():
    with TemporaryDirectory() as tmpdir:
        command = [
            "etcd",
            "--data-dir",
            tmpdir,
            "--name",
            "krake-testing",
            "--listen-client-urls",
            f"http://{etcd_host}:{etcd_port}",
            "--advertise-client-urls",
            f"http://{etcd_host}:{etcd_port}",
            "--listen-peer-urls",
            f"http://{etcd_host}:{etcd_port + 1}",
            "--initial-advertise-peer-urls",
            f"http://{etcd_host}:{etcd_port + 1}",
        ]
        with subprocess.Popen(command) as proc:
            try:
                wait_for_url(f"http://{etcd_host}:{etcd_port}/version")
                yield etcd_host, etcd_port
            finally:
                time.sleep(1)
                proc.terminate()


@pytest.fixture
async def etcd_client(etcd_server, loop):
    host, port = etcd_server

    async with AioClient(host=host, port=port) as client:
        yield client
        await client.delete_range(all=True)


@pytest.fixture
async def db(etcd_server, etcd_client, loop):
    from krake.api.database import Session

    host, port = etcd_server

    async with Session(host=host, port=port, loop=loop) as session:
        yield session


@pytest.fixture
def user():
    return "testuser"


@pytest.fixture
def config(etcd_server, user):
    etcd_host, etcd_port = etcd_server

    return {
        "tls": {
            "enabled": False,
            "cert": "cert_path",
            "key": "key_path",
            "client_ca": "client_ca_path",
        },
        "authentication": {
            "allow_anonymous": True,
            "strategy": {
                "keystone": {"enabled": False, "endpoint": "http://localhost"},
                "static": {"enabled": True, "name": user},
            },
        },
        "authorization": "always-allow",
        "etcd": {"host": etcd_host, "port": etcd_port, "retry_transactions": 0},
        "default-roles": [
            {
                "metadata": {"name": "system:admin"},
                "rules": [
                    {
                        "api": "all",
                        "namespaces": ["all"],
                        "resources": ["all"],
                        "verbs": ["create", "list", "get", "update", "delete"],
                    }
                ],
            }
        ],
        "default-role-bindings": [
            {
                "metadata": {"name": "system:admin"},
                "users": ["system:admin"],
                "roles": ["system:admin"],
            }
        ],
        "default-metrics": [
            {
                "metadata": {"name": "heat_demand_zone_1"},
                "spec": {
                    "min": 0,
                    "max": 1,
                    "weight": 0.9,
                    "provider": {"name": "prometheus-zone-1", "metric": "heat-demand"},
                },
            }
        ],
        "default-metrics-providers": [
            {
                "metadata": {"name": "prometheus-zone-1"},
                "spec": {
                    "type": "prometheus",
                    "config": {
                        "url": "http://localhost:9090/api/v1/query",
                        "metrics": ["heat-demand"],
                    },
                },
            }
        ],
    }


keystone_config = """
[fernet_tokens]
key_repository = {tempdir}/fernet-keys

[fernet_receipts]
key_repository = {tempdir}/fernet-keys

[DEFAULT]
log_dir = {tempdir}/logs

[assignment]
driver = sql

[cache]
enabled = false

[catalog]
driver = sql

[policy]
driver = rules

[credential]
key_repository = {tempdir}/credential-keys

[token]
provider = fernet
expiration = 21600

[database]
connection = sqlite:///{tempdir}/keystone.db
"""


class KeystoneInfo(NamedTuple):
    host: str
    port: int

    username: str
    user_domain_name: str
    password: str
    project_name: str
    project_domain_name: str

    @property
    def auth_url(self):
        return f"http://{self.host}:{self.port}/v3"


@pytest.fixture("session")
def keystone():
    host = "localhost"
    port = 5050

    with TemporaryDirectory() as tempdir:
        config = Path(tempdir) / "keystone.conf"

        # Create keystone configuration
        with config.open("w") as fd:
            fd.write(keystone_config.format(tempdir=tempdir))

        (Path(tempdir) / "fernet-keys").mkdir(mode=0o700)
        (Path(tempdir) / "credential-keys").mkdir(mode=0o700)
        (Path(tempdir) / "logs").mkdir()

        user = os.getuid()
        group = os.getgid()

        # Populate identity service database
        subprocess.check_call(
            ["keystone-manage", "--config-file", str(config), "db_sync"]
        )
        # Initialize Fernet key repositories
        subprocess.check_call(
            [
                "keystone-manage",
                "--config-file",
                str(config),
                "fernet_setup",
                "--keystone-user",
                str(user),
                "--keystone-group",
                str(group),
            ]
        )
        subprocess.check_call(
            [
                "keystone-manage",
                "--config-file",
                str(config),
                "credential_setup",
                "--keystone-user",
                str(user),
                "--keystone-group",
                str(group),
            ]
        )
        # Bootstrap identity service
        subprocess.check_call(
            [
                "keystone-manage",
                "--config-file",
                str(config),
                "bootstrap",
                "--bootstrap-password",
                "admin",
                "--bootstrap-admin-url",
                f"http://{host}:{port}/v3/",
                "--bootstrap-internal-url",
                f"http://{host}:{port}/v3/",
                "--bootstrap-public-url",
                f"http://{host}:{port}/v3/",
                "--bootstrap-region-id",
                "DefaultRegion",
            ]
        )

        command = [
            "keystone-wsgi-public",
            "--host",
            host,
            "--port",
            str(port),
            "--",
            "--config-file",
            str(config),
        ]
        with subprocess.Popen(command) as proc:
            try:
                wait_for_url(f"http://{host}:{port}/v3")
                info = KeystoneInfo(
                    host=host,
                    port=port,
                    username="admin",
                    password="admin",
                    user_domain_name="Default",
                    project_name="admin",
                    project_domain_name="Default",
                )
                yield info
            finally:
                time.sleep(1)
                proc.terminate()


class RecordsContext(object):
    def __init__(self, db, records):
        self.db = db
        self.records = records

    async def __aenter__(self):
        for record in self.records:
            await self.db.put(record)
        return self.records

    async def __aexit__(self, *exc):
        for record in reversed(self.records):
            await self.db.delete(record)


@pytest.fixture
def rbac_allow(db, user):
    from factories.core import RoleFactory, RoleBindingFactory
    from krake.data.core import Verb, RoleRule

    def rbac_creator(api, resource, verb, namespace="testing"):
        if isinstance(verb, str):
            verb = Verb.__members__[verb]

        namespaces = []
        if namespace:
            namespaces.append(namespace)

        role = RoleFactory(
            rules=[
                RoleRule(
                    api=api, namespaces=namespaces, resources=[resource], verbs=[verb]
                )
            ]
        )
        binding = RoleBindingFactory(users=[user], roles=[role.metadata.name])

        return RecordsContext(db, [role, binding])

    return rbac_creator


class Certificate(NamedTuple):
    """Path to certificate issued by :class:`PublicKeyRepository` and its
    corresponding private key.
    """

    cert: str
    key: str


class PublicKeyRepository(object):
    """Pytest fixture for testing public key infrastructure.

    The repository uses the ``cfssl`` executable for creating and signing
    certificates.

    The repository must be used with the context protocol:

    .. code:: python

        with PublicKeyRepository() as pki:
            cert = pki.gencert("me")

    Attributes:
        ca (Certificate): Certificate Authority of this repository created by
            :meth:`genca`.

    """

    ca_csr = {
        "CN": "Krake CA",
        "key": {"algo": "ecdsa", "size": 256},
        "names": [{"O": "Acme Corporation"}],
    }

    ca_config = {
        "signing": {
            "profiles": {
                "krake-test-ca": {
                    "usages": [
                        "signing",
                        "key encipherment",
                        "server auth",
                        "client auth",
                    ],
                    "expiry": "8760h",
                }
            }
        }
    }

    client_csr = {
        "CN": None,
        "hosts": ["127.0.0.1"],
        "key": {"algo": "ecdsa", "size": 256},
        "names": [{"O": "Acme Corporation"}],
    }

    def __init__(self):
        self._tempdir = None
        self.clients = None
        self.ca = None
        self.ca_config_file = None

    def __enter__(self):
        self._tempdir = TemporaryDirectory(prefix="pki-")
        return self

    def __exit__(self, *exc):
        self._tempdir.cleanup()
        self.ca = None
        self.ca_config_file = None

    @property
    def tempdir(self):
        """Temporary directory holding all certificates, keys and config
        files. It is created when entering the context and removed on exit.
        """
        if self._tempdir is None:
            return None
        return Path(self._tempdir.name)

    def gencert(self, name):
        """Generate client certificate signed by the CA managed by this repository.

        Args:
            name (str): Common name of the certificate

        Returns:
            Certificate: Named tuple of paths to the certificate and
            corresponding private key.
        """
        if self.ca is None:
            self.genca()

        client_csr = dict(self.client_csr, CN=name)
        client_csr_file = self.tempdir / f"{name}-csr.json"

        client_cert_file = self.tempdir / f"{name}.pem"
        client_key_file = self.tempdir / f"{name}-key.pem"

        if not client_key_file.exists():
            with client_csr_file.open("w") as fd:
                json.dump(client_csr, fd, indent=4)

            certs = self.cfssl(
                "gencert",
                "-profile",
                "krake",
                "-config",
                str(self.ca_config_file),
                "-ca",
                self.ca.cert,
                "-ca-key",
                self.ca.key,
                str(client_csr_file),
            )

            with client_key_file.open("w") as fd:
                fd.write(certs["key"])
            client_key_file.chmod(0o600)

            with client_cert_file.open("w") as fd:
                fd.write(certs["cert"])

        return Certificate(cert=str(client_cert_file), key=str(client_key_file))

    def genca(self):
        """Initialize the CA certificate of the repository.

        This method is automatically called by :meth:`gencert` if :attr:`ca`
        is None.
        """
        ca_csr_file = self.tempdir / "ca-csr.json"
        ca_key_file = self.tempdir / "ca-key.pem"
        ca_cert_file = self.tempdir / "ca.pem"

        self.ca_config_file = self.tempdir / "ca-config.json"
        self.ca = Certificate(cert=str(ca_cert_file), key=str(ca_key_file))

        with ca_csr_file.open("w") as fd:
            json.dump(self.ca_csr, fd, indent=4)

        certs = self.cfssl("gencert", "-initca", str(ca_csr_file))

        with ca_key_file.open("w") as fd:
            fd.write(certs["key"])
        ca_key_file.chmod(0o600)

        with ca_cert_file.open("w") as fd:
            fd.write(certs["cert"])

        with open(self.ca_config_file, "w") as fd:
            json.dump(self.ca_config, fd, indent=4)

    @staticmethod
    def cfssl(*command):
        """Execute an ``cfssl`` command. The output is directly parsed as JSON
        and returned.

        Args:
            *command: command line arguments for ``cfssl``

        Returns:
            JSON output of the cfssl command

        """
        with subprocess.Popen(("cfssl",) + command, stdout=subprocess.PIPE) as proc:
            try:
                data = json.load(proc.stdout)
            except json.JSONDecodeError:
                returncode = proc.poll()
                if returncode is not None and returncode != 0:
                    raise subprocess.CalledProcessError(returncode, command)
                raise

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, command)

        return data


@pytest.fixture("session")
def pki():
    """Public key infrastructure fixture"""
    with PublicKeyRepository() as repo:
        yield repo


prometheus_config = """
global:
    scrape_interval: {interval}s
scrape_configs:
    - job_name: prometheus
      static_configs:
        - targets:
          - localhost:{prometheus_port}
    - job_name: heat-demand-exporter
      static_configs:
        - targets:
          - localhost:{exporter_port}
"""


class HeatDemandExporter(threading.Thread):
    def __init__(self, name, interval=1):
        threading.Thread.__init__(self)
        self.exporter_event = threading.Event()
        self.name = name
        self.interval = interval

    def run(self):
        metric = Gauge(self.name, "float - heat demand (kW)")
        while not self.exporter_event.isSet():
            metric.set(round(random.random(), 2))
            self.exporter_event.wait(self.interval)

    def join(self):
        self.exporter_event.set()


@pytest.fixture("session")
def prometheus():
    """Prometheus server and heat-demand exporter fixture

    Heat demand exporter generates random heat demand metric `heat_demand_zone_1`
    """
    host = "localhost"
    port = 5055
    interval = 1  # scrape interval[s]
    exporter_port = port + 1
    metric_name = "heat_demand_zone_1"

    def response_callback(resp):
        if resp:
            response = resp.json()
            for metric_data in response["data"]["result"]:
                if metric_data:
                    return True
        return False

    # Prometheus heat-demand exporter
    start_http_server(exporter_port)
    exporter = HeatDemandExporter(metric_name, interval=interval)
    exporter.start()

    with TemporaryDirectory() as tempdir:
        config_file = Path(tempdir) / "prometheus.yml"

        # Create prometheus configuration
        with config_file.open("w") as fd:
            fd.write(
                prometheus_config.format(
                    interval=interval, prometheus_port=port, exporter_port=exporter_port
                )
            )

        command = [
            "prometheus",
            "--config.file",
            str(config_file),
            "--web.enable-admin-api",
            "--web.listen-address",
            ":" + str(port),
        ]
        with subprocess.Popen(command) as proc:
            try:
                wait_for_url(
                    f"http://{host}:{port}/api/v1/query?query={metric_name}",
                    response_fn=response_callback,
                    timeout=10,
                )
                yield host, port
            finally:
                time.sleep(1)
                exporter.join()
                proc.terminate()
