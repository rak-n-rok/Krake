# import asyncio
import socket
import multiprocessing

# from typing import NamedTuple
import requests
import pytest
from aiohttp import web


def make_app():
    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(request):
        return web.json_response(text="Bonjour le monde")

    app = web.Application()
    app.add_routes(routes)

    return app


class SubprocessServer(object):
    def __init__(self):
        self.process = None
        self.host = None
        self.port = None

    def __call__(self, app, host="localhost", port=0):
        # Bind to an open port
        if port == 0:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("", 0))
            _, port = s.getsockname()
            s.close()

        self.port = port
        self.host = host
        self.process = multiprocessing.Process(
            target=web.run_app, args=(app,), kwargs=dict(host=host, port=port)
        )

        self.process.start()

        return self

    def close(self):
        if self.process:
            self.process.terminate()
            self.process.join()


@pytest.fixture
def subprocess_server():
    server = SubprocessServer()
    yield server
    server.close()


def test_blocking(subprocess_server):
    my_app = make_app()
    server = subprocess_server(my_app)

    response = requests.get(f"http://{server.host}:{server.port}/")

    assert response.status_code == 200
    # assert response.status_code == 201
