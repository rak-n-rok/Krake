import asyncio
import multiprocessing
import ssl
import sys
import time

from aiohttp import web
from asyncio.subprocess import PIPE, STDOUT
import pytest

from krake.api import __version__ as version
from krake.api.__main__ import main
from krake.api.app import create_app
from krake.api.helpers import session, HttpProblem, HttpProblemTitle
from krake.api.database import revision, TransactionError
from krake.data import Key
from krake.data.config import AuthenticationConfiguration, TlsServerConfiguration
from krake.data.serializable import Serializable
from krake.test_utils import with_timeout

from tests.factories.core import RoleFactory, RoleBindingFactory


@pytest.mark.slow
def test_main(config, tmp_path):
    """Test the main function of the API, and verify that it starts, display the right
    output and stops without issue.
    """
    config.port = 1234
    config.log = {"version": 1, "level": "INFO"}

    file_path = tmp_path / "test.txt"

    def wrapper(configuration):
        sys.stdout = open(file_path, "w")
        main(configuration)

    # Start the process and let it time to initialize
    process = multiprocessing.Process(target=wrapper, args=(config,))
    process.start()
    time.sleep(2)

    # Stop and wait for the process to finish
    process.terminate()
    process.join()

    assert not process.is_alive()
    assert process.exitcode == 0

    with open(file_path, "r") as f:
        output = f.read()

    assert "Running on http://0.0.0.0:1234" in output


async def test_index(aiohttp_client, no_db_config):
    client = await aiohttp_client(create_app(config=no_db_config))
    resp = await client.get("/")
    assert resp.status == 200
    data = await resp.json()
    assert data["version"] == version


async def test_me_route(aiohttp_client, db, config):
    """Ensures that the user given by the `/me` endpoint is the right one, and that it
    is sent along with the corresponding :class:`krake.data.core.Role` instance names.
    """
    authentication = {
        "allow_anonymous": False,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "localhost", "realm": "krake"},
            "static": {"enabled": True, "name": "foo-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)

    client = await aiohttp_client(create_app(config=config))

    roles = [RoleFactory() for _ in range(10)]
    binding_1 = RoleBindingFactory(
        users=["foo-user"], roles=[role.metadata.name for role in roles[:4]]
    )
    binding_2 = RoleBindingFactory(
        users=["foo-user"], roles=[role.metadata.name for role in roles[4:8]]
    )
    # Add an additional RoleBinding for other roles. It should NOT be returned by the
    # endpoint.
    binding_3 = RoleBindingFactory(
        users=["another-one"], roles=[role.metadata.name for role in roles[8:]]
    )
    for role in roles:
        await db.put(role)
    await db.put(binding_1)
    await db.put(binding_2)
    await db.put(binding_3)

    resp = await client.get("/me")
    assert resp.status == 200

    data = await resp.json()
    assert data["user"] == "foo-user"
    assert data["roles"] == sorted([role.metadata.name for role in roles[:8]])


async def test_transaction_retry(aiohttp_client, db, config, loop):
    """Test retry after transaction errors in :func:`krake.api.middlewares.database`.

    Create a custom HTTP endpoint "PUT /books/{isbn}" where the handler waits
    for another coroutine modifying the same etcd key that is fetched by the
    request handler. The modification in the other coroutine will lead to a
    transaction error because the revision changed.

    The database middleware should catch the transaction error and retry the
    request handler. The handler should succeed the second time.
    """
    config.etcd.retry_transactions = 2

    class Book(Serializable):
        isbn: str
        title: str
        author: str
        year: int

        __etcd_key__ = Key("/books/{isbn}")

    fetched = loop.create_future()
    modified = loop.create_future()

    async def write_handler(request):
        book = await session(request).get(Book, isbn=request.match_info["isbn"])
        assert book is not None

        # If the handler is called the first time, inform the modifying
        # coroutine that the book was fetched from the database.
        if not fetched.done():
            fetched.set_result(revision(book).version)

        body = await request.json()
        book.title = body["title"]
        book.author = body["author"]
        book.year = body["year"]

        await modified
        await session(request).put(book)

        return web.json_response(book.serialize())

    async def modify(book):
        # Wait until the book is fetched in the request handler, then modify
        # it and inform the request handler that it was modified.
        await fetched
        await db.put(book)
        modified.set_result(None)

    app = create_app(config=config)
    app.router.add_route("PUT", "/books/{isbn}", write_handler)

    book = Book(
        isbn="0-330-29288-9",
        title="The Hitchhiker's Guide to the Galaxy",
        author="Douglas Adams",
        year=1985,
    )
    await db.put(book)

    book.title = "The Hitchhiker's Guide to the Galaxy: The Original Radio Scripts"

    client = await aiohttp_client(app)
    resp, _ = await asyncio.gather(
        client.put(f"/books/{book.isbn}", json=book.serialize()), modify(book)
    )
    assert resp.status == 200

    body = await resp.json()
    updated = Book.deserialize(body)
    assert updated == book


@with_timeout(3)
async def test_main_help(loop):
    """Verify that the help for the Krake API main is displayed, and contains the
    elements added by the argparse formatters (default value and expected types of the
    parameters).
    """
    command = "python -m krake.api -h"
    # The loop parameter is mandatory otherwise the test fails if started with others.
    process = await asyncio.create_subprocess_shell(
        command, stdout=PIPE, stderr=STDOUT
    )
    stdout, _ = await process.communicate()
    output = stdout.decode()

    to_check = [
        "Krake API server",
        "usage:",
        "default:",  # Present if the default value of the arguments are displayed
        "str",  # Present if the type of the arguments are displayed
        "int",
    ]

    # Because python3.10 argparse version changed 'optional arguments:' to 'options:'
    if sys.version_info < (3, 10):
        to_check.append("optional arguments:")
    else:
        to_check.append("options:")

    for expression in to_check:
        assert expression in output


async def test_transaction_error(aiohttp_client, db, config, loop):
    async def raise_transaction_error(request):
        raise TransactionError("Transaction failed")

    app = create_app(config=config)
    app.router.add_route("PUT", "/raise", raise_transaction_error)

    client = await aiohttp_client(app)
    resp = await client.put("/raise")
    assert resp.status == 409

    json = await resp.json()
    problem = HttpProblem.deserialize(json)
    assert problem.title == HttpProblemTitle.TRANSACTION_ERROR


async def test_cors_setup(aiohttp_client, db, config, loop):
    config.authentication.cors_origin = "http://valid.com"
    app = create_app(config=config)
    client = await aiohttp_client(app)

    # Authorized request to Krake
    resp = await client.options(
        "/",
        headers={
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Requested-With",
            "Origin": "http://valid.com",
        },
    )
    assert resp.status == 200

    # Request refused because of the "PATCH" method.
    resp = await client.options(
        "/",
        headers={
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "X-Requested-With",
            "Origin": "http://valid.com",
        },
    )
    data = await resp.text()
    assert resp.status == 403
    assert "CORS" in data and "PATCH" in data

    # Request refused because of an invalid origin URL.
    resp = await client.options(
        "/",
        headers={
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Requested-With",
            "Origin": "http://invalid-website.com",
        },
    )
    data = await resp.text()
    assert resp.status == 403
    assert "CORS" in data
    assert "origin" in data
    assert "http://invalid-website.com" in data


async def test_cors_setup_rbac(aiohttp_client, db, config, loop, pki):
    """Ensure that even with TLS and RBAC enabled, and no authentication method that
    matches, the CORS mechanism is still accessible.
    """
    server_cert = pki.gencert("api-server")
    client_cert = pki.gencert("test-user")
    authentication = {
        "allow_anonymous": False,
        "strategy": {
            "keystone": {"enabled": False, "endpoint": "localhost"},
            "keycloak": {"enabled": False, "endpoint": "endpoint", "realm": "krake"},
            "static": {"enabled": False, "name": "test-user"},
        },
    }
    config.authentication = AuthenticationConfiguration.deserialize(authentication)
    config.authorization = "RBAC"

    tls_config = {
        "enabled": True,
        "client_ca": pki.ca.cert,
        "cert": server_cert.cert,
        "key": server_cert.key,
    }
    config.tls = TlsServerConfiguration.deserialize(tls_config)

    app = create_app(config=config)
    client = await aiohttp_client(app)
    context = ssl.create_default_context(
        purpose=ssl.Purpose.CLIENT_AUTH, cafile=pki.ca.cert
    )
    context.load_cert_chain(*client_cert)

    # Requests authenticated via TLS

    # Authorized request to Krake
    resp = await client.options(
        "/kubernetes/applications",
        headers={
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Requested-With",
            "Origin": "http://example.com",
        },
        ssl=context,
    )
    assert resp.status == 200

    # Request refused because of the "PATCH" method.
    resp = await client.options(
        "/kubernetes/applications",
        headers={
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "X-Requested-With",
            "Origin": "http://example.com",
        },
        ssl=context,
    )
    data = await resp.text()
    assert "PATCH" in data and "CORS" in data
    assert resp.status == 403

    # Requests without TLS authentication

    # Authorized request to Krake
    resp = await client.options(
        "/kubernetes/applications",
        headers={
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Requested-With",
            "Origin": "http://example.com",
        },
    )
    assert resp.status == 200

    # Request refused because of the "PATCH" method.
    resp = await client.options(
        "/kubernetes/applications",
        headers={
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "X-Requested-With",
            "Origin": "http://example.com",
        },
    )
    data = await resp.text()
    assert "PATCH" in data and "CORS" in data
    assert resp.status == 403


async def test_unknown_auth_strategy(aiohttp_client, config):
    """Ensure that setting an authorization mode that is not supported raises an
    exception.
    """
    config.authorization = "invalid"

    with pytest.raises(ValueError, match="Unknown authorization strategy 'invalid'"):
        create_app(config=config)


async def test_error_logging(aiohttp_client, config, caplog):
    """Ensure that an exception occurring inside the API is properly logged."""
    # Get an additional WARNING otherwise
    config.authentication.cors_origin = "http://example.com"
    config.etcd.host = "wrong_endpoint"

    client = await aiohttp_client(create_app(config=config))

    resp = await client.get("/core/globalmetrics")
    assert resp.status == 500

    for record in caplog.records:
        assert record.levelname == "ERROR"
