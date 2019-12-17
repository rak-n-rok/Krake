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
        nargs='+',
        help="minikube clusters to use for integration tests",
    )


@pytest.fixture
def minikubeclusters(request):
    return request.config.getoption("--minikubeclusters", skip=True)
