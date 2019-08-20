import asyncio
from unittest.mock import Mock

from factories.kubernetes import ApplicationFactory
from krake.controller import WorkQueue, consume


async def test_put_get_done():
    queue = WorkQueue()

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
