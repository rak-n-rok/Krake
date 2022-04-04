import asyncio
import sys
import logging
import pytest
from contextlib import suppress
from functools import partial
from unittest.mock import Mock

from aiohttp import web
from krake.client.core import CoreApi
from krake.test_utils import server_endpoint, with_timeout
from aiohttp import ClientConnectorError
from krake.data.config import TlsClientConfiguration
from tests.factories.kubernetes import ApplicationFactory, ApplicationStatusFactory
from krake.controller import (
    WorkQueue,
    Executor,
    Reflector,
    Controller,
    BurstWindow,
    Observer,
    sigmoid_delay,
    create_ssl_context,
    _extract_ssl_config,
)
from krake.data.core import WatchEvent, WatchEventType, ListMetadata, RoleList
from krake.data.kubernetes import ApplicationState
from tests.controller import SimpleWorker


async def test_put_get_done():
    queue = WorkQueue(debounce=0)

    await queue.put("key1", "value1-1")
    assert queue.size() == 1
    key, value = await queue.get()

    assert key == "key1"
    assert value == "value1-1"

    # Mark "key1" and "key2" as dirty.
    await queue.put("key1", "value1-2")
    await queue.put("key2", "value2-1")
    assert queue.size() == 2

    # Since "key1" is marked as "processing" it must not be returned.
    key, value = await queue.get()
    assert key == "key2"
    assert value == "value2-1"

    # Mark "key1" as done. The key is marked as dirty. Hence, queue should
    # return it.
    await queue.done("key1")
    key, value = await queue.get()

    assert key == "key1"
    assert value == "value1-2"

    await queue.done("key1")
    await queue.done("key2")

    assert queue.empty()


@pytest.mark.slow
async def test_queue_debounce(loop):
    queue = WorkQueue(loop=loop, debounce=1)

    # Each new added value should reset the timer for the "key" key
    await queue.put("key", 1)

    start = loop.time()
    key, value = await queue.get()
    end = loop.time()

    assert (key, value) == ("key", 1)

    # The value should be received a bit after debounce time
    assert 1 < end - start < 1.1

    await queue.done("key")
    assert queue.empty()


async def test_queue_debounce_burst(loop):
    queue = WorkQueue(loop=loop, debounce=0.1)

    await queue.put("key", 1)

    await asyncio.sleep(0.05)
    await queue.put("key", 2)

    await asyncio.sleep(0.05)
    await queue.put("key", 3)

    key, value = await queue.get()
    assert (key, value) == ("key", 3)


@pytest.mark.slow
async def test_queue_debounce_with_done(loop):
    queue = WorkQueue(loop=loop, debounce=1)

    await queue.put("key", 1)
    key, value1 = await queue.get()
    assert key, value1 == ("key", 1)

    # Receive the new value. This should also debounce which means that the
    # reception takes some time.
    await queue.put("key", 2)

    # Release key while a debounce timer is active for the key
    start = loop.time()
    await queue.done("key")

    key, value2 = await queue.get()
    end = loop.time()
    assert key, value2 == ("key", 2)

    # The value should be received a bit after debounce time
    assert 1 < end - start < 1.1


async def test_queue_pending_debounce(loop):
    queue = WorkQueue(loop=loop, debounce=0.1)

    # Put version of of the key into the queue
    await queue.put("key", 1)

    # Wait until the debounce timer triggers and put another version into the
    # queue. This means the debounce timer is still pending when the first
    # version is fetched from the queue.
    await asyncio.sleep(0.2)
    await queue.put("key", 2)

    key, value = await queue.get()
    assert (key, value) == ("key", 1)
    await queue.done(key)

    key, value = await queue.get()
    assert (key, value) == ("key", 2)


async def test_queue_delayed_put(loop):
    queue = WorkQueue(loop=loop, debounce=0)

    # Each new added value should reset the timer for the "key" key
    await queue.put("key", 1, delay=0.1)

    start = loop.time()
    key, value = await queue.get()
    end = loop.time()

    assert (key, value) == ("key", 1)

    # The value should be received a bit after the delay time
    assert 0.1 < end - start < 0.15

    await queue.done("key")
    assert queue.empty()


async def test_queue_multiple_puts(loop):
    """Verify the behavior of the queue after a key was inserted, then its value was
    replaced. The queue should behave as if the key was inserted once, as the second
    insertion should not change the normal behavior of the queue."""
    queue = WorkQueue(loop=loop, debounce=0)

    await queue.put("key", 1)
    await queue.put("key", 2)

    key, value = await queue.get()
    assert value == 2

    # After a get(), if only one key is inserted (even after replacing it), the get()
    # method should hang for a while. To carry on with the test, the wait_for function
    # is used.
    # As the get() method should only be stopped because of the timeout, what is
    # verified here is that the only exception raised is a TimeoutError.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=1)

    # Free the key from the queue
    await queue.done(key)

    # After the key was freed, no other key was added, so the get() method should hang
    # again, and should be stopped only because of a timeout.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=1)


async def test_queue_active(loop):
    queue = WorkQueue(loop=loop, debounce=0)

    await queue.put("key", 1)
    await queue.get()

    await queue.put("key", 2)
    await queue.done("key")

    # Check that the key isn't removed from the active set when the done method is
    # called while a new value is present in the dirty dictionary.
    assert "key" in queue.active

    # Consequently, check that the key is added only once to the queue.
    await queue.put("key", 3)
    assert queue.queue.qsize() == 1


async def test_queue_cancel_simple(loop):
    """Attempt the canceling of a unique key. This should leave the queue and its timers
    empty
    """
    queue = WorkQueue(loop=loop, debounce=0)

    # Add a large value to be sure it will not be removed during the test
    await queue.put("key", 1, delay=10 ** 10)

    assert queue.empty()
    assert queue.size() == 0
    assert len(queue.timers) == 1

    await queue.cancel("key")

    assert queue.empty()
    assert queue.size() == 0
    assert len(queue.timers) == 0


async def test_queue_cancel_multiple_keys(loop):
    """Attempt the canceling of multiple keys."""
    queue = WorkQueue(loop=loop, debounce=0)

    # Add a large value to be sure it will not be removed during the test
    await queue.put("key_1", 1, delay=10 ** 10)
    await queue.put("key_2", 2, delay=10 ** 10)

    assert queue.empty()
    assert queue.size() == 0
    assert len(queue.timers) == 2

    await queue.cancel("key_1")

    assert queue.empty()
    assert queue.size() == 0
    assert len(queue.timers) == 1

    await queue.cancel("key_2")

    assert queue.empty()
    assert queue.size() == 0
    assert len(queue.timers) == 0


async def test_queue_cancel_workflow(loop):
    """Attempt adding a key, updating it, canceling it, then add a new value."""
    queue = WorkQueue(loop=loop, debounce=0)
    await queue.put("key", 1, delay=10 ** 10)
    assert len(queue.timers) == 1

    await queue.put("key", 2, delay=10 ** 10)
    assert len(queue.timers) == 1

    await queue.cancel("key")
    assert len(queue.timers) == 0

    await queue.put("key", 3)
    assert len(queue.timers) == 0
    assert not queue.empty()

    key, value = await queue.get()
    assert (key, value) == ("key", 3)


async def test_queue_cancel_non_existent_key(loop):
    """Ensure that cancelling a key not present in the queue
    does not raise any error.
    """
    queue = WorkQueue(loop=loop, debounce=0)
    assert queue.empty()

    await queue.cancel("key")

    assert queue.empty()
    assert len(queue.timers) == 0

    # Add another key and try to cancel a non-existing key again. The behavior should
    # not change in any way.
    await queue.put("other_key", 1)

    await queue.cancel("key")

    assert queue.size() == 1
    assert len(queue.timers) == 0


async def test_queue_close(loop):
    """Test the close() method of the WorkQueue, which cancel all its timers."""
    queue = WorkQueue(loop=loop, debounce=0)
    await queue.put("key_1", 1, delay=10 ** 10)
    await queue.put("key_2", 2, delay=10 ** 11)
    assert len(queue.timers) == 2
    assert queue.empty()

    await queue.close()
    assert len(queue.timers) == 0
    assert queue.empty()


async def test_queue_full(loop):
    """Test the full() method of the WorkQueue, which checks if the amount of elements
    in the queue is equal to its maximum size.
    """
    queue = WorkQueue(maxsize=2, loop=loop, debounce=0)
    assert not queue.full()

    await queue.put("key_1", 1)
    assert not queue.full()

    await queue.put("key_2", 2)
    assert queue.full()

    _, _ = await queue.get()
    assert not queue.full()

    await queue.put("key_3", 3)
    assert queue.full()


async def test_executor(loop):
    # Do not use a unittest.Mock because run() needs to be asynchronous
    class SimpleController(object):
        def __init__(self):
            self.called_count = 0

        async def run(self):
            self.called_count += 1

    controller = SimpleController()
    executor = Executor(controller, catch_signals=False)
    async with executor:
        await executor

    assert controller.called_count == 1


def test_create_endpoint_https_without_ssl(loop, caplog):
    """Test creating a controller with an endpoint with the "https" scheme, but with TLS
    disabled. A warning should appear in the logs.
    """
    api_endpoint = "https://host.com:1234"

    _ = Controller(api_endpoint, loop=loop, ssl_context=None)

    for record in caplog.records:
        if record.levelname == logging.WARNING:
            assert "forced to scheme 'http'" in record.message


def test_create_endpoint_http_with_ssl(pki, loop, caplog):
    """Test creating a controller with an endpoint with the "http" scheme, but with TLS
    enabled. A warning should appear in the logs.
    """
    client_cert = pki.gencert("client")
    client_tls = TlsClientConfiguration(
        enabled=True,
        client_ca=pki.ca.cert,
        client_cert=client_cert.cert,
        client_key=client_cert.key,
    )
    ssl_context = create_ssl_context(client_tls)

    api_endpoint = "http://host.com:1234"
    _ = Controller(api_endpoint, loop=loop, ssl_context=ssl_context)

    for record in caplog.records:
        if record.levelname == logging.WARNING:
            assert "forced to scheme 'https'" in record.message


class BackgroundTask(object):
    """Dummy task that can be used in the Controller as a background task.
    THIS TASK DOES NOT RUN INDEFINITELY, thus, the controller may raise
    exceptions.

    The task simply increments a value and add it to the :attr:`gathered`
    set. It can also be set to simulate work on the first call to the task.

    Args:
        init_value (int): the first value to give to the task.
        gathered (set): a set where all computed values will be added.
        sleep_first (int): how much time (in seconds) the task will sleep
            the first time it is called.

    """

    def __init__(self, init_value, gathered, sleep_first=0):
        self.value = init_value
        self.gathered = gathered
        self.to_sleep = sleep_first

    async def run(self, increment=2):
        self.gathered.add(self.value)
        self.value += increment
        if self.to_sleep:
            await asyncio.sleep(self.to_sleep)
            self.to_sleep = 0


async def test_controller_background_tasks(loop):
    # Test for several background tasks working in parallel.
    values_gathered = set()

    class SimpleController(Controller):
        def prepare(self):
            task_1 = BackgroundTask(1, values_gathered)
            self.register_task(task_1.run)
            task_2 = BackgroundTask(2, values_gathered)
            self.register_task(task_2.run)

    controller = SimpleController(api_endpoint="http://localhost:8080")
    controller.prepare()  # need to be called explicitly
    await asyncio.gather(*(task() for task, name in controller.tasks))

    assert values_gathered == {1, 2}


async def test_controller_run(loop):
    # Test the retry() function of the Controller, which restart any task a certain
    # amount of time, 3 by default.
    values_gathered = set()

    class SimpleController(Controller):
        async def infinite_task(self):
            # Create a task that runs indefinitely to simulate other background tasks
            # that run on a Controller.
            while True:
                # Ensure this does not throw any GeneratorExit exception.
                key, cluster = await self.queue.get()
                try:
                    await asyncio.sleep(0)
                finally:
                    await self.queue.done(key)

        async def prepare(self, client):
            self.client = client
            self.task_1 = BackgroundTask(1, values_gathered)
            self.register_task(self.task_1.run)
            self.task_2 = BackgroundTask(2, values_gathered)
            self.register_task(self.task_2.run)

            self.register_task(self.infinite_task)

        async def cleanup(self):
            self.task_1, self.task_2 = None, None

    endpoint = "http://localhost:8080"
    controller = SimpleController(api_endpoint=endpoint, loop=loop)

    with pytest.raises(RuntimeError, match="Task run failed 3 times in a row"):
        await controller.run()

    assert values_gathered == {1, 2, 3, 4, 5, 6}  # Each task is restarted 3 times.
    assert controller.task_1 is None

    if sys.version_info < (3, 9):
        all_tasks_method = asyncio.Task.all_tasks
    else:
        all_tasks_method = asyncio.all_tasks

    # Ensure that all remaining tasks of the retry mechanism of the Controller
    # ("gathered" in the run method) are cancelled because of the errors that occurred
    # in background tasks "task_1" and "task_2".
    for task in all_tasks_method():
        # Choose only the task with a waiter, otherwise we also choose the current test
        # coroutine
        if not task.done() and task._fut_waiter is not None:
            assert task._fut_waiter._state == "CANCELLED"


@pytest.mark.slow
async def test_burst_window(loop):
    """The test start a "for" loop with many iterations.

    For the first two iterations, the task in this loop stops, but slow enough,
    so that the window does not raise any exception. It simulates a task that
    fails but that we can save.

    All next iterations happen too fast, which means the task "fails" too
    fast, and the :class:`BurstWindow` decides to raise an Exception after two
    retries (see the `max_retry` parameter of `window` ).

    """
    window = BurstWindow("dummy_task", 0.5, max_retry=2, loop=loop)

    i = 0
    with pytest.raises(RuntimeError):
        for i in range(6):
            with window:
                # Start task:
                if i < 2:
                    await asyncio.sleep(1)
                else:
                    pass  # for all other iterations, the task "fails" too fast

            assert window.retries == (i + 1) % 2

    # The "for" loop went through 4 iterations in total.
    assert i == 3


@pytest.mark.slow
async def test_controller_retry(loop):
    """Try here the retry function with burst. For this the BackgroundTask is
    set to sleep at the beginning, before stopping. With this, the Controller
    assumes that the task did not fail too fast, and that is should be retried.

    After the first try, no sleep is performed. The Controller assumes that the
    BackgroundTask failed too quickly, and does not try to restart it.

    So the controller should retry it twice, then retry again twice.
    """
    values_gathered = set()

    class SimpleController(Controller):
        def prepare(self):
            task = BackgroundTask(1, values_gathered, sleep_first=3)
            self.register_task(task.run)

    controller = SimpleController(api_endpoint="http://localhost:8080")
    controller.max_retry = 2
    controller.burst_time = 1
    controller.prepare()
    with pytest.raises(RuntimeError):
        task_tuple = controller.tasks[0]
        # The task is a tuple (coroutine, name)
        await controller.retry(task_tuple[0])

    assert values_gathered == {1, 3, 5, 7}


async def test_controller_retry_error_handling(loop, caplog):
    """This test ensures that any exception occurring inside the retry() method of the
    Controller is still logged, and that is does not stop the method. The test ensures
    also that its still stops as expected when the maximum amounts of retries have been
    attempted.
    """
    caplog.set_level(logging.INFO)

    class ErrorTaskException(Exception):
        pass

    class ErrorTask(object):
        async def run(self):
            raise ErrorTaskException("Raise an error on purpose")

    class SimpleController(Controller):
        def prepare(self):
            self.register_task(ErrorTask().run)

    controller = SimpleController(api_endpoint="http://localhost:8080", loop=loop)
    controller.max_retry = 2
    controller.burst_time = 1
    controller.prepare()
    with pytest.raises(RuntimeError):
        task_tuple = controller.tasks[0]
        # The task is a tuple (coroutine, name)
        await controller.retry(task_tuple[0])

    error_count = 0
    for record in caplog.records:
        if record.levelname == "ERROR":
            assert record.message == "Raise an error on purpose"
            error_count += 1

    # The number of retries has been set to 2 (max_retry), and the task fails very fast
    # (the exception is directly raised), so the burst time of 1 is not exceeded. Thus,
    # a first try is attempted, it fails directly, then a second one, which also
    # directly fails. Thus, the burst window raises a RuntimeError and breaks the loop,
    # and the error from the background task is raised twice.
    assert error_count == 2


async def test_reflector_list(loop):
    # Test the list functionality of the Reflector. Give the received values to a
    # SimpleWorker.
    items = [ApplicationFactory() for _ in range(3)]
    receiver = SimpleWorker(set((app.metadata.uid for app in items)), loop)

    async def list_res():
        list_mock = Mock()
        list_mock.items = list(items)
        return list_mock

    reflector = Reflector(
        listing=list_res, watching=None, on_list=receiver.resource_received
    )
    await reflector.list_resource()

    assert receiver.done.done()
    await receiver.done


async def test_reflector_watch_multiple(loop):
    # Test the watch functionality of the Reflector. Give the received values to a
    # SimpleWorker.
    items = [ApplicationFactory() for _ in range(3)]
    receiver = SimpleWorker(set((app.metadata.uid for app in items)), loop)

    class Watcher(object):
        def __init__(self, apps):
            self.items = list(apps)

        async def __aenter__(self):
            return self.watch()

        async def __aexit__(self, *exc):
            pass

        async def watch(self):
            for item in self.items:
                yield WatchEvent(type=WatchEventType.ADDED, object=item)

    async def on_receive(resource):
        await receiver.resource_received(resource=resource)

    async def not_to_call():
        assert False

    reflector = Reflector(
        listing=None,
        watching=partial(Watcher, items),
        on_add=on_receive,
        on_update=not_to_call,
        on_delete=not_to_call,
    )

    async with reflector.client_watch() as watcher:
        await reflector.watch_resource(watcher)

    assert receiver.done.done()
    await receiver.done


async def test_reflector_watch_events(loop):
    """Test the watch functionality of the Reflector. Ensure each watch event type is
    actually handled and by a different function.
    """
    items = [ApplicationFactory() for _ in range(3)]
    receiver_added = SimpleWorker({items[0].metadata.uid}, loop)
    receiver_modified = SimpleWorker({items[1].metadata.uid}, loop)
    receiver_deleted = SimpleWorker({items[2].metadata.uid}, loop)

    class Watcher(object):
        def __init__(self, apps):
            self.items = list(apps)

        async def __aenter__(self):
            return self.watch()

        async def __aexit__(self, *exc):
            pass

        async def watch(self):
            types = [
                WatchEventType.ADDED,
                WatchEventType.MODIFIED,
                WatchEventType.DELETED,
            ]
            for item, watch_event_type in zip(self.items, types):
                yield WatchEvent(type=watch_event_type, object=item)

    async def on_add(resource):
        await receiver_added.resource_received(resource=resource)

    async def on_update(resource):
        await receiver_modified.resource_received(resource=resource)

    async def on_delete(resource):
        await receiver_deleted.resource_received(resource=resource)

    reflector = Reflector(
        listing=None,
        watching=partial(Watcher, items),
        on_add=on_add,
        on_update=on_update,
        on_delete=on_delete,
    )

    async with reflector.client_watch() as watcher:
        await reflector.watch_resource(watcher)

    # Each handler should have been called after its corresponding event was received.
    assert receiver_added.done.done()
    await receiver_added.done

    assert receiver_modified.done.done()
    await receiver_modified.done

    assert receiver_deleted.done.done()
    await receiver_deleted.done


@pytest.mark.slow
async def test_reflector_retry(loop):
    """This test is intended to test the retry() mechanism of the Reflector, which
    attempts to reconnect to the API when disconnections occur.

    Four steps are present during the test:
    1. Simulate a disconnection of the Reflector to the API, to trigger the retry
    mechanism of the Reflector.

    2. Then, a connection is possible, which should reset the delay.

    3. After that, a disconnection happens again.

    4. Finally, trigger an unexpected error to ensure that the reflector is stopped.
    """
    start_time = 0
    # Amount of time in seconds a connection was possible between the Reflector and the
    # API without interruption (during step 2).
    error_free_time = 0
    # Store the amounts of time in seconds between two entries in the watcher.
    delays = []

    connect_key = Mock()
    connect_key.host = "http://dummy_host:8080"

    mock_event = Mock()
    mock_event.object = Mock()

    class WatcherMock(object):
        async def __aenter__(self):
            return self.watch()

        async def __aexit__(self, *exc):
            pass

        async def watch(self):
            while True:
                yield await client_handler()

    async def client_handler():
        # This function is called every time the Reflector attempts to connect to the
        # API. When this function creates a disconnection, the Reflector tries to
        # connect again, and the interval between two attempts grows.

        nonlocal error_free_time
        # Timestamp since the last error
        since_error = loop.time() - error_free_time
        delays.append(since_error)

        # Timestamp since the beginning of the Reflector run
        from_start = loop.time() - start_time
        if from_start < 3:
            # Step 1: 3 disconnections are expected.
            raise ClientConnectorError(connection_key=connect_key, os_error=OSError())
        elif from_start < 5:
            # Step 2: Connection starts again: 1 connection is possible
            await asyncio.sleep(2)
            error_free_time = loop.time()
            return mock_event
        elif from_start < 8:
            # Step 3: 3 disconnections are expected, the delay is reset.
            raise ClientConnectorError(connection_key=connect_key, os_error=OSError())
        else:
            # Step 4: Error not handled by the Reflector
            raise RuntimeError("Unexpected error")

    reflector = Reflector(None, WatcherMock)

    start_time = loop.time()
    error_free_time = loop.time()
    with pytest.raises(RuntimeError, match="Unexpected error"):
        await reflector(min_interval=1)

    # Delay is computed when entering the watcher!!!
    #  * A first delay when entering the function the first time;
    #  * then 3 connection exceptions,
    #  * then have a connection that reset the delay after it to a small value;
    #  * then 3 connection exceptions.
    # Finally an error (no delay computed).
    # That makes 8 delays.
    assert len(delays) == 8

    # When the connection was possible, the growth of the delay was reset. It means
    # the first half of the delays is increasing from ~0 to a higher value, then on the
    # second half, the delays are reset, and the delays are again increasing from ~0 to
    # a higher value.
    cumulative_sum = 0
    for i in range(4):
        # We ensure first that the delays before and after the reset are higher than the
        # computed delay. This should always be the case, as the delays are the sum of
        # the sigmoid delay and the compute between two attempts. This should hold true
        # for all attempts, hence testing inside a loop.
        assert delays[i] > cumulative_sum
        assert delays[i + 4] > cumulative_sum

        cumulative_sum += sigmoid_delay(i)

        # The current delay should however always be smaller than the next delay,
        # because of the sigmoid delay which is higher than one (and because of the
        # compute time). This should hold true for all attempts, hence testing inside a
        # loop.
        assert cumulative_sum > delays[i]
        assert cumulative_sum > delays[i + 4]


@with_timeout(3)
async def test_controller_resilience_api_list_fail(aiohttp_server, config, db, loop):
    """Ensure that a response sent by the API with an error when listing the resources
    does not make the Reflector fail, and with it the Controller.
    """
    routes = web.RouteTableDef()

    class SimpleController(Controller):
        async def simple_on_list(self, resource):
            # If this method is not provided, the listing will not be done by the
            # Reflector
            assert False  # This method should never be called

        async def prepare(self, client):
            assert client is not None
            self.client = client
            self.core_api = CoreApi(self.client)

            self.simple_reflector = Reflector(
                listing=self.core_api.list_roles,
                watching=self.core_api.watch_roles,
                on_list=self.simple_on_list,
                loop=self.loop,
            )
            self.register_task(self.simple_reflector, name="Simple reflector")

        async def cleanup(self):
            self.simple_reflector = None
            self.core_api = None

    @routes.get("/core/roles")
    async def _(request):
        watch = request.rel_url.query.get("watch")
        if watch is None:
            raise web.HTTPInternalServerError()
        # Create a mock "watch" response
        resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        resp.enable_chunked_encoding()
        await resp.prepare(request)
        await asyncio.sleep(30)  # Ensure that the "watch" request do no end prematurely

    mock_app = web.Application(debug=True)
    mock_app.add_routes(routes)
    mock_api = await aiohttp_server(mock_app, debug=True)

    controller = SimpleController(server_endpoint(mock_api), loop=loop)
    run_task = loop.create_task(controller.run())
    await asyncio.sleep(1)  # wait for the reflectors --> prevents false positives

    # The controller task should not have been finished because of the server error.
    assert not run_task.done()
    assert not run_task.cancelled()
    with pytest.raises(asyncio.InvalidStateError, match="Exception is not set."):
        run_task.exception()

    run_task.cancel()
    with suppress(asyncio.CancelledError):
        await run_task


@with_timeout(3)
async def test_controller_resilience_api_watch_fail(aiohttp_server, config, db, loop):
    """Ensure that a response sent by the API with an error when watching the resources
    does not make the Reflector fail, and with it the Controller.
    """
    routes = web.RouteTableDef()

    class SimpleController(Controller):
        async def prepare(self, client):
            assert client is not None
            self.client = client
            self.core_api = CoreApi(self.client)

            self.simple_reflector = Reflector(
                listing=self.core_api.list_roles,
                watching=self.core_api.watch_roles,
                loop=self.loop,
            )
            self.register_task(self.simple_reflector, name="Simple reflector")

        async def cleanup(self):
            self.simple_reflector = None
            self.core_api = None

    @routes.get("/core/roles")
    async def _(request):
        watch = request.rel_url.query.get("watch")
        if watch is None:
            # Create a mock "list" response
            body = RoleList(metadata=ListMetadata(), items=[])
            return web.json_response(body.serialize())
        raise web.HTTPInternalServerError()

    mock_app = web.Application(debug=True)
    mock_app.add_routes(routes)
    mock_api = await aiohttp_server(mock_app, debug=True)

    controller = SimpleController(server_endpoint(mock_api), loop=loop)
    run_task = loop.create_task(controller.run())
    await asyncio.sleep(1)  # wait for the reflectors --> prevents false positives

    # The controller task should not have been finished because of the server error.
    assert not run_task.done()
    assert not run_task.cancelled()
    with pytest.raises(asyncio.InvalidStateError, match="Exception is not set."):
        run_task.exception()

    run_task.cancel()
    with suppress(asyncio.CancelledError):
        await run_task


async def test_observer(loop):
    is_res_updated = loop.create_future()

    app = ApplicationFactory(status__state=ApplicationState.RUNNING)
    real_world_status = ApplicationStatusFactory(state=ApplicationState.RUNNING)

    async def on_res_update(resource):
        assert resource != app
        assert resource.status == real_world_status
        is_res_updated.set_result(resource)

    async def new_poll_resources():
        # change the real world status compared to the one registered
        return real_world_status

    observer = Observer(app, on_res_update)
    observer.poll_resource = new_poll_resources

    await observer.observe_resource()

    # Ensure that the on_res_update function is called
    assert is_res_updated.done()
    await is_res_updated


@pytest.mark.slow
async def test_observer_run(loop):
    """Test the run() method of the Observer. Ensure its polls the status of the
    observed resources several times.
    """
    count = 0
    is_res_updated = loop.create_future()

    app = ApplicationFactory(status__state=ApplicationState.RUNNING)
    real_world_status = ApplicationStatusFactory(state=ApplicationState.RUNNING)

    async def on_res_update(resource):
        nonlocal count
        count += 1
        if count == 3:
            is_res_updated.set_result(resource)

    async def new_poll_resources():
        # change the real world status compared to the one registered, to trigger the
        # call to on_res_update
        return real_world_status

    observer = Observer(app, on_res_update, time_step=1)
    observer.poll_resource = new_poll_resources

    # Run the task 4 seconds to let it do several loops.
    run_task = loop.create_task(observer.run())
    await asyncio.sleep(4)

    run_task.cancel()
    with suppress(asyncio.CancelledError):
        await run_task

    # Ensure that the on_res_update function has been called 3 times (see the content of
    # on_res_update()): as there was a 4 seconds sleep, and the time_step of the
    # Observer is 1 seconds, only 3 loops of the Observer.run() method could finish.
    assert count == 3

    assert is_res_updated.done()
    await is_res_updated


@pytest.mark.parametrize("invalid_attr", ["client_ca", "client_cert", "client_key"])
def test_extract_ssl_config_error_handling(pki, invalid_attr):
    """Test the error handling in the _extract_ssl_config utility function."""
    client_cert = pki.gencert("client")
    client_tls = TlsClientConfiguration(
        enabled=True,
        client_ca=pki.ca.cert,
        client_cert=client_cert.cert,
        client_key=client_cert.key,
    )

    setattr(client_tls, invalid_attr, "/path/to/nothing")

    with pytest.raises(FileNotFoundError, match="/path/to/nothing"):
        _extract_ssl_config(client_tls)
