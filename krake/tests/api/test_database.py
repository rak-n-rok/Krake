import json
from dataclasses import field
import factory
import pytest

from krake.data import Key
from krake.data.serializable import Serializable
from krake.api.database import EventType, Revision, revision, TransactionError
from krake.test_utils import aenumerate

from tests.factories import fake


class MyModel(Serializable):
    id: str = field(metadata={"immutable": True})
    name: str

    __etcd_key__ = Key("/model/{id}")


class MyModelFactory(factory.Factory):
    class Meta:
        model = MyModel

    id = factory.fuzzy.FuzzyAttribute(fake.uuid4)
    name = factory.Sequence(lambda n: f"model-{n}")


def test_deserialize():
    data = MyModelFactory()
    value = data.serialize()
    model = MyModel.deserialize(value)

    assert isinstance(model, MyModel)
    assert model.id == data.id
    assert model.name == data.name


async def test_put_add(db, etcd_client, loop):
    data = MyModelFactory()
    await db.put(data)
    rev = revision(data)

    resp = await etcd_client.range(f"/model/{data.id}")

    assert len(resp.kvs) == 1
    assert resp.kvs[0].key.decode() == f"/model/{data.id}"
    assert rev == Revision.from_kv(resp.kvs[0])
    assert rev.version == 1

    value = json.loads(resp.kvs[0].value.decode())
    model = MyModel(**value)

    assert model.id == data.id
    assert model.name == data.name


async def test_put_key_already_exists(db, etcd_client):
    data = MyModelFactory()
    await etcd_client.put(f"/model/{data.id}", "already existing")

    with pytest.raises(TransactionError):
        await db.put(data)

    assert revision(data) is None


async def test_put_update(db, etcd_client, loop):
    data = MyModelFactory()

    await db.put(data)  # Insert first version

    # Make changes and put second version
    data.name = "updated name"
    await db.put(data)
    rev = revision(data)

    resp = await etcd_client.range(f"/model/{data.id}")

    assert len(resp.kvs) == 1
    assert resp.kvs[0].key.decode() == f"/model/{data.id}"
    assert rev == Revision.from_kv(resp.kvs[0])
    assert rev.version == 2

    value = json.loads(resp.kvs[0].value.decode())
    model = MyModel(**value)

    assert model.id == data.id
    assert model.name == data.name


async def test_put_modified_key(db, etcd_client):
    data = MyModelFactory()
    await db.put(data)  # Insert first version

    # Put second version in-between
    await etcd_client.put(f"/model/{data.id}", "intermediate change")

    # Make changes and try to update which should raise an transaction error
    # because the key was modified.
    data.name = "updated name"
    with pytest.raises(TransactionError):
        await db.put(data)


async def test_get(db, etcd_client):
    data = MyModelFactory()
    await etcd_client.put(f"/model/{data.id}", json.dumps(data.serialize()))

    model = await db.get(MyModel, id=data.id)
    rev = revision(model)

    assert rev.version == 1
    assert rev.key == f"/model/{data.id}"
    assert isinstance(model, MyModel)
    assert model.id == data.id
    assert model.name == data.name


async def test_all(db, etcd_client):
    data = [MyModelFactory() for _ in range(10)]

    for instance in data:
        await db.put(instance)

    models = [model async for model in db.all(MyModel)]

    assert len(models) == 10


async def test_delete(db, etcd_client):
    data = MyModelFactory()
    await db.put(data)
    old_rev = revision(data)

    await db.delete(data)
    rev = revision(data)

    assert rev.version == 0
    assert rev.modified == old_rev.modified + 1
    assert rev.created == old_rev.created

    resp = await etcd_client.range(f"/model/{data.id}")
    assert resp.kvs is None


async def test_delete_key_modified(db, etcd_client):
    data = MyModelFactory()
    await db.put(data)

    # Modify in between
    await etcd_client.put(f"/model/{data.id}", "intermediate change")

    with pytest.raises(TransactionError):
        await db.delete(data)


async def test_delete_and_add(db, etcd_client):
    data = MyModelFactory()
    await db.put(data)

    await db.delete(data)

    await db.put(data)
    rev = revision(data)

    assert rev.version == 1


async def test_watching_create(db, loop):
    data = [MyModelFactory() for _ in range(10)]
    watched = []

    async def create():
        for model in data:
            await db.put(model)

    async with db.watch(MyModel) as watcher:
        creating = loop.create_task(create())

        async for event, model, rev in watcher:
            assert event == EventType.PUT
            assert rev.version == 1
            watched.append(model)

            if len(watched) == len(data):
                break

        await creating

    assert data == watched


async def test_watching_update(db, loop):
    names = [fake.pystr(), fake.pystr(), fake.pystr()]
    data = MyModelFactory(name=names[0])

    async def modify():
        # Insert model into database
        await db.put(data)

        # Modify name
        data.name = names[1]
        await db.put(data)

        data.name = names[2]
        await db.put(data)

        await db.delete(data)

    async with db.watch(MyModel) as watcher:
        modifying = loop.create_task(modify())

        async for i, (event, model, rev) in aenumerate(watcher):
            if i == 0:
                assert event == EventType.PUT
                assert model.id == data.id
                assert model.name == names[0]
                assert rev.version == 1

            elif i == 1:
                assert event == EventType.PUT
                assert model.id == data.id
                assert model.name == names[1]
                assert rev.version == 2

            elif i == 2:
                assert event == EventType.PUT
                assert model.id == data.id
                assert model.name == names[2]
                assert rev.version == 3

            elif i == 3:
                assert event == EventType.DELETE
                assert model is None
                assert rev.version == 0
                break

        await modifying


async def test_update(db):
    original = MyModelFactory()
    await db.put(original)

    rev = revision(original)
    original_id = original.id

    overwrite = MyModelFactory(id=original_id)
    assert revision(overwrite) is None

    original.update(overwrite)

    assert revision(original) is rev
    assert original_id == original.id
    assert original.name == overwrite.name
