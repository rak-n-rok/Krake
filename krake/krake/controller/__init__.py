"""This module comprises Krake controllers responsible of watching API
resources and transferring the state of related real-world resources to the
desired state specified in the API. Controllers can be written in any language
and with every technique. This module provides basic functionality and
paradigms to implement a simple "control loop mechanism" in Python.
"""
import asyncio
import logging
import os.path
import signal
from itertools import count
from statistics import mean
from contextlib import suppress

from krake.data.core import WatchEventType
from yarl import URL
import ssl
from aiohttp import ClientConnectorError

from krake.client import Client


logger = logging.getLogger(__name__)


class WorkQueue(object):
    """Simple asynchronous work queue.

    The key manages a set of key-value pairs. The queue guarantees strict
    sequential processing of keys: A key-value pair retrieved via :meth:`get`
    is not returned via :meth:`get` again until :meth:`done` with the
    corresponding key is called, even if a new key-value pair with the
    corresponding key was put into the queue in the meantime.

    Args:
        maxsize (int, optional): Maximal number of items in the queue before
            :meth:`put` blocks. Defaults to 0 which means the size is infinite
        debounce (float): time in second for the debouncing of the values. A
            number higher than 0 means that the queue will wait the given time
            before giving a value. If a newer value is received, this time is
            reset.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used

    Todo:
        * Implement rate limiting and delays
    """

    def __init__(self, maxsize=0, debounce=0, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self.dirty = dict()
        self.timers = dict()
        self.processing = set()
        self.debounce = debounce
        self.loop = loop
        self.queue = asyncio.Queue(maxsize=maxsize, loop=loop)

    async def put(self, key, value, delay=None):
        """Put a new key-value pair into the queue.

        Args:
            key: Key that used to identity the value
            value: New value that is associated with the key
            delay (float, optional): Number of seconds the put should be
                delayed. If :data:`None` is given, :attr:`debounce` will be
                used.

        """
        if delay is None:
            delay = self.debounce

        async def debounce():
            await asyncio.sleep(delay)
            await put_key()

        async def put_key():
            self.dirty[key] = value

            if key not in self.processing:
                await self.queue.put(key)

        def remove_timer(_):
            # Remove timer from dictionary and resolve the waiter for the
            # removal.
            _, removed = self.timers.pop(key)
            removed.set_result(None)

        if delay == 0:
            await put_key()
        else:
            # Cancel current debounced task if present
            if key in self.timers:
                previous, removed = self.timers.get(key)
                previous.cancel()

                # Await the "removed" future instead of the task itself
                # because it is not ensured that the "done" callback was executed
                # when
                #
                #   >>> await previous
                #
                # returns.
                await removed

            timer = self.loop.create_task(debounce())

            # We attach a waiter (future) to the timer task that will be used
            # to await the removal of the key from the timers dictionary. This
            # is required because it is not ensured that "done" callbacks of
            # futures are executed before other coroutines blocking in the
            # future are continued.
            removed = self.loop.create_future()
            timer.add_done_callback(remove_timer)

            self.timers[key] = timer, removed

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

    async def cancel(self, key):
        if key in self.timers:
            timer, removed = self.timers[key]
            timer.cancel()
            with suppress(asyncio.CancelledError):
                await removed

    async def close(self):
        """Cancel all pending debounce timers."""
        timers = list(self.timers.values())

        for timer, _ in timers:
            timer.cancel()

        for timer, _ in timers:
            with suppress(asyncio.CancelledError):
                await timer

    def empty(self):
        """Check if the queue is empty

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


class Reflector(object):
    """Component used to contact the API, fetch resources and handle disconnections.

    Args:
        listing (coroutine): the coroutine used to get the list of resources currently
            stored by the API. Its signature is: ``() -> ApplicationList``.
        watching (coroutine): the coroutine used to watch updates on the resources, as
            as sent by the API. Its signature is: ``() -> watching object``. This
            watching object should be able to be used as context manager, and as
            generator.
        on_list (coroutine): the coroutine called when listing all resources with the
            fetched resources as parameter. Its signature is: ``(resource) -> None``.
        on_add (coroutine, optional): the coroutine called during watch, when an
            ADDED event has been received. Its signature is: ``(resource) -> None``.
        on_update (coroutine, optional): the coroutine called during watch, when a
            MODIFIED event has been received. Its signature is: ``(resource) -> None``.
        on_delete (coroutine, optional): the coroutine called during watch, when a
            DELETED event has been received. Its signature is: ``(resource) -> None``.
        resource_plural (str, optional): name of the resource that the reflector is
            monitoring. For logging purpose. Default is ``"resources"``
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.

    """

    def __init__(
        self,
        listing,
        watching,
        on_list=None,
        on_add=None,
        on_update=None,
        on_delete=None,
        resource_plural=None,
        loop=None,
    ):
        if not loop:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self.client_list = listing
        self.client_watch = watching
        self.on_list = on_list
        self.on_add = on_add
        self.on_update = on_update
        self.on_delete = on_delete

        if not resource_plural:
            resource_plural = "resources"
        self.resource_plural = resource_plural

    async def list_resource(self):
        """Pass each resource returned by the current instance's listing function
        as parameter to the receiving function.
        """
        logger.info(f"Listing {self.resource_plural}")
        if self.on_list is None:
            return

        resource_list = await self.client_list()
        for resource in resource_list.items:
            logger.debug("Received %r", resource)
            await self.on_list(resource)

    async def watch_resource(self, watcher):
        """Pass each resource returned by the current instance's watching object
        as parameter to the event receiving functions.

        Args:
            watcher: an object that returns a new event every time an update on a
                resource occurs

        """
        logger.info(f"Watching {self.resource_plural}")
        async for event in watcher:
            logger.debug("Received %r", event)
            resource = event.object

            # If an event handler has been given, process it
            if event.type == WatchEventType.ADDED and self.on_add:
                await self.on_add(resource)
            elif event.type == WatchEventType.MODIFIED and self.on_update:
                await self.on_update(resource)
            elif event.type == WatchEventType.DELETED and self.on_delete:
                await self.on_delete(resource)

    async def list_and_watch(self):
        """Start the given list and watch coroutines.
        """
        async with self.client_watch() as watcher:
            await joint(
                self.list_resource(), self.watch_resource(watcher), loop=self.loop
            )

    async def __call__(self, max_retry=0):
        """Start the Reflector. Encapsulate the connections with a retry logic.

        Args:
            max_retry (int, optional): the number of times the connection should be
            retried. If 0 is given, it means it should be retried indefinitely

        """
        for i in count():
            try:
                await self.list_and_watch()
            except ClientConnectorError as err:
                logger.error(err)
                await asyncio.sleep(1)

            # This is never true when "max_retry" is None or 0 which leads
            # to an infinite loop.
            if i + 1 == max_retry:
                break


async def joint(*aws, loop=None):
    """Start several coroutines together. Ensure that if one stops, all others
    are cancelled as well.

    Args:
        aws (Awaitable): a list of awaitables to start concurrently.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.

    """
    if loop is None:
        loop = asyncio.get_event_loop()

    # Run every coroutine in a background task
    tasks = [loop.create_task(c) for c in aws]

    try:
        return await asyncio.gather(*tasks)
    finally:
        # Cancel all tasks when returning ensuring that there are no leftover.
        for task in tasks:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


class Observer(object):
    """Component used to watch the actual status of one instance of any resource.

    Args:
        resource: the instance of a resource that the Observer has to watch.
        on_res_update (coroutine): a coroutine called when a resource's actual status
            differs from the status sent by the database. Its signature is:
            ``(resource) -> None``
        time_step (int, optional): how frequently the Observer should watch the actual
            status of the resources.
    """

    def __init__(self, resource, on_res_update, time_step=1):
        self.resource = resource
        self.on_res_update = on_res_update
        self.time_step = time_step

    async def poll_resource(self):
        """Fetch the current status of the watched resource.

        Returns:
            krake.data.core.Status:

        """
        raise NotImplementedError("Implement poll_resources")

    async def observe_resource(self):
        """Update the watched resource if its status is different from the status
        observed. The status sent for the update is the observed one.
        """
        status = await self.poll_resource()
        if self.resource.status != status:
            self.resource.status = status
            await self.on_res_update(self.resource)

    async def run(self):
        """Start the observing process indefinitely, with the Observer time step.
        """
        while True:
            logger.debug("Observing registered resource: %s", self.resource)
            await self.observe_resource()
            await asyncio.sleep(self.time_step)


class Controller(object):
    """Base class for Krake controllers providing basic functionality for
    watching and enqueuing API resources.

    The basic workflow is as follows: the controller holds several background
    tasks. The API resources are watched by a Reflector, which calls a handler
    on each received state of a resource. Any received new state is put into a
    :class:`WorkQueue`. Multiple workers consume this queue. Workers are
    responsible for doing the actual state transitions. The work queue ensures
    that a resource is processed by one worker at a time (strict sequential).
    The status of the real world resources is monitored by an Observer (another
    background task).

    However, this workflow is just a possibility. By modifying :meth:`__init__`
    (or other functions), it is possible to add other queues, change the
    workers at will, add several Reflector or Observer, create additional
    background tasks...

    Args:
        api_endpoint (str): URL to the API
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.
        ssl_context (ssl.SSLContext, optional): if given, this context will be
            used to communicate with the API endpoint.
        debounce (float, optional): value of the debounce for the
            :class:`WorkQueue`.

    """

    def __init__(self, api_endpoint, loop=None, ssl_context=None, debounce=0):
        if not loop:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self.queue = WorkQueue(loop=self.loop, debounce=debounce)
        self.tasks = []
        self.max_retry = 3
        self.burst_time = 10

        # Create client parameters
        self.ssl_context = ssl_context
        self.api_endpoint = self.create_endpoint(api_endpoint)
        self.client = None

    async def prepare(self, client):
        """Start all API clients that the controller will be using. Create all
        necessary coroutines and register them as background tasks that will be
        started by the Controller.

        Args:
            client (krake.client.Client): the base client to use for the API client
                to connect to the API.

        """
        raise NotImplementedError("Implement prepare")

    async def cleanup(self):
        """Unregister all background tasks that are attributes
        """
        raise NotImplementedError("Implement clean_background_tasks")

    def create_endpoint(self, api_endpoint):
        """Ensure the scheme (HTTP/HTTPS) of the endpoint to connect to the
        API, depending on the existence of a given SSL context.

        Args:
            api_endpoint (str): the given API endpoint.

        Returns:
            str: the final endpoint with the right scheme.

        """
        base_url = URL(api_endpoint)

        if self.ssl_context and base_url.scheme != "https":
            logger.warning("API endpoint forced to scheme 'https', as TLS is enabled")
            base_url = base_url.with_scheme("https")

        if not self.ssl_context and base_url.scheme != "http":
            logger.warning("API endpoint forced to scheme 'http', as TLS is disabled")
            base_url = base_url.with_scheme("http")

        return base_url.human_repr()

    def register_task(self, corofactory, name=None):
        """Add a coroutine to the list of task that will be run in the background
         of the Controller.

        Args:
            corofactory (coroutine): the coroutine that will be used as task. It must
                be running indefinitely and not catch :class:`asyncio.CancelledError`.
            name (str, optional): the name of the background task, for logging
                purposes.

        """
        if not name:
            name = corofactory.__name__
        self.tasks.append((corofactory, name))

    async def simple_on_receive(self, resource, condition=bool):
        """Example of a resource receiving handler, that accepts a resource
        under conditions, and if they are met, add the resource to the queue.
        When listing values, you get a Resource, while when watching, you get
        an Event.

        Args:
            resource (krake.data.serializable.Serializable): a resource
                received by listing.
            condition (callable, optional): a condition to accept the given
                resource. The signature should be ``(resource) -> bool``.

        """
        if condition(resource):
            await self.queue.put(resource.metadata.uid, resource)
        else:
            logger.debug("Resource rejected: %s", resource)

    async def retry(self, coro, name=""):
        """Start a background task. If the task fails not too regularly, restart it
        A :class:`BurstWindow` is used to decide if the task should be restarted.

        Args:
            coro (coroutine): the background task to try to restart.
            name (str): the name of the background task (for debugging purposes).

        Raises:
            RuntimeError: if a background task keep on failing more regularly
                than what the burst time allows.

        """
        window = BurstWindow(name, self.burst_time, max_retry=self.max_retry)

        while True:
            with window:
                try:
                    await coro()
                except asyncio.CancelledError:
                    break
                except Exception as err:
                    logger.exception(err)

    async def run(self):
        """Start at once all the registered background tasks with the retry logic.
        """
        client = Client(
            url=self.api_endpoint, loop=self.loop, ssl_context=self.ssl_context
        )
        try:
            await self.prepare(client)
            await self.client.open()
            await asyncio.gather(*(self.retry(task, name) for task, name in self.tasks))
        finally:
            await client.close()
            await self.queue.close()
            await self.cleanup()
            self.tasks = []
            self.client = None


class BurstWindow(object):
    """Context manager that can be used to check the time arbitrary code took to
    run. This arbitrary code should be something that needs to run indefinitely. If
    this code fails too quickly, it is not restarted.

    The criteria is as follow: every :attr:`max_retry` times, if the average
    running time of the task is more than the :attr:`burst_time`, the task
    is considered savable and the context manager is exited. If not, an
    exception will be raised.

    .. code:: python

        window = BurstWindow("my_task", 10, max_retry=3)

        while True:  # use any kind of loop
            with window:
                # code to retry
                # ...

    Args:
        name (str): the name of the background task (for debugging purposes).
        burst_time (float): maximal accepted average time for a retried
            task.
        max_retry (int, optional): number of times the task should be retried before
            testing the burst time. If 0, the task will be retried indefinitely,
            without looking for attr:`burst_time`.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.

    """

    def __init__(self, name, burst_time, max_retry=0, loop=None):
        if not loop:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self.name = name

        self.burst_time = burst_time
        self.max_retry = max_retry

        self.retries = 0
        self.times = [0] * max_retry
        self.start = None

    def __enter__(self):
        self.start = self.loop.time()

    def __exit__(self, *exc):
        """After the given number of tries, raise an exception if the content of the
        context manager failed too fast.

        Raises:
            RuntimeError: if a background task keep on failing more regularly
                than what the burst time allows.

        """
        # TODO: this mechanism could be changed and improved
        end = self.loop.time()
        self.times[self.retries] = end - self.start

        # When errors occurred "max_try" times, check again if the average
        # error time is less than the burst time
        # If max_retry is 0, the exception is never raised.
        if self.retries + 1 == self.max_retry and mean(self.times) < self.burst_time:
            raise RuntimeError(
                f"Task {self.name} failed {self.max_retry} times in a row"
            )
        # Increase retries to update the times list with the current try
        self.retries = (self.retries + 1) % self.max_retry


class Executor(object):
    """Component used to encapsulate the Controller. It takes care of starting
    the Controller, and handles all logic not directly dependent to the
    Controller, such as the handlers for the UNIX signals.

    It implements the asynchronous context manager protocol. The controller
    itself can be awaited. The "await" call blocks until the Controller
    terminates.

    .. code:: python

        executor = Executor(controller)
        async with executor:
            await executor

    Args:
        controller (krake.controller.Controller): the controller that the
            executor is tasked with starting.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.
        catch_signals (bool, optional): if True, the Executor will add handlers
            to catch killing signals in order to stop the Controller and the
            Executor gracefully.
    """

    def __init__(self, controller, loop=None, catch_signals=True):
        self.controller = controller
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self._waiter = None
        self._catch_signals = catch_signals

    def stop(self):
        """Called as signal handler. Stop the Controller managed by the
        instance.
        """
        logger.info("Received signal, exiting...")
        self._waiter.cancel()

    async def __aenter__(self):
        """Create the signal handlers and start the Controller as background
        task.
        """
        if self._catch_signals:
            self.loop.add_signal_handler(signal.SIGINT, self.stop)
            self.loop.add_signal_handler(signal.SIGTERM, self.stop)
        self._waiter = self.loop.create_task(self.controller.run())
        logger.info("Controller started")

    def __await__(self):
        return self._waiter.__await__()

    async def __aexit__(self, *exc):
        """Wait for the managed controller to be finished and cleanup.
        """
        if not self._waiter.done():
            self._waiter.cancel()

        try:
            await self._waiter
        except asyncio.CancelledError:
            pass
        finally:
            if self._catch_signals:
                self.loop.remove_signal_handler(signal.SIGINT)
                self.loop.remove_signal_handler(signal.SIGTERM)
            self._waiter = None

        logger.info("Controller stopped")


def run(controller):
    """Start the controller using an executor.

    Args:
        controller (krake.controller.Controller): the controller to start

    """
    executor = Executor(controller)

    async def _run_controller():
        async with executor:
            await executor

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(_run_controller())
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


def create_ssl_context(tls_config):
    """
    From a certificate, create an SSL Context that can be used on the client side
    for communicating with a Server.

    Args:
        tls_config (dict): the "tls" configuration part of a controller

    Returns:
        ssl.SSLContext: a default SSL Context tweaked with the given certificate
        elements

    """
    if tls_config is None or not tls_config["enabled"]:
        return None

    cert, key, client_ca = _extract_ssl_config(tls_config)
    ssl_context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    ssl_context.verify_mode = ssl.CERT_OPTIONAL

    ssl_context.load_cert_chain(certfile=cert, keyfile=key)

    # Load authorities for client certificates.
    if client_ca:
        ssl_context.load_verify_locations(cafile=client_ca)

    return ssl_context


def _extract_ssl_config(tls_config):
    """
    Get the SSL-oriented parameters from the "tls" part of the configuration of a
    controller, if it is present

    Args:
        tls_config (dict): the "tls" configuration part of a controller

    Returns:
        tuple: a three-element tuple containing: the path of the certificate, its key
         as stored in the config and if the client authority certificate is present,
         its path is also given. Otherwise the last element is None.

    """
    try:
        cert_tuple = (
            tls_config["client_cert"],
            tls_config["client_key"],
            tls_config.get("client_ca"),
        )
    except KeyError as ke:
        raise KeyError(
            f"The key '{ke.args[0]}' is missing from the 'tls' configuration part"
        )

    for path in cert_tuple:
        if path and not os.path.isfile(path):
            raise FileNotFoundError(path)

    return cert_tuple
