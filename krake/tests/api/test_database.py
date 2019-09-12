import json
import factory

from krake.data import Key
from krake.data.serializable import Serializable
from krake.api.database import EventType

from factories import fake


class MyModel(Serializable):
    id: str
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


async def test_put(db, etcd_client, loop):
    data = MyModelFactory()
    await db.put(data)

    resp = await etcd_client.range(f"/model/{data.id}")

    assert len(resp.kvs) == 1
    assert resp.kvs[0].key.decode() == f"/model/{data.id}"

    value = json.loads(resp.kvs[0].value.decode())
    model = MyModel(**value)

    assert model.id == data.id
    assert model.name == data.name


async def test_get(db, etcd_client):
    data = MyModelFactory()
    await etcd_client.put(f"/model/{data.id}", json.dumps(data.serialize()))

    model, rev = await db.get(MyModel, id=data.id)

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

    deleted = await db.delete(data)
    assert deleted == 1

    resp = await etcd_client.range(f"/model/{data.id}")
    assert resp.kvs is None


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


async def aenumerate(iterable):
    i = 0

    async for item in iterable:
        yield i, item
        i += 1


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
