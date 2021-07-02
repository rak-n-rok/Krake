"""Database abstraction for etcd_. Key idea of the abstraction is to provide
an declarative way of defining persistent data structures (aka. "models")
together with a simple interface for loading and storing these data
structures.

This goal is achieved by leveraging the JSON-serializable data classes based
on :mod:`krake.data.serializable` and combining them with a simple database
session.

Example:
    .. code:: python

        from krake.api.database import Session
        from krake.data import Key
        from krake.data.serializable import Serializable


        class Book(Serializable):
            isbn: int
            title: str

            __etcd_key__ = Key("/books/{isbn}")


        async with Session(host="localhost") as session:
            book = await session.get(Book, isbn=9783453146976)

.. _etcd: https://etcd.io/

"""
import json
from typing import NamedTuple
from enum import Enum, auto
from etcd3 import Txn
from etcd3.aio_client import AioClient
from semantic_version import Version
import requests


class DatabaseError(Exception):
    pass


class TransactionError(DatabaseError):
    pass


class Revision(NamedTuple):
    """Etcd revision of a loaded key-value pair.

    Etcd stores all keys in a flat binary key space. The key space has a
    lexically sorted index on byte string keys. The key space maintains
    multiple revisions of the same key. Each atomic mutative operation (e.g.,
    a transaction operation may contain multiple operations) creates a new
    revision on the key space.

    Every :meth:`Session.get` request returns also the revision besides the
    model.

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


class EventType(Enum):
    """Different types of events that can occur during
    :meth:`Session.watch`.
    """

    PUT = auto()
    DELETE = auto()


class Event(NamedTuple):
    """Events that are yielded by :meth:`Session.watch`

    Attributes:
        event (EventType): Type of event that occurred (PUT or DELETE)
        value (object, None): Deserialized object. None if the event is of
            kind DELETE.
        rev (Revision): Revision of the object
    """

    event: EventType
    value: object
    rev: Revision


class EtcdClient(AioClient):
    """Async etcd v3 client based on :class:`etcd3.aio_client.AioClient` with
    some minor patches.
    """

    def _retrieve_version(self):
        # FIXME: The base implementation swallows every exception and just
        #   emits a warning. We want to retrieve the whole exception.
        #
        #   The current implementation is synchronous because it is executed
        #   in the constructor which is very ugly! Because we consider moving
        #   to an gRPC-based etcd client, we should not invest too much effort
        #   into fixing this problem.
        #
        #   When this is fixed, requests should be removed from the setup.py
        resp = requests.get(
            self._url("/version", prefix=False),
            cert=self.cert,
            verify=self.verify,
            timeout=0.3,  # 300ms will do
            headers=self.headers,
        )
        resp.raise_for_status()
        version = resp.json()
        self.server_version = version["etcdserver"]
        self.cluster_version = version["etcdcluster"]

        self.cluster_version_sem = Version(self.cluster_version)
        self.server_version_sem = Version(self.server_version)


class Session(object):
    """Database session for managing
    :class:`krake.data.serializable.Serializable` objects in an etcd database.

    The serializable objects need have one additional attribute:

    __etcd_key__
        A :class:`krake.data.Key` template for the associated etcd key of a
        managed object.

    Objects managed by a session have an attached etcd :class:`Revision` when
    loaded from the database. This revision can be read by :func:`revision`.
    If an object has no revision attached, it is considered *fresh* or *new*.
    It is expected that the associated key of a *new* object does not already
    exist in the database.

    The session is an asynchronous context manager. It takes of care of
    opening and closing an HTTP session to the gRPC JSON gateway of the etcd
    server.

    The etcd v3 protocol is documented by its `protobuf definitions`_.

    Example:
        .. code:: python

            async with Session(host="localhost") as session:
                pass

    Args:
        host (str): Hostname of the etcd server
        port (int, optional): Client port of the etcd server
        loop (async.AbstractEventLoop, optional): asyncio event loop that
            should be used

    .. _protobuf definitions: https://etcd.io/docs/v3.3.12/dev-guide/api_reference_v3/

    """

    def __init__(self, host, port=2379, loop=None):
        self.host = host
        self.port = port
        self.loop = loop
        self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def client(self):
        """Lazy loading of the etcd client. It is only created when the first request is
        performed.

        Returns:
            EtcdClient: the client to connect to the database.
        """
        # It allows for the API to be started without any connection to the database.
        # Without this lazy loading, when the API is started, if the connection is not
        # possible, the API will raise an exception and stop, as the connection is
        # created at startup.
        # With the lazy loading, the API can be started. A future request will attempt
        # the creation of the client. If an issue occurs then, the exception will be
        # raised, the client will not be created, and will be created in another
        # attempt, if the database is now accessible.
        # As long as the client has been created once, a disconnection from the
        # database will raise an exception, but not stop the API.
        if not self._client:
            # FIXME: AioClient does not take "loop" as argument
            self._client = EtcdClient(host=self.host, port=self.port)

        return self._client

    async def get(self, cls, **kwargs):
        """Fetch an serializable object from the etcd server specified by its
        identity attribute.

        Attributes:
            cls (type): Serializable class that should be loaded
            **kwargs: Parameters for the etcd key

        Returns:
            object, None: Deserialized model with attached revision. If
            the key was not found in etcd, None is returned.

        """
        key = cls.__etcd_key__.format_kwargs(**kwargs)
        return await self.get_by_key(cls, key)

    async def get_by_key(self, cls, key, revision=None):
        resp = await self.client.range(key, revision=revision)

        if resp.kvs is None:
            return None

        return self.load_instance(cls, resp.kvs[0])

    async def all(self, cls, **kwargs):
        """Fetch all instances of a given type

        The instances can be filtered by partial identities. Every identity can
        be specified as keyword argument and only instances with this
        identity attribute are returned. The only requirement for a filtered
        identity attribute is that all preceding identity attributes must
        also be given.

        Example:
            .. code:: python

                class Book(Serializable):
                    isbn: int
                    title: str
                    author: str

                    __metadata__ = {
                        "key": Key("/books/{author}/{isbn}")
                    }

                await db.all(Book)

                # Get all books by Adam Douglas
                await db.all(Book, author="Adam Douglas")

                # This will raise a TypeError because the preceding "name"
                # attribute is not given.
                await db.all(Book, isbn=42)

        Args:
            cls (type): Serializable class that should be loaded
            **kwargs: Parameters for the etcd key

        Yields:
            (object, Revision): Tuple of deserialized model and revision

        Raises:
            TypeError: If an identity attribute is given without all preceding
                identity attributes.

        """
        key = cls.__etcd_key__.prefix(**kwargs)
        # TODO: Support pagination
        resp = await self.client.range(key, prefix=True)
        if not resp.kvs:
            return

        for kv in resp.kvs:
            if cls.__etcd_key__.matches(kv.key.decode()):
                yield self.load_instance(cls, kv)

    async def put(self, instance):
        """Store new revision of a serializable object on etcd server.

        If the instances does not have an attached :class:`Revision` (see
        :func:`revision`), it is assumed that a key-value pair should be
        *created*. Otherwise, it is assumed that the key-value pair is
        updated.

        A transaction ensures that

        a) the etcd key was not modified in-between if the key is updated
        b) the key does not already exists if a key is added

        If the transaction is successful, the revision of the instance will
        updated to the revision returned by the transaction response.

        Args:
            instance (krake.data.serializable.Serializable): Serializable object that
            should be stored.

        Raise:
            TransactionError: If the key was modified in between or already
                exists

        """
        key = instance.__etcd_key__.format_object(instance)
        value = json.dumps(instance.serialize())
        rev = revision(instance)

        txn = Txn(self.client)
        txn.success(txn.put(key, value))

        if rev is None or rev.version == 0:
            # Create new key. Ensure the key does not exist.
            txn.compare(txn.key(key).create == 0)
        else:
            # Update existing key. Ensure the key was not modified.
            txn.compare(txn.key(key).mod == rev.modified)

        resp = await txn.commit()

        if not resp.succeeded:
            if rev is None:
                raise TransactionError("Key already exists")
            raise TransactionError("Key was modified")

        # Update revision
        if rev is None or rev.version == 0:
            instance.__revision__ = Revision(
                key=key,
                created=resp.header.revision,
                modified=resp.header.revision,
                version=1,
            )
        else:
            instance.__revision__ = rev._replace(
                modified=resp.header.revision, version=rev.version + 1
            )

    async def delete(self, instance):
        """Delete a given instance from etcd.

        A transaction is used ensuring the etcd key was not modified
        in-between. If the transaction is successful, the revision of the
        instance will be updated to the revision returned by the transaction
        response.

        Args:
            instance (object): Serializable object that should be deleted

        Raises:
            ValueError: If the passed object has no revision attached.
            TransactionError: If the key was modified in between

        """
        key = instance.__etcd_key__.format_object(instance)
        rev = revision(instance)

        if rev is None:
            raise ValueError(f"{instance!r} has no revision")

        txn = Txn(self.client)
        txn.compare(txn.key(key).mod == rev.modified)
        txn.success(txn.delete(key))

        resp = await txn.commit()

        if not resp.succeeded:
            raise TransactionError("Key was modified")

        instance.__revision__ = rev._replace(modified=resp.header.revision, version=0)

    def watch(self, cls, **kwargs):
        """Watch the namespace of a given serializable type and yield
        every change in this namespace.

        Internally, it uses the etcd watch API. The ``created`` future can be
        used to signal successful creation of an etcd watcher.

        Args:
            cls (type): Serializable type of which the namespace should be
                watched
            **kwargs: Parameters for the etcd key

        Yields:
            Event: Every change in the namespace will generate an event

        """
        return Watcher(self, cls, **kwargs)

    def load_instance(self, cls, kv):
        """Load an instance and its revision by an etcd key-value pair

        Args:
            cls (type): Serializable type
            kv: etcd key-value pair

        Returns:
            object: Deserialized model with attached revision
        """
        value = json.loads(kv.value.decode())
        model = cls.deserialize(value)
        model.__revision__ = Revision.from_kv(kv)

        return model


def revision(instance):
    """Returns the etcd :class:`Revision` of an object used with a
    :class:`Session`. If the object is currently *unattached* -- which means it
    was not retrieved from the database with :meth:`Session.get` -- this function
    returns :obj:`None`.

    Args:
        instance (object): Object used with :class:`Session`.

    Returns:
        Revision, None: The current etcd revision of the instance.

    """
    return getattr(instance, "__revision__", None)


class Watcher(object):
    """Async context manager for database watching requests.

    This context manager is used internally by :meth:`Session.watch`. It
    returns a async generator on entering. It is ensured that the watch is
    created on entering. This means inside the context, it can be assumed that
    the watch exists.

    Args:
        session (Session): Database session doing the watch request
        model (type): Class that is loaded from database
        **kwargs (dict): Keyword arguments that are used to generate the
            etcd key prefix (:meth:`Key.prefix`)

    """

    def __init__(self, session, model, **kwargs):
        self.session = session
        self.model = model
        self.prefix = model.__etcd_key__.prefix(**kwargs)
        self.response = None
        self.watch_id = None

    async def __aenter__(self):
        self.response = self.session.client.watch_create(key=self.prefix, prefix=True)

        # Receiving "created" response
        async for resp in self.response:
            assert resp.created
            assert resp.events is None
            self.watch_id = resp.watch_id
            break

        return self.watch()

    async def __aexit__(self, *exc):
        self.response.close()
        self.response = None
        self.watch_id = None

    async def watch(self):
        """Async generator for watching database prefix.

        Yields:
            Event: Database event holding the loaded model (see ``model``
                argument) and database revision.

        """
        async for resp in self.response:
            assert resp.watch_id == self.watch_id

            for event in resp.events:
                if self.model.__etcd_key__.matches(event.kv.key.decode()):
                    # Resolve event type. Empty string means "PUT" event.
                    if event.type == "":
                        type_ = EventType.PUT
                        value = self.session.load_instance(self.model, event.kv)
                        rev = revision(value)
                    else:
                        assert event.type.name == "DELETE"
                        type_ = EventType.DELETE
                        value = None
                        rev = Revision.from_kv(event.kv)

                    yield Event(type_, value, rev)
