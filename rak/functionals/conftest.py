import os
import pytest
import sys

# Prepend package directory for working imports
package_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, package_dir)


def pytest_addoption(parser):
    """Register :mod:`argparse`-style options and ini-style config values fo
    pytest.

    Called once at the beginning of a test run.

    Args:
        parser (pytest.config.Parser): pytest parser

    """

    parser.addoption(
        "--minikubeclusters",
        action="store",
        nargs="+",
        help="minikube clusters to use for integration tests",
    )
    parser.addoption(
        "--krake_container",
        action="store",
        help="krake container name to use for scripts integration tests",
    )
    parser.addoption(
        "--etcd_container",
        action="store",
        help="etcd container name to use for scripts integration tests",
    )
    parser.addoption(
        "--etcd_container_port",
        action="store",
        help="etcd container port to use for scripts integration tests",
    )


@pytest.fixture
def minikube_clusters(request):
    return request.config.getoption("--minikubeclusters", skip=True)


@pytest.fixture
def krake_container(request):
    return request.config.getoption("--krake_container", skip=True)


@pytest.fixture
def etcd_container(request):
    return request.config.getoption("--etcd_container", skip=True)


@pytest.fixture
def etcd_container_port(request):
    return request.config.getoption("--etcd_container_port", skip=True)
