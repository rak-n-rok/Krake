import uuid
import json
import asyncio
import pytest
import factory
from factory.fuzzy import FuzzyInteger

from krake.data.serializable import Serializable, serialize, deserialize
from krake.api.database import EventType, Key

from factories import fake


class MyModel(Serializable):
    id: str
    name: str
    kind: str = "my-model"

    __metadata__ = {"key": Key("/model/{id}"), "discriminator": "kind"}


class AnotherModel(MyModel):
    number: int
    kind: str = "another-model"


class MyModelFactory(factory.Factory):
    class Meta:
        model = MyModel

    @factory.lazy_attribute
    def id(self):
        return uuid.uuid4().hex

    name = factory.Sequence(lambda n: f"model-{n}")


class AnotherModelFactory(MyModelFactory):
    class Meta:
        model = AnotherModel

    number = FuzzyInteger(0, 42)


def test_deserialize():
    data = MyModelFactory()
    value = serialize(data)
    model = deserialize(MyModel, value)

    assert isinstance(model, MyModel)
    assert model.id == data.id
    assert model.name == data.name
    assert model.kind == data.kind


def test_polymorphic_deserialize():
    data = AnotherModelFactory()
    value = serialize(data)

    model = deserialize(MyModel, value)
    assert isinstance(model, MyModel)
    assert model.id == data.id
    assert model.name == data.name
    assert model.kind == data.kind
    assert model.number == data.number


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
    await etcd_client.put(f"/model/{data.id}", json.dumps(serialize(data)))

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


async def test_get_polymorphic(db, etcd_client):
    class App(Serializable):
        id: int
        name: str
        kind: str = "app"

        __metadata__ = {
            "key": Key("/apps/{id}"),
            "identity": ("id",),
            "discriminator": "kind",
        }

    class SpecificApp(App):
        kind: str = "specific-app"
        attr: str = "default"

    app = App(id=42, name=fake.name())
    await db.put(app)

    instance, rev = await db.get(App, id=42)
    assert isinstance(instance, App)
    assert rev.version == 1

    app = SpecificApp(id=43, name=fake.name())
    await db.put(app)
    assert rev.version == 1

    instance, rev = await db.get(App, id=43)
    assert isinstance(instance, SpecificApp)


async def test_watching_create(db, loop):
    data = [MyModelFactory() for _ in range(10)]
    watched = []
    created = loop.create_future()

    async def create():
        # Wait for the watcher to be created
        await created

        for model in data:
            await db.put(model)

    async def watch():
        async for event, model, rev in db.watch(MyModel, created=created):
            assert event == EventType.PUT
            assert rev.version == 1
            watched.append(model)

            if len(watched) == len(data):
                break

    creating = loop.create_task(create())
    watching = loop.create_task(watch())

    await creating
    await watching

    assert data == watched


async def aenumerate(iterable):
    i = 0

    async for item in iterable:
        yield i, item
        i += 1


async def test_watching_update(db, loop):
    names = [fake.pystr(), fake.pystr(), fake.pystr()]
    data = MyModelFactory(name=names[0])
    created = loop.create_future()

    async def modify():
        # Wait for the watcher to be created
        await created

        # Insert model into database
        await db.put(data)

        # Modify name
        data.name = names[1]
        await db.put(data)

        data.name = names[2]
        await db.put(data)

        await db.delete(data)

    async def watch():
        watcher = db.watch(MyModel, created=created)

        async for i, (event, model, rev) in aenumerate(watcher):
            if i == 0:
                assert event == EventType.PUT
                assert model.id == data.id
                assert model.kind == data.kind
                assert model.name == names[0]
                assert rev.version == 1

            elif i == 1:
                assert event == EventType.PUT
                assert model.id == data.id
                assert model.kind == data.kind
                assert model.name == names[1]
                assert rev.version == 2

            elif i == 2:
                assert event == EventType.PUT
                assert model.id == data.id
                assert model.kind == data.kind
                assert model.name == names[2]
                assert rev.version == 3

            elif i == 3:
                assert event == EventType.DELETE
                assert model is None
                assert rev.version == 0
                break

    modifying = loop.create_task(modify())
    watching = loop.create_task(watch())

    await modifying
    await watching
