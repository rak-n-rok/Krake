import json
import os
from zipfile import ZipFile

import pytest
import sys
import werkzeug
import yaml

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
def file_server(httpserver):
    """Start http server with endpoint to get the given file.

    Given file could be `dict` or a regular file.

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

    File content could be given as `dict` or as a regular file.

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
