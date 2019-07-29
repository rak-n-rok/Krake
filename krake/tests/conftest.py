import os
import sys
import subprocess
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import NamedTuple
import time
import logging.config
import requests
import pytest
from etcd3.aio_client import AioClient
from aresponses import ResponsesMockServer


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


def wait_for_url(url, timeout=5):
    """Wait until an URL endpoint is reachable"""
    start = time.time()

    while True:
        try:
            resp = requests.get(url)
            assert resp.status_code == 200
        except requests.ConnectionError:
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
        "authentication": {"kind": "static", "name": user},
        "authorization": "always-allow",
        "etcd": {"host": etcd_host, "port": etcd_port},
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
    }


@pytest.fixture
async def aresponses(loop):
    async with ResponsesMockServer(loop=loop) as server:
        yield server


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
