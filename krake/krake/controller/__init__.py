"""This module comprises Krake controllers responsible of watching API
resources and transferring the state of related real-world resources to the
desired state specified in the API. Controllers can be written in any language
and with every technique. This module provides basic functionality and
paradigms to implement a simple "control loop mechanism" in Python.
"""
import asyncio
import logging
import os.path

from aiohttp import ClientConnectorError

from krake.client import Client


logger = logging.getLogger(__name__)


class WorkQueue(object):
    """Simple asynchronous work queue.

    The key manages a set of key-value pairs. The queue guarantees strict
    sequential processing of keys: If a key-value pair was retrieved via
    :meth:`get`, the same key is not returned via :meth:`get` as long as
    :meth:`done` with the same key is called again even if in the time of
    processing a new key-value pair was put into the queue.

    Args:
        maxsize (int, optional): Maximal number of items in the queue before
            :meth:`put` blocks. Defaults to 0 which means the size is infinite
        loop (asyncio.AbstractEventLoop): Event loop that should be used

    Todo:
        * Implement rate limiting and delays
    """

    def __init__(self, maxsize=0, loop=None):
        self.dirty = dict()
        self.processing = set()
        self.queue = asyncio.Queue(maxsize=maxsize, loop=loop)

    async def put(self, key, value):
        """Put a new key-value pair into the queue.

        Args:
            key: Key that used to identity the value
            value: New value that is associated with the key

        """
        if key not in self.processing:
            await self.queue.put(key)
        self.dirty[key] = value

    async def get(self):
        """Retrieve a key-value pair from the queue.

        The queue will not return this key as long as :meth:`done` is not
        called with this key.

        Returns:
            (key, value) tuple

        """
        key = await self.queue.get()
        value = self.dirty.pop(key)
        self.processing.add(key)
        return key, value

    async def done(self, key):
        """
        """
        self.processing.discard(key)

        if key in self.dirty:
            await self.queue.put(key)

    def empty(self):
        """Check of the queue is empty

        Returns
            bool: True if there are no dirty keys

        """
        return len(self.dirty) == 0

    def full(self):
        """Check if the queue is full

        Returns:
            bool: True if the queue is full

        """

        return self.queue.full()

    def size(self):
        """Returns the number of keys marked as "dirty"

        Returns:
            int: Number of dirty keys in the queue

        """
        return len(self.dirty)


class Controller(object):
    """Base class for Krake controllers providing basic functionality for
    watching and enqueuing API resources.

    The basic workflow is as follows: API resources are watched by the
    controller. Any received new state is put into a :class:`WorkQueue`.
    Multiple worker instances are spawned consuming this queue. Workers are
    responsible for doing the actual state transitions. The work queue ensures
    that a resource is processed by one worker at the same time (strict
    sequential).

    A specialized controller needs to implement the :meth:`list_and_watch`
    coroutine listing and watching resources. The specific characteristics
    which resource should be handled by this controller is an implementation
    detail of the concrete controller.

    It implements the asynchronous context manager protocol. The controller
    itself can be awaited. The await call blocks until the :attr:`watcher`
    task terminates.

    .. code:: python

        async with MyController("http://localhost:8080", worker_factory) as controller:
            await controller

    Args:
        api_endpoint (str): URL to the API
        worker_factory (callable): A callable returning objects compatible with
            the :class:`Worker` interface.
        api_token (str, optional): Token used for API authentication
        worker_count (int, optional): Number of workers that should be spawned
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be used

    Attributes:
        client (krake.client.Client): Krake API client instance that should be used
            for communication with the API.
        queue (WorkQueue): Queue for resource that should be processed
        watcher (asyncio.Task): Task running the :meth:`list_and_watch` coroutine.
        workers (List[asyncio.Task]): List of worker tasks running the
            :func:`consume` coroutine.
    """

    def __init__(
        self,
        api_endpoint,
        worker_factory,
        worker_count=10,
        loop=None,
        ssl_cert=None,
        ssl_key=None,
        client_ca=None,
    ):
        self.loop = loop or asyncio.get_event_loop()
        self.client = None
        self.api_endpoint = api_endpoint
        self.worker_factory = worker_factory
        self.worker_count = worker_count
        self.queue = None
        self.watcher = None
        self.workers = None
        self.ssl_cert = ssl_cert
        self.ssl_key = ssl_key
        self.client_ca = client_ca

    async def __aenter__(self):
        self.client = Client(
            url=self.api_endpoint,
            loop=self.loop,
            ssl_cert=self.ssl_cert,
            ssl_key=self.ssl_key,
            client_ca=self.client_ca,
        )
        await self.client.open()
        self.queue = WorkQueue(loop=self.loop)

        # Start worker tasks
        self.workers = [
            self.loop.create_task(consume(self.queue, self.worker_factory(self.client)))
            for _ in range(self.worker_count)
        ]
        self.watcher = self.loop.create_task(reconnect(self.list_and_watch))
        return self

    async def __aexit__(self, *exc):
        # Cancel watcher task
        if not self.watcher.done():
            self.watcher.cancel()

        # Cancel worker tasks
        for task in self.workers:
            task.cancel()
        for task in self.workers:
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Close client session
        await self.client.close()
        self.client = None

        # Wait for watcher task at the end because otherwise exceptions in the
        # watcher task would prevent the session and worker tasks to be
        # closed.
        try:
            await self.watcher
        except asyncio.CancelledError:
            pass
        finally:
            self.watcher = None

    def __await__(self):
        return self.watcher.__await__()

    async def close(self):
        """Close the controller by canceling the :attr:`watcher` task."""
        self.watcher.cancel()
        try:
            await self.watcher
        except asyncio.CancelledError:
            pass

    async def list_and_watch(self):
        """Coroutine driving the controller that must be implemented by
        subclasses.

        The :attr:`watcher` task will run this coroutine. This coroutine
        should do two things:

        1. **list**: Fetch a list of all resources handled by this controller
           and put them into :attr:`queue`.
        2. **watch**: Create an infinite watch loop for the resource of
           interest and put new resource states into :attr:`queue`.

        :attr:`client` should be used for every interaction with the API.
        """
        raise NotImplementedError()


class Worker(object):
    """Worker interface for consumers of the controller workqueue
    (:attr:`Controller.queue`).

    Args:
        client (krake.client.Client): Krake API client that should be used for
            all interaction with the Krake HTTP API.
    """

    def __init__(self, client):
        self.client = client

    async def resource_received(self, resource):
        """A new resource was received from the API. The worker should compare
        the corresponding real-world state and take necessary actions to
        transfer the real-world state to the desired state specified in the
        API.

        Args:
            resource (object): API object (see :mod:`krake.data`) received
                from the Krake client.
        """
        raise NotImplementedError()

    async def error_occurred(self, resource, error):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Args:
            resource (object): API object (see :mod:`krake.data`) processed
                when the error occurred
            error (Exception): The exception whose reason will be propagated
                to the end-user. Defaults to None.
        """
        raise NotImplementedError()


async def reconnect(handler):
    while True:
        try:
            await handler()
        except asyncio.TimeoutError:
            logger.warn("Timeout")
        except ClientConnectorError as err:
            logger.error(err)
            await asyncio.sleep(1)


async def consume(queue, worker):
    while True:
        # Fetch a new resource and its correlating key from the queue. Until
        # "queue.done(key)"" is called, no other worker can fetch another
        # version of the resource. This ensures strict sequential processing
        # of resources.
        key, item = await queue.get()
        try:
            await worker.resource_received(item)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.exception(err)
            await worker.error_occurred(item, error=err)
        finally:
            # Mark key as done allowing workers to consume the resource
            # again.
            await queue.done(key)


def run(controller):
    """Simple blocking function running the infinite watch loop of a
    controller.

    Args:
        controller (Controller): Controller instances that should be executed
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_run_controller(controller))


async def _run_controller(controller):
    async with controller:
        await controller


def extract_ssl_config(config):
    """
    Get the SSL-oriented parameters from the "tls" part of the configuration of a
    controller.

    Args:
        config (dict): the configuration part of a controller

    Returns:
        dict: the path of the certificate and its key as stored in the configuration. If
        the client authority certificate is present, its path is also given.

    """
    tls_config = config.get("tls")
    if tls_config is None:
        return {}

    try:
        ssl_config = {
            "ssl_cert": tls_config["client_cert"],
            "ssl_key": tls_config["client_key"],
            "client_ca": tls_config.get("client_ca"),
        }
    except KeyError as ke:
        raise KeyError(
            f"The key '{ke.args[0]}' is missing from the 'tls' configuration part"
        )

    for path in ssl_config.values():
        if path and not os.path.isfile(path):
            raise FileNotFoundError(path)

    return ssl_config
