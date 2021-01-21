import asyncio
import os
import random
import signal
import sys
import subprocess
import urllib
from io import BytesIO
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import NamedTuple
import time
import logging.config
from textwrap import dedent
import json
from zipfile import ZipFile

import requests
import pytest
import aiohttp
import shutil
from aiohttp import web
from prometheus_async import aio
from prometheus_client import Gauge, CollectorRegistry, CONTENT_TYPE_LATEST
from contextlib import suppress

# Prepend package directory for working imports
from krake.data.config import ApiConfiguration

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
        "markers", "timeout(time): mark async test with maximal duration"
    )


def pytest_collection_modifyitems(config, items):
    """Called after pytest collection has been performed, may filter or
    re-order the items in-place.

    Args:
        config (pytest.config.Config): config object
        items (List[pytest.nodes.Item]): list of test item objects

    """
    if not config.getoption("--runslow"):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


def wait_for_url(url, timeout=5, condition=None):
    """Wait until an URL endpoint is reachable.

    The ``condition`` callable takes the HTTP response as argument and checks if it
    suits a certain format.

    The signature of ``condition`` is:

    .. function:: my_condition(response)

        :param requests.Response response: the Response object of the HTTP request
        :return: true if the condition is met
        :rtype: bool

    Args:
        url (str): URL endpoint
        timeout (int, optional): Timeout. Defaults to 5s
        condition (callable, optional): Condition that has to be met.

    Raises:
        TimeoutError: When timeout is reached

    """
    start = time.time()

    while True:
        try:
            resp = requests.get(url)
            assert resp.status_code == 200
            if condition:
                assert condition(resp)
        except (requests.ConnectionError, AssertionError):
            time.sleep(0.1)
            if time.time() - start > timeout:
                raise TimeoutError(f"Cannot connect to {url}")
        else:
            return


async def await_for_url(url, loop, timeout=5):
    start = loop.time()

    while True:
        try:
            async with aiohttp.ClientSession(raise_for_status=True) as client:
                resp = await client.get(url)
        except aiohttp.ClientError:
            await asyncio.sleep(0.1)
            if loop.time() - start > timeout:
                raise TimeoutError(f"Cannot connect to {url!r}")
        else:
            return resp


@pytest.fixture("session")
def etcd_server():
    def check_etcd_health(response):
        with suppress(json.decoder.JSONDecodeError):
            jresp = response.json()
            with suppress(KeyError):
                return jresp["health"] == "true"
        return False

    etcd_host = "127.0.0.1"
    etcd_port = 3379

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
                wait_for_url(
                    f"http://{etcd_host}:{etcd_port}/health",
                    condition=check_etcd_health,
                )
                yield etcd_host, etcd_port
            finally:
                proc.terminate()


@pytest.fixture
async def etcd_client(etcd_server, loop):
    # Use the patched etcd3 client (see #293)
    from krake.api.database import EtcdClient

    host, port = etcd_server

    async with EtcdClient(host=host, port=port) as client:
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

    config = {
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
                "keycloak": {
                    "enabled": False,
                    "endpoint": "no_endpoint",
                    "realm": "krake",
                },
                "static": {"enabled": True, "name": user},
            },
        },
        "authorization": "always-allow",
        "etcd": {"host": etcd_host, "port": etcd_port, "retry_transactions": 0},
        "log": {},
    }
    return ApiConfiguration.deserialize(config, creation_ignored=True)


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
    pytest.importorskip("keystone")

    host = "localhost"
    port = 5050

    config_template = dedent(
        """
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
    )

    with TemporaryDirectory() as tempdir:
        config_file = Path(tempdir) / "keystone.conf"

        # Create keystone configuration
        with config_file.open("w") as fd:
            fd.write(config_template.format(tempdir=tempdir))

        (Path(tempdir) / "fernet-keys").mkdir(mode=0o700)
        (Path(tempdir) / "credential-keys").mkdir(mode=0o700)
        (Path(tempdir) / "logs").mkdir()

        user = os.getuid()
        group = os.getgid()

        # Populate identity service database
        subprocess.check_call(
            ["keystone-manage", "--config-file", str(config_file), "db_sync"]
        )
        # Initialize Fernet key repositories
        subprocess.check_call(
            [
                "keystone-manage",
                "--config-file",
                str(config_file),
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
                str(config_file),
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
                str(config_file),
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
            str(config_file),
        ]
        with subprocess.Popen(command) as proc:
            try:
                wait_for_url(f"http://{host}:{port}/v3", timeout=7)
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


class KeycloakInfo(NamedTuple):
    port: int
    realm: str
    client_id: str
    client_secret: str
    grant_type: str
    username: str
    password: str

    @property
    def auth_url(self):
        return f"http://localhost:{self.port}"


@pytest.fixture
def keycloak():
    """Fixture to create a Keycloak instance running in the background. The instance is
    stopped after a test that uses this fixture finished.

    Returns:
        KeycloakInfo: the different values needed to connect to the running instance.

    """
    version = "11.0.2"
    with TemporaryDirectory() as tempdir:

        url = urllib.request.urlopen(
            f"https://downloads.jboss.org/keycloak/{version}/keycloak-{version}.zip"
        )

        # Download Keycloak's zip and directly unzip the downloaded file.
        # See https://stackoverflow.com/questions/42326428/zipfile-in-python-file-permission  # noqa
        zip_unix_system = 3
        with ZipFile(BytesIO(url.read())) as zf:
            for info in zf.infolist():
                extracted_path = zf.extract(info, tempdir)

                if info.create_system == zip_unix_system:
                    unix_attributes = info.external_attr >> 16
                    if unix_attributes:
                        os.chmod(extracted_path, unix_attributes)

        keycloak_dir = Path(tempdir) / f"keycloak-{version}"
        subprocess.check_call(
            [
                "support/keycloak",
                "--temp-dir",
                tempdir,
                "init",
                "--keycloak-dir",
                keycloak_dir,
            ]
        )

        process = subprocess.Popen(
            ["support/keycloak", "--temp-dir", tempdir, "credentials"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, _ = process.communicate()
        keycloak_cred = json.loads(out)

        info = KeycloakInfo(**keycloak_cred)

        with subprocess.Popen(
            f"support/keycloak --temp-dir {tempdir}", shell=True, preexec_fn=os.setsid
        ) as proc:
            try:
                wait_for_url(
                    f"http://localhost:{info.port}/auth/realms/{info.realm}/",
                    timeout=60,
                )
                yield info
            except TimeoutError:
                print("The URL could not be reached before the timeout.")
            finally:
                pid = proc.pid
                time.sleep(1)
                proc.terminate()
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                time.sleep(1)


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
    from tests.factories.core import RoleFactory, RoleBindingFactory
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
    if not shutil.which("cfssl"):
        pytest.skip("Executable 'cfssl' not found")

    with PublicKeyRepository() as repo:
        yield repo


class PrometheusExporter(NamedTuple):
    """Tuple yielded by the :func:`prometheus_exporter` fixture describing
    server connection information and the name of the provided metric.
    """

    host: str
    port: int
    metric: str


@pytest.fixture
async def prometheus_exporter(loop, aiohttp_server):
    """Heat-demand exporter fixture. Heat demand exporter generates heat
    demand metric `heat_demand_zone_1` with random value.
    """
    metric_name = "heat_demand_zone_1"
    interval = 1  # refresh metric value interval[s]

    registry = CollectorRegistry(auto_describe=True)

    async def heat_demand_metric():
        metric = Gauge(metric_name, "float - heat demand (kW)", registry=registry)
        while True:
            metric.set(round(random.random(), 2))
            await asyncio.sleep(interval)

    async def start_metric(app):
        app["metric"] = loop.create_task(heat_demand_metric())

    async def cleanup_metric(app):
        app["metric"].cancel()
        try:
            await app["metric"]
        except asyncio.CancelledError:
            pass

    async def server_stats(request):
        """Return a web response with the plain text version of the metrics."""
        resp = web.Response(body=aio.web.generate_latest(registry))

        # This is set separately because aiohttp complains about ";"" in
        # content_type thinking it means there's also a charset.
        # @see https://github.com/aio-libs/aiohttp/issues/2197
        resp.content_type = CONTENT_TYPE_LATEST

        return resp

    app = web.Application()
    app.router.add_get("/metrics", server_stats)
    app.on_startup.append(start_metric)
    app.on_cleanup.append(cleanup_metric)

    server = await aiohttp_server(app)

    yield PrometheusExporter(host=server.host, port=server.port, metric=metric_name)


class Prometheus(NamedTuple):
    """Tuple yielded by the :func:`prometheus` fixture. It contains
    information about the Prometheus server connection.
    """

    scheme: str
    host: str
    port: int
    exporter: PrometheusExporter


@pytest.fixture
async def prometheus(prometheus_exporter, loop):
    prometheus_host = "localhost"
    prometheus_port = 5055

    if not shutil.which("prometheus"):
        pytest.skip("Executable 'prometheus' not found")

    config = dedent(
        """
        global:
            scrape_interval: 1s
        scrape_configs:
            - job_name: prometheus
              static_configs:
                - targets:
                  - {prometheus_host}:{prometheus_port}
            - job_name: heat-demand-exporter
              static_configs:
                - targets:
                  - {exporter_host}:{exporter_port}
        """
    )

    async def await_for_prometheus(url, timeout=10):
        """Wait until the Prometheus server is booted up and the first metric
        is scraped.
        """
        start = loop.time()

        while True:
            resp = await await_for_url(url, loop)
            body = await resp.json()

            # If the returned metric list is not empty, stop waiting.
            if body["data"]["result"]:
                return

            if loop.time() - start > timeout:
                raise TimeoutError(f"Cannot get metric from {url!r}")

            # Prometheus' first scrap takes some time
            await asyncio.sleep(0.25)

    with TemporaryDirectory() as tempdir:
        config_file = Path(tempdir) / "prometheus.yml"

        # Create prometheus configuration
        with config_file.open("w") as fd:
            fd.write(
                config.format(
                    prometheus_host=prometheus_host,
                    prometheus_port=prometheus_port,
                    exporter_host=prometheus_exporter.host,
                    exporter_port=prometheus_exporter.port,
                )
            )

        command = [
            "prometheus",
            "--config.file",
            str(config_file),
            "--storage.tsdb.path",
            str(Path(tempdir) / "data"),
            "--web.enable-admin-api",
            "--web.listen-address",
            ":" + str(prometheus_port),
        ]
        with subprocess.Popen(command) as prometheus:
            try:
                await await_for_prometheus(
                    f"http://{prometheus_host}:{prometheus_port}"
                    f"/api/v1/query?query={prometheus_exporter.metric}"
                )
                yield Prometheus(
                    scheme="http",
                    host=prometheus_host,
                    port=prometheus_port,
                    exporter=prometheus_exporter,
                )
            finally:
                prometheus.terminate()
