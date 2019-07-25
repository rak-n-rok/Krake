from etcd3.models import EventEventType


async def test_read_write_delete(etcd_client):
    await etcd_client.put("/foo", "bar")
    await etcd_client.range("/foo")

    resp = await etcd_client.put("/foo", "baz", prev_kv=True)
    assert resp.prev_kv.value == b"bar"

    resp = await etcd_client.delete_range("/foo", prev_kv=True)
    assert len(resp.prev_kvs) == 1
    assert resp.prev_kvs[0].key == b"/foo"
    assert resp.prev_kvs[0].value == b"baz"


async def test_watch(etcd_client, loop):
    async def put_key(created):
        await created
        await etcd_client.put("/foo", "bar")
        await etcd_client.put("/foo", "baz")
        await etcd_client.delete_range("/foo")

    events = []
    created = loop.create_future()
    task = loop.create_task(put_key(created))

    # Gather all events
    async for resp in etcd_client.watch_create("/foo"):
        if not created.done():
            assert resp.created
            created.set_result(True)
            if resp.events:
                events.extend(resp.events)
        else:
            events.extend(resp.events)

        if len(events) == 3:
            break

    await task

    assert events[0].type == ""
    assert events[1].type == ""
    assert events[2].type == EventEventType.DELETE
