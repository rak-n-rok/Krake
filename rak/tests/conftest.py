import socket
import multiprocessing
import pytest
from aiohttp import web


class SubprocessServer(object):
    def __init__(self):
        self.process = None
        self.host = None
        self.port = None
        self.scheme = None

    def __call__(self, app, host="localhost", port=0, ssl_context=None):
        # ssl_context – ssl.SSLContext for HTTPS server, None for HTTP connection.

        # Bind to an open port
        if port == 0:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("", 0))
            _, port = s.getsockname()
            s.close()

        self.host = host
        self.port = port
        self.scheme = "http" if not ssl_context else "https"
        self.process = multiprocessing.Process(
            target=web.run_app,
            args=(app,),
            kwargs=dict(host=host, port=port, ssl_context=ssl_context),
        )

        self.process.start()

        return self

    def close(self):
        if self.process:
            self.process.terminate()
            self.process.join()

    @property
    def endpoint(self):
        """Return the HTTP endpoint of the test server.

        Returns:
            str: HTTP endpoint of the server

        """
        return f"{self.scheme}://{self.host}:{self.port}"


@pytest.fixture
def subprocess_server():
    server = SubprocessServer()
    yield server
    server.close()


#
#
# logging.config.dictConfig(
#    {
#        "version": 1,
#        "handlers": {"console": {"class": "logging.StreamHandler", "level": "DEBUG"}},
#        "loggers": {"krake": {"handlers": ["console"]}},
#    }
# )
