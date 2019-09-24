import asyncio
from unittest.mock import Mock

import pytest
from factories.kubernetes import ApplicationFactory
from krake.controller import WorkQueue, consume


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

    assert len(queue.timers) == 0, "Timer was not deleted"

    assert (key, value) == ("key", 1)

    # The value should be received a bit after debounce time
    assert 1 < end - start < 1.1

    await queue.done("key")
    assert queue.empty()


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
