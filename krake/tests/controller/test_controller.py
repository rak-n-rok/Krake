import asyncio
from functools import partial
from unittest.mock import Mock

import pytest
from aiohttp import ClientConnectorError
from factories.kubernetes import ApplicationFactory, ApplicationStatusFactory
from krake.client import Client
from krake.controller import (
    WorkQueue,
    Executor,
    Reflector,
    Controller,
    BurstWindow,
    Observer,
)
from krake.data.core import WatchEvent, WatchEventType
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
        def create_background_tasks(self):
            task_1 = BackgroundTask(1, values_gathered)
            self.register_task(task_1.run)
            task_2 = BackgroundTask(2, values_gathered)
            self.register_task(task_2.run)

    controller = SimpleController(api_endpoint="http://localhost:8080")
    controller.create_background_tasks()  # need to be called explicitly
    await asyncio.gather(*(task() for task, name in controller.tasks))

    assert values_gathered == {1, 2}


async def test_controller_run(loop):
    # Test the retry() function of the Controller, which restart any task by default.
    values_gathered = set()

    class SimpleController(Controller):
        async def prepare(self, client):
            self.client = client
            self.task_1 = BackgroundTask(1, values_gathered)
            self.register_task(self.task_1.run)
            self.task_2 = BackgroundTask(2, values_gathered)
            self.register_task(self.task_2.run)

        async def cleanup(self):
            self.task_1, self.task_2 = None, None

    endpoint = "http://localhost:8080"
    controller = SimpleController(api_endpoint=endpoint)

    async with Client(url=endpoint, loop=loop) as client:
        await controller.prepare(client)  # need to be called explicitly
        with pytest.raises(RuntimeError):
            await controller.run()

    assert values_gathered == {1, 2, 3, 4, 5, 6}  # Each task is restarted 3 times.
    assert controller.task_1 is None


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
        def create_background_tasks(self):
            task = BackgroundTask(1, values_gathered, sleep_first=3)
            self.register_task(task.run)

    controller = SimpleController(api_endpoint="http://localhost:8080")
    controller.max_retry = 2
    controller.burst_time = 1
    controller.create_background_tasks()
    with pytest.raises(RuntimeError):
        task_tuple = controller.tasks[0]
        # The task is a tuple (coroutine, name)
        await controller.retry(task_tuple[0])

    assert values_gathered == {1, 3, 5, 7}


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


async def test_reflector_watch(loop):
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


@pytest.mark.slow
async def test_reflector_retry(loop):
    # Simulate a disconnection of the Reflector to the API.
    error_count = []

    connection_key = Mock()
    connection_key.host = "http://localhost:8080"

    def client_error():
        error_count.append(1)
        raise ClientConnectorError(connection_key=connection_key, os_error=OSError())

    reflector = Reflector(client_error, client_error)

    await reflector(max_retry=2)  # Only retry the connection twice
    assert len(error_count) == 2


async def test_observer(loop):
    is_res_updated = loop.create_future()

    app = ApplicationFactory(status__state=ApplicationState.RUNNING)

    real_world_status = ApplicationStatusFactory(state=ApplicationState.UPDATED)

    async def on_res_update(resource):
        assert resource == app
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

    # Ensure that the Application that have been modified on the real world
    # is the second one
    assert is_res_updated.result() == app
