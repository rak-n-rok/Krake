import pytest


def pytest_addoption(parser):
    """Register :mod:`argparse`-style options and ini-style config values fo
    pytest.

    Called once at the beginning of a test run.

    Args:
        parser (pytest.config.Parser): pytest parser

    """

    parser.addoption("--minikubecluster", action="store",
        default="minikube cluster to use for integration tests")


@pytest.fixture
def minikubecluster(request):
    return request.config.getoption("--minikubecluster")