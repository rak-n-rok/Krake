import os
import pytest
import sys

# FIXME: Change with a rok implementation of Role and RoleBinding
# This is 1) not the best code, since we make a try.. except.. clause around an
# import statement and 2) it creates a dependency between the rak and rok modules,
# which is not really desired.
# But to have End-to-end-tests in place for roles and rolebindings, we need it like this
# for now (or have a whole lot of code duplication).
# The whole implementation can be rewritten in the future, if rok has support for
# roles and rolebindings in its cli.
#
# Other changes need to be done for the tests in
# rak/functionals/integration/test_core.py
try:
    from rok.fixtures import config as rok_config, session as rok_session
except ImportError:
    pass


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
    parser.addoption(
        "--rok_config",
        action="store",
        help="rok config location to use for scripts integration tests",
    )
    parser.addoption(
        "--template-id", action="store", help="UUID of an OpenStack cluster template."
    )
    parser.addoption(
        "--project-id",
        action="store",
        help="UUID of an OpenStack Project to use as base.",
    )
    parser.addoption(
        "--user-id",
        action="store",
        help="UUID of an OpenStack user, with access to the project and the template.",
    )
    parser.addoption(
        "--user-password", action="store", help="Password of the OpenStack user."
    )
    parser.addoption(
        "--auth-url",
        action="store",
        help="URL to connect to the OpenStack infrastructure.",
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


@pytest.fixture
def session():
    yield from rok_session(rok_config())


@pytest.fixture
def template_id(request):
    return request.config.getoption("--template-id", skip=True)


@pytest.fixture
def project_id(request):
    return request.config.getoption("--project-id", skip=True)


@pytest.fixture
def user_id(request):
    return request.config.getoption("--user-id", skip=True)


@pytest.fixture
def user_password(request):
    return request.config.getoption("--user-password", skip=True)


@pytest.fixture
def auth_url(request):
    return request.config.getoption("--auth-url", skip=True)
