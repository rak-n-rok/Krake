import json
from collections import deque
from typing import NamedTuple
from enum import Enum, auto
from etcd3.aio_client import AioClient

from krake.data.serializable import serialize, deserialize


class Revision(NamedTuple):
    """
    Attributes:
        key (str): Key in the etcd database
        created (int): is the revision of last creation on this key.
        modified (int): is the revision of last modification on this key.
        version (int): is the version of the key. A deletion resets the
            version to zero and any modification of the key increases its
            version.
    """

    key: str
    created: int
    modified: int
    version: int

    @classmethod
    def from_kv(cls, kv):
        return cls(
            key=kv.key.decode(),
            created=kv.create_revision,
            modified=kv.mod_revision,
            version=kv.version,
        )


class Event(Enum):
    PUT = auto()
    DELETE = auto()


# class Model(Serializable):
#     pass


class Session(object):
    def __init__(self, host, port, loop=None):
        self.host = host
        self.port = port
        self.loop = loop
        self.client = None

    async def __aenter__(self):
        # FIXME: AioClient does not take "loop" as argument
        self.client = AioClient(host=self.host, port=self.port)
        return self

    async def __aexit__(self, *exc):
        await self.client.close()
        self.client = None

    async def get(self, cls, identity):
        key = f"{cls.__namespace__}/{identity}"
        resp = await self.client.range(key)

        if resp.kvs is None:
            return (None, None)

        return self.load_instance(cls, resp.kvs[0])

    async def all(self, cls):
        resp = await self.client.range(cls.__namespace__, prefix=True)
        if not resp.kvs:
            return []
        return [
            self.load_instance(cls, kv)[0]
            for kv in resp.kvs
            if in_namespace(cls.__namespace__, kv.key.decode())
        ]

    async def put(self, instance):
        identity = getattr(instance, instance.__identity__)
        data = serialize(instance)
        key = f"{instance.__namespace__}/{identity}"
        await self.client.put(key, json.dumps(data))
        # TODO: Should be we fetch the revision here with "prev_kv"?

    async def delete(self, instance):
        """
        Returns:
            int: Number of keys that where deleted
        """
        identity = getattr(instance, instance.__identity__)
        key = f"{instance.__namespace__}/{identity}"

        resp = await self.client.delete_range(key=key)
        return resp.deleted

    async def watch(self, cls, created=None):
        watcher = self.client.watch_create(key=cls.__namespace__, prefix=True)
        async with watcher:
            async for resp in watcher:
                if resp.events is None:
                    assert resp.created == True

                    # If a created future is passed, notify waiters that the
                    # watcher was created.
                    if created is not None:
                        created.set_result(True)
                else:
                    for event in resp.events:
                        # Resolve event type. Empty string means "PUT" event.
                        if event.type == "":
                            type_ = Event.PUT
                            value, rev = self.load_instance(cls, event.kv)
                        else:
                            assert event.type.name == "DELETE"
                            type_ = Event.DELETE
                            value = None
                            rev = Revision.from_kv(event.kv)

                        yield type_, value, rev

    def load_instance(self, cls, kv):
        value = json.loads(kv.value.decode())
        model = deserialize(cls, value)
        rev = Revision.from_kv(kv)

        return model, rev


def in_namespace(namespace, key):
    prefix, _ = key.rsplit("/", 1)
    return prefix == namespace
