import asyncio
import os
import random
import signal
import sys
import subprocess
import urllib
from io import BytesIO
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import NamedTuple, List
import time
import logging.config
from textwrap import dedent
import json
from zipfile import ZipFile

import requests
import pytest
import aiohttp
import shutil

import werkzeug
import yaml
from aiohttp import web

from krake.controller import create_ssl_context
from prometheus_async import aio
from prometheus_client import Gauge, CollectorRegistry, CONTENT_TYPE_LATEST
from contextlib import suppress

# Prepend package directory for working imports
from krake.data.config import (
    ApiConfiguration,
    HooksConfiguration,
    MagnumConfiguration,
    TlsClientConfiguration,
    ControllerConfiguration,
    SchedulerConfiguration,
    KubernetesConfiguration,
)

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


@pytest.fixture(scope="session")
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


def base_config(user, etcd_host="localhost", etcd_port=2379):
    """Creates a configuration with some simple parameters, which have a default value
    that can be set.

    Args:
        user (str): the name of the user for the static authentication
        etcd_host (str): the host for the database.
        etcd_port (int): the port for the database.

    Returns:
        dict: the created configuration.

    """
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
                "keycloak": {
                    "enabled": False,
                    "endpoint": "no_endpoint",
                    "realm": "krake",
                },
                "static": {"enabled": True, "name": user},
            },
            "cors_origin": "http://example.com",
        },
        "authorization": "always-allow",
        "etcd": {"host": etcd_host, "port": etcd_port, "retry_transactions": 0},
        "docs": {"problem_base_url": "http://example.com/problem"},
        "log": {},
    }


@pytest.fixture
def config(etcd_server, user):
    """Generate a default configuration for the API, which leverages a test instance of
    etcd.

    Args:
        etcd_server ((str, int)): the information to connect to the etcd instance.
        user (str): the name of the user for the static authentication.

    Returns:
        ApiConfiguration: the generated configuration.

    """
    etcd_host, etcd_port = etcd_server
    config = base_config(user, etcd_host=etcd_host, etcd_port=etcd_port)
    return ApiConfiguration.deserialize(config, creation_ignored=True)


@pytest.fixture
def no_db_config(user):
    """Create a configuration for the API component without database being created and
    running in the background.

    Returns:
        ApiConfiguration: the generated configuration.

    """
    config = base_config(user)
    return ApiConfiguration.deserialize(config, creation_ignored=True)


@pytest.fixture
def log_to_file_config(tmp_path):
    """Returns a function that can generate a dictionary that can be used as
    configuration for the logging module. Such a dictionary is part of the Krake
    components configuration.
    The generated configuration sets the "INFO" log level, and only logs to a file. The
    path to the file can be provided. If not, a file is created by default in a
    temporary directory.

    FIXME: This should be removed when issue #282 has been closed.
    """
    base_file_path = str(tmp_path / "krake.log")

    def generate_log_config(file_path=None):
        """Generate the actual dictionary for logging.

        Args:
            file_path (str): path to the file to which the logs will be written. If not
                specified, a temporary file is used by default.

        Returns:
            (dict[str, Any], str): a tuple that contains first the generated dictionary,
                and second the path to the file where the logs will be written.

        """
        final_file_path = base_file_path
        if file_path is not None:
            final_file_path = file_path

        log_format = "%(asctime)s - [%(name)s] - [%(levelname)-5s] - %(message)s"
        return (
            {
                "version": 1,
                "level": "INFO",
                "formatters": {"krake": {"format": log_format}},
                "handlers": {
                    "file": {
                        "class": "logging.FileHandler",
                        "formatter": "krake",
                        "filename": final_file_path,
                    }
                },
                "loggers": {"krake": {"handlers": ["file"], "propagate": False}},
            },
            final_file_path,
        )

    return generate_log_config


@pytest.fixture
def tls_client_config():
    """Create a configuration for the "tls" field in the controllers configuration.

    Returns:
        TlsClientConfiguration: the created configuration.

    """
    config = {
        "enabled": False,
        "client_cert": "cert_path",
        "client_key": "key_path",
        "client_ca": "client_ca_path",
    }
    return TlsClientConfiguration.deserialize(config, creation_ignored=True)


@pytest.fixture
def gc_config(tls_client_config):
    """Create a configuration for the Garbage Collector.

    Returns:
        ControllerConfiguration: the created configuration.

    """

    config = {"tls": tls_client_config.serialize(), "log": {}}
    return ControllerConfiguration.deserialize(config, creation_ignored=True)


@pytest.fixture
def kube_config(tls_client_config):
    """Create a configuration for the Kubernetes Controller.

    Returns:
        KubernetesConfiguration: the created configuration.

    """

    config = {
        "tls": tls_client_config.serialize(),
        "hooks": {
            "complete": {
                "intermediate_src": "/etc/krake/certs/kube.pem",
                "intermediate_key_src": "/etc/krake/certs/kube-key.pem",
            },
            "shutdown": {
                "intermediate_src": "/etc/krake/certs/kube.pem",
                "intermediate_key_src": "/etc/krake/certs/kube-key.pem",
            },
        },
        "log": {},
    }
    return KubernetesConfiguration.deserialize(config, creation_ignored=True)


@pytest.fixture
def magnum_config(tls_client_config):
    """Create a configuration for the Magnum Controller.

    Returns:
        MagnumConfiguration: the created configuration.

    """

    config = {"tls": tls_client_config.serialize(), "log": {}}
    return MagnumConfiguration.deserialize(config, creation_ignored=True)


@pytest.fixture
def scheduler_config(tls_client_config):
    """Create a configuration for the Scheduler.

    Returns:
        SchedulerConfiguration: the created configuration.

    """

    config = {"tls": tls_client_config.serialize(), "log": {}}
    return SchedulerConfiguration.deserialize(config, creation_ignored=True)


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


@pytest.fixture(scope="session")
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
                wait_for_url(f"http://{host}:{port}/v3", timeout=30)
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
                    timeout=90,
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

    def rbac_creator(api, resource, verb, namespace="testing", override_user=None):
        """Add a role and role binding for the provided resource in the given namespace.
        This can then be leveraged to test the RBAC mechanism.

        Args:
            api (str): name of the API of the resource for which a role has to be given
                permission:
            resource (str): name of the resource's kind for which a role has to be given
                permission:
            verb (str, Verb): verb or name of the verb that corresponds to the action
                which should be allowed on the resource.
            namespace (str): namespace where the action is allowed.
            override_user (str): if provided, change the user for which the permission
                is added. Otherwise, use the tests default.

        Returns:
            RecordsContext: context manager in which the permission is added.

        """
        role_user = user
        if override_user:
            role_user = override_user

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
        binding = RoleBindingFactory(users=[role_user], roles=[role.metadata.name])

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

    Three types of certificates can be created:

     * a CA is always created;
     * an intermediate certificate can be created, which cannot be used for client
       authentication (cfssl "intermediate-ca" profile) OR;
     * a certificate ready for client authentication (cfssl "krake-test-ca" profile).

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
                },
                "intermediate-ca": {
                    "usages": [
                        "signing",
                        "key encipherment",
                        "server auth",
                        "client auth",
                        "cert sign",
                        "crl sign",
                    ],
                    "ca_constraint": {"is_ca": True, "max_path_len": 1},
                    "expiry": "8760h",
                },
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

    def gencert(self, name, is_intermediate=False):
        """Generate client certificate signed by the CA managed by this repository.

        Args:
            name (str): Common name of the certificate
            is_intermediate (bool): if True, the certificate will be able to sign other
                certificates, but cannot be used for client authentication.

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

        profile = "krake-test-ca"
        if is_intermediate:
            profile = "intermediate-ca"

        if not client_key_file.exists():
            with client_csr_file.open("w") as fd:
                json.dump(client_csr, fd, indent=4)

            certs = self.cfssl(
                "gencert",
                "-profile",
                profile,
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


@pytest.fixture(scope="session")
def pki():
    """Public key infrastructure fixture"""
    if not shutil.which("cfssl"):
        pytest.skip("Executable 'cfssl' not found")

    with PublicKeyRepository() as repo:
        yield repo


@pytest.fixture
def client_ssl_context(pki):
    """Create a decorator to create an SSL context to be used by a
    :class:`krake.client.Client`. It accepts a user as parameter for the certificate CN.

    Args:
        pki (PublicKeyRepository): the SSL components generated by the pki fixture.

    Returns:
        function: the generated decorator, which depends on the user provided.

    """

    def create_client_ssl_context(user):
        """Generate an SSL context, with the CA, the certificate and key. The
        certificate's CN has the provided user.

        Args:
            user (str): the CN for which the certificate should be generated.

        Returns:
            ssl.SSLContext: the created SSL context.

        """
        client_cert = pki.gencert(user)
        client_tls = TlsClientConfiguration(
            enabled=True,
            client_ca=pki.ca.cert,
            client_cert=client_cert.cert,
            client_key=client_cert.key,
        )
        return create_ssl_context(client_tls)

    return create_client_ssl_context


@pytest.fixture
def hooks_config(pki):
    """Generate the configuration for using the hooks of the KubernetesController.

    Args:
        pki (PublicKeyRepository): Already-prepared certificate environment.

    Returns:
        HooksConfiguration: the generated configuration.

    """
    client_complete_cert = pki.gencert(
        "test-complete-hook-signing", is_intermediate=True
    )
    client_shutdown_cert = pki.gencert(
        "test-shutdown-hook-signing", is_intermediate=True
    )
    return deepcopy(
        HooksConfiguration.deserialize(
            {
                "complete": {
                    "hook_user": "test-complete-hook-user",
                    "intermediate_src": client_complete_cert.cert,
                    "intermediate_key_src": client_complete_cert.key,
                    "cert_dest": "/etc/krake_complete_certs",
                    "env_token": "KRAKE_COMPLETE_TOKEN",
                    "env_url": "KRAKE_COMPLETE_URL",
                },
                "shutdown": {
                    "hook_user": "test-shutdown-hook-user",
                    "intermediate_src": client_shutdown_cert.cert,
                    "intermediate_key_src": client_shutdown_cert.key,
                    "cert_dest": "/etc/krake_shutdown_certs",
                    "env_token": "KRAKE_SHUTDOWN_TOKEN",
                    "env_url": "KRAKE_SHUTDOWN_URL",
                },
            }
        )
    )


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


def write_properties(properties, file_path):
    """Create a file with the provided parameters: each key-value pair is written as:
    "<key>=<value>", one line per key.

    Args:
        properties (dict[str, Any]): dictionary that contains the parameters to write.
        file_path (pathlib.Path): name of the file in which the properties will be
            written.
    """
    with open(file_path, "w") as f:
        for key, value in properties.items():
            f.write(f"{key}={value}\n")


class Zookeeper(NamedTuple):
    """Contains the information to connect to a Zookeeper instance.

    Attributes:
        host (str): host of the Zookeeper instance.
        port (int): port of the Zookeeper instance.

    """

    host: str
    port: int


async def write_command_to_port(loop, host, port, command=b"dump"):
    """Send a byte string to a specific port on the provided host. Read the complete
    output and return it.

    Args:
        loop (asyncio.AbstractEventLoop): the current loop.
        host (str): the host to which the command should be sent.
        port (int): the port on which the command should be sent.
        command (bytes): the command to send.

    Returns:
        bytes: the output read from the host.

    """
    # If the process that listens at the endpoint is not ready, the socket connector
    # raises an OSError.
    # FIXME: the OSError may be changed with another error, for instance
    #  ConnectionRefusedError. This works locally but not on the pipeline.
    with suppress(OSError):
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(command)
        data = await reader.read(512)
        writer.close()
        return data


@pytest.fixture
async def zookeeper(tmp_path, loop):
    if not shutil.which("zookeeper-server-start"):
        pytest.skip("Executable 'zookeeper-server-start' not found")

    zookeeper_port = 30007
    properties = {
        "4lw.commands.whitelist": "*",  # Allows sending all commands to Zookeeper
        "admin.enableServer": False,
        "clientPort": zookeeper_port,
        "dataDir": tmp_path,
        "maxClientCnxns": 0,
    }
    properties_path = tmp_path / "zookeeper.properties"
    write_properties(properties, properties_path)

    command = ["zookeeper-server-start", properties_path]

    with subprocess.Popen(command) as zookeeper:
        try:
            timeout = 10
            start = loop.time()
            # Wait for the Zookeeper instance to be ready.
            while True:
                data = await write_command_to_port(loop, "localhost", zookeeper_port)
                if data:
                    break

                if loop.time() - start > timeout:
                    raise TimeoutError("The instance was not ready before the timeout")
                await asyncio.sleep(0.25)

            yield Zookeeper(host="localhost", port=zookeeper_port)
        finally:
            zookeeper.terminate()


class Kafka(NamedTuple):
    """Contains the information to connect to a Kafka instance.

    Attributes:
        host (str): host of the Kafka instance.
        port (int): port of the Kafka instance.

    """

    host: str
    port: int


@pytest.fixture
async def kafka(zookeeper, tmp_path, loop):
    if not shutil.which("kafka-server-start"):
        pytest.skip("Executable 'kafka-server-start' not found")

    broker_id = 42
    kafka_host = "localhost"
    kafka_port = 31007
    properties = {
        "auto.create.topics.enable": True,
        "broker.id": broker_id,
        "delete.topic.enable": True,
        "listeners": f"PLAINTEXT://{kafka_host}:{kafka_port}",
        "log.cleaner.enable": True,
        "log.dirs": tmp_path,
        "offsets.topic.replication.factor": 1,  # Allows having only one broker
        "transaction.state.log.replication.factor": 1,  # Allows having only one broker
        "transaction.state.log.min.isr": 1,  # Allows having only one broker
        "zookeeper.connect": f"{zookeeper.host}:{zookeeper.port}",
        "zookeeper.connection.timeout.ms": 6000,
    }
    properties_path = tmp_path / "kafka.properties"
    write_properties(properties, properties_path)

    command = ["kafka-server-start", properties_path]

    with subprocess.Popen(command) as kafka:
        try:
            timeout = 20
            start = loop.time()
            # Wait for the Kafka instance to be ready.
            while True:
                dump_return = await write_command_to_port(
                    loop, zookeeper.host, zookeeper.port
                )

                # If the ID appears in the list of broker IDs in the Zookeeper status,
                # it means the broker is ready.
                if f"/brokers/ids/{broker_id}".encode() in dump_return:
                    break

                if loop.time() - start > timeout:
                    raise TimeoutError("The instance was not ready before the timeout")

                await asyncio.sleep(1)

            yield Kafka(host=kafka_host, port=kafka_port)
        finally:
            kafka.terminate()


class KsqlMetric(NamedTuple):
    """Entry in a KSQL table, where each row corresponds to a metric and its value. The
    value can be updated any time by a new input from Kafka.

    Attributes:
        name (str): name attribute of an entry in the KSQL database.
        value (int): value attribute of an entry in the KSQL database.

    """

    name: str
    value: int


class KafkaTable(NamedTuple):
    """Data about a KSQL table that contains the value of different metrics, one per
    row.

    Attributes:
        metrics (list[KsqlMetric]): definitions of the metrics inserted into the
            database.
        comparison_column (str): name of the KSQL column which contains the metrics
            names, and thus whose content is compared to the name of the chosen metric.
        value_column (str): name of the KSQL column which contains the current value of
            all metrics.
        table (str): name of the table in which the metrics have been added (so this
            table has at least two columns, namely "<comparison_column>" and
            "<value_column>").

    """

    metrics: List[KsqlMetric]
    comparison_column: str
    value_column: str
    table: str


class KsqlServer(NamedTuple):
    """Contains the information to connect to a KSQL database.

    Attributes:
        host (str): host of the KSQL database.
        port (int): port of the KSQL database.
        kafka_table (KafkaTable): information regarding the KSQL table present in the
            KSQL database.
        scheme (str): scheme to connect to the KSQL database.

    """

    host: str
    port: int
    kafka_table: KafkaTable
    scheme: str = "http"


async def send_command(client, url, command):
    """Send a KSQL command to the provided URL.

    Args:
        client (aiohttp.ClientSession): client to use for sending the command.
        url (str): URL to which the command should be sent.
        command (dict): command to send to the KSQL database.

    """
    resp = await client.post(url + "/ksql", json=command)
    assert resp.status == 200, f"The following command failed: {command!r}"


async def insert_entries(url):
    """Prepare a KSQL database by adding a stream, a table constructed from the stream,
    and by sending some elements to the stream. The stream has two columns: the metric
    name, and the number of time it appeared in the stream.

    Args:
        url (str): URL of the KSQL database.

    Returns:
        KafkaTable: necessary information regarding all elements inserted in the
            database.

    """
    value_column = "num_write"
    comparison_column = "zone"
    table = "heat_demand_zones_metrics"
    metrics = [
        KsqlMetric(name="heat_demand_1", value=2),  # Because it is inserted twice.
        KsqlMetric(name="heat_demand_2", value=1),
    ]

    base_command = {"ksql": None, "streamsProperties": {}}
    build_commands = [
        (
            "CREATE STREAM heat_demand_zones"
            f" ({comparison_column} STRING KEY, value INTEGER) WITH"
            " (kafka_topic='heat_demand_zones', value_format='json', partitions=1);"
        ),
        (
            f"CREATE TABLE {table} AS SELECT {comparison_column}, COUNT(*)"
            f" AS {value_column}"
            f" FROM heat_demand_zones GROUP BY {comparison_column} EMIT CHANGES;"
        ),  # Table from the stream, counts the number of inserted entries for each zone
    ]

    insert_commands = [
        (
            f"INSERT INTO heat_demand_zones ({comparison_column}, value) VALUES"
            f" ('{metrics[0].name}', 84);"
        ),
        (
            f"INSERT INTO heat_demand_zones ({comparison_column}, value) VALUES"
            f" ('{metrics[1].name}', 23);"
        ),
        (
            f"INSERT INTO heat_demand_zones ({comparison_column}, value) VALUES"
            f" ('{metrics[0].name}', 17);"
        ),
    ]
    async with aiohttp.ClientSession() as client:
        for command in build_commands:
            base_command["ksql"] = command
            await send_command(client, url, base_command)

        # Between the creation of the stream/table and the insertion of entries, some
        # time is necessary.
        await asyncio.sleep(15)

        for command in insert_commands:
            base_command["ksql"] = command
            await send_command(client, url, base_command)

    return KafkaTable(
        metrics=metrics,
        comparison_column=comparison_column,
        value_column=value_column,
        table=table,
    )


@pytest.fixture
async def ksql(kafka, tmp_path, loop):
    """Start a KSQL database. Insert some dummy metrics inside. The state of the
    database at the end of this fixture is the following:

     * a stream called "heat_demand_zones", with the following attributes:
         * zone (as string): the name of the zone;
         * value (as integer): an arbitrary value;
     * a table created from the stream, it has the following attributes:
         * zone (as string): same as for the stream;
         * num_write (as integer): the amount of time an entry was added for the current
           zone.
     * Three entries added to the stream:
         * two for the zone "heat_demand_1";
         * one for the zone "heat_demand_2".

    """

    if not shutil.which("ksql-server-start"):
        pytest.skip("Executable 'ksql-server-start' not found")

    ksql_host = "0.0.0.0"
    ksql_port = 32007
    url = f"http://{ksql_host}:{ksql_port}"
    properties = {
        "listeners": url,
        "ksql.logging.processing.topic.auto.create": "true",
        "ksql.logging.processing.stream.auto.create": "true",
        "bootstrap.servers": f"{kafka.host}:{kafka.port}",
        "compression.type": "snappy",
        "ksql.streams.state.dir": tmp_path,
    }
    properties_path = tmp_path / "ksql-server.properties"
    write_properties(properties, properties_path)

    command = ["ksql-server-start", properties_path]

    with subprocess.Popen(command) as ksql:
        try:
            timeout = 60
            start = loop.time()
            # Wait for the KSQL instance to be ready.
            while True:
                resp = None
                async with aiohttp.ClientSession() as client:
                    try:
                        resp = await client.get(url + "/info")
                    except aiohttp.ClientConnectorError:
                        pass

                if resp and resp.status == 200:
                    break
                if loop.time() - start > timeout:
                    raise TimeoutError("The instance was not ready before the timeout")

                await asyncio.sleep(1)

            kafka_table = await insert_entries(url)
            yield KsqlServer(host=ksql_host, port=ksql_port, kafka_table=kafka_table)
        finally:
            ksql.terminate()


@pytest.fixture
def file_server(httpserver):
    """Start http server with endpoint to get the given file.

    Given file could be a `dict` or a regular file.

    Example:
        .. code:: python

            import requests

            def test_get_file(file_server):
                file_url = file_server({"foo": "bar"})
                resp = requests.get(file_url)
                assert resp.json() == {"foo": "bar"}

    """

    def serve_file(file, file_name="example.yaml"):
        def handler(request):
            """Return a web response with the file content."""
            if isinstance(file, dict):
                return werkzeug.Response(json.dumps(file).encode())
            else:
                return werkzeug.Response(open(file, "rb"))

        httpserver.expect_request(f"/{file_name}").respond_with_handler(handler)

        return httpserver.url_for(f"/{file_name}")

    return serve_file


@pytest.fixture
def archive_files(tmp_path):
    """Archive given files to the ZIP archive.

    Files should be given in format:
        [(<file_name>, <file_content>)]

    File content could be given as a `dict` or as a regular file.

    Example:
        .. code:: python

            import zipfile
            import yaml

            def test_archive_file(archive_files, tmp_path):
                archive_path = archive_files([("example.yaml", {"foo": "bar"})])

                extracted = tmp_path / "extracted"
                with zipfile.ZipFile(archive_path) as zip_fd:
                    zip_fd.extractall(extracted)

                with open(extracted / "example.yaml") as fd:
                    assert yaml.safe_load(fd) == {"foo": "bar"}

    """

    def create_archive(files, archive_name="example.zip"):
        archive_path = tmp_path / archive_name
        for name, path_content in files:
            file_path = None
            try:
                if os.path.exists(path_content):
                    file_path = path_content
            except TypeError:
                pass

            if not file_path:
                if isinstance(path_content, dict):
                    file_path = tmp_path / name
                    # ensure that parents exist
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "w") as yaml_fd:
                        yaml.safe_dump(path_content, yaml_fd)

                elif isinstance(path_content, str):
                    file_path = tmp_path / name
                    # ensure that parents exist
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "w") as str_fd:
                        str_fd.write(path_content)

                else:
                    raise ValueError(f"Given {path_content} could not be archived.")

            with ZipFile(archive_path, "a") as archive_fd:
                archive_fd.write(file_path, name)

        return archive_path

    return create_archive
