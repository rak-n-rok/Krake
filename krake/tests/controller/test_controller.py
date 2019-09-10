import asyncio
from unittest.mock import Mock

import pytest
from factories.kubernetes import ApplicationFactory
from krake.controller import WorkQueue, consume, Timer


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
async def test_queue_timer(loop):
    queue = WorkQueue(loop=loop, debounce=3)

    # Each new added value should reset the timer for the "key1" key
    await queue.put("key1", "value1-1")

    # A new value is added after the start of the waiting time,
    # which should reset the internal timer for the key
    async def callback():
        await queue.put("key1", "value1-2")

    timer = Timer(1, callback)

    start = loop.time()
    key, value = await queue.get()
    end = loop.time()

    assert timer.is_done()
    assert key == "key1"
    assert value == "value1-2"
    # The value should be received a bit after "debounce time + timer timeout"
    assert 4 < end - start < 4.1

    await queue.done("key1")

    assert queue.empty()


async def test_consume_error_handling(loop):
    app = ApplicationFactory()
    reason = Exception("Internal Error")

    worker = Mock()
    worker.resource_received = Mock(side_effect=reason)
    worker.error_occurred = Mock()

    queue = WorkQueue(loop=loop)
    await queue.put(app.metadata.uid, app)

    await asyncio.wait(
        [consume(queue, worker)], timeout=0.5, return_when=asyncio.FIRST_EXCEPTION
    )
    worker.error_occurred.assert_called_once_with(app, error=reason)
