import os
import sys
import asyncio
import subprocess
from tempfile import TemporaryDirectory
import time
import logging.config
import requests
import pytest
import aiohttp
from etcd3.aio_client import AioClient
from aresponses import ResponsesMockServer


# Prepend package directory for working imports
package_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, package_dir)

import factories


logging.config.dictConfig(
    {
        "version": 1,
        "handlers": {"console": {"class": "logging.StreamHandler", "level": "DEBUG"}},
        "loggers": {"krake": {"handlers": ["console"]}},
    }
)


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
            "rok_api_test",
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
        "auth": {"kind": "anonymous", "name": user},
        "etcd": {"host": etcd_host, "port": etcd_port},
    }


@pytest.fixture
async def aresponses(loop):
    async with ResponsesMockServer(loop=loop) as server:
        yield server


# -----------------------------------------------------------------------------
# Factories
# -----------------------------------------------------------------------------


@pytest.fixture
def fake():
    return factories.fake


@pytest.fixture
def k8s_app_factory():
    return factories.kubernetes.ApplicationFactory


@pytest.fixture
def k8s_magnum_cluster_factory():
    return factories.kubernetes.MagnumClusterFactory
