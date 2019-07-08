"""Database abstraction for etcd_. Key idea of the abstraction is to provide
an declarative way of defining persistent data structures (aka. "models")
together with a simple interface for loading and storing these data
structures.

This goal is achieved by leveraging the JSON-serializable data classes based
on :mod:`krake.data.serializable` and combining them with a simple database
session.

Example:
    .. code:: python

        from krake.api.database import Session, Key
        from krake.data.serialzable import Serializable


        class Book(Serializable):
            isbn: int
            title: str

            __metadata__ = {
                "key": Key("/books/{isbn}")
            }


        async with Session(host="localhost") as session:
            book, revision = await session.get(Book, isbn=9783453146976)

.. _ etcd: https://etcd.io/

"""
import json
from collections import deque
from typing import NamedTuple
from enum import Enum, auto
import re
from operator import itemgetter
from etcd3.aio_client import AioClient

from krake.data.serializable import serialize, deserialize


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
        event (EventType): Type of event that occured (PUT or DELETE)
        value (object, None): Deserialized object. None if the event is of
            kind DELETE.
        rev (Revision): Revision of the object
    """

    event: EventType
    value: object
    rev: Revision


class Session(object):
    """Database session for loading and loading serializable objects in
    an etcd database.

    The term "serializable object" refers to objects supporting the
    :func:`krake.data.serialize` and :func:`krake.data.deserialize` functions.
    In additional to that, two keys are required in the special
    ``__metadata__`` attribute of models:

    namespace:
        Defines the etcd key prefix
    identity:
        Is a tuple defining the name of the attributes that should used as
        identifier for an object.

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
        self.client = None

    async def __aenter__(self):
        # FIXME: AioClient does not take "loop" as argument
        self.client = AioClient(host=self.host, port=self.port)
        return self

    async def __aexit__(self, *exc):
        await self.client.close()
        self.client = None

    async def get(self, cls, **kwargs):
        """Fetch an serializable object from the etcd server specified by its
        identity attribute.

        Attributes:
            cls (type): Serializable class that should be loaded
            **kwargs: Parameters for the etcd key

        Returns:
            (object, Revision): Tuple of deserialized model and revision. If
            the key was not found in etcd (None, None) is returned.
        """
        key = create_key(cls, **kwargs)
        resp = await self.client.range(key)

        if resp.kvs is None:
            return (None, None)

        return self.load_instance(cls, resp.kvs[0])

    async def all(self, cls, **kwargs):
        """Fetch all instances of a given type

        The instances can be filtered by partial identites. Every identity can
        be specified as keyword argument and only instances with this
        idenenity attribute are returned. The only requirement for a filtered
        identity attribute is that all preceeding identity attributes must
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
            TypeError: If an identity attribute is given without all preceeding
                identity attributes.

        """
        key = create_prefix(cls, **kwargs)
        # TODO: Support pagination
        resp = await self.client.range(key, prefix=True)
        if not resp.kvs:
            return

        for kv in resp.kvs:
            if matches_key(cls, kv.key.decode()):
                yield self.load_instance(cls, kv)

    async def put(self, instance, **kwargs):
        """Store new revision of a serializable object on etcd server.

        Args:
            instance (object): Serializable object that should be stored
            **kwargs: Additional parameters for the etcd key

        Returns:
            int: key-value revision version when the request was applied

        """
        key = create_key(instance, **kwargs)
        data = serialize(instance)
        resp = await self.client.put(key, json.dumps(data))
        return resp.header.revision
        # TODO: Should be we fetch the previous revision here with "prev_kv"?

    async def delete(self, instance, **kwargs):
        """Delete a given instance from etcd

        Args:
            instance (object): Serializable object that should be deleted
            **kwargs: Additional parameters for the etcd key

        Returns:
            int: Number of keys that where deleted

        """
        key = create_key(instance, **kwargs)
        resp = await self.client.delete_range(key=key)
        return resp.deleted

    async def watch(self, cls, created=None, **kwargs):
        """Watch the namespace of a given serializable type and yield
        every change in this namespace.

        Internally, it uses the etcd watch API. The ``created`` future can be
        used to signal succesful creation of an etcd watcher.

        Args:
            cls (type): Serializable type of which the namespace should be
                watched
            created (asyncio.Future, optional): Future that will be set
                if the watcher was succesfully created.
            **kwargs: Parameters for the etcd key

        Yields:
            Event: Every change in the namespace will generate an event

        """
        prefix = create_prefix(cls, **kwargs)
        watcher = self.client.watch_create(key=prefix, prefix=True)
        async with watcher:
            async for resp in watcher:
                if resp.events is None:
                    assert resp.created == True

                    # If a created future is passed, notify waiters that the
                    # watcher was created.
                    if created is not None:
                        created.set_result(None)
                else:
                    for event in resp.events:
                        if matches_key(cls, event.kv.key.decode()):
                            # Resolve event type. Empty string means "PUT"
                            # event.
                            if event.type == "":
                                type_ = EventType.PUT
                                value, rev = self.load_instance(cls, event.kv)
                            else:
                                assert event.type.name == "DELETE"
                                type_ = EventType.DELETE
                                value = None
                                rev = Revision.from_kv(event.kv)

                            yield Event(type_, value, rev)

    def load_instance(self, cls, kv):
        """Load an instance and its revision by an etcd key-value pair

        Args:
            cls (type): Serializable type
            kv: etcd key-value pair

        Returns:
            (object, Revision): Tuple of deserialized model and revision
        """
        value = json.loads(kv.value.decode())
        model = deserialize(cls, value)
        rev = Revision.from_kv(kv)

        return model, rev


class Key(object):
    """Etcd key template that

    The string template uses the same syntax as Python's standard format
    strings for parameters:

    .. code:: python

        key = Key("/books/{namespaces}/{isbn}")

    The parameters are substituted by in the corresponding methods by either
    attributes of the passed object or additional keyword arguments.

    Args:
        template (str): Key template with format string-like parameters

    """
    _params_re = re.compile(r"\{(.+?)\}")

    def __init__(self, template):
        self.template = template
        self.parameters = list(self._params_re.finditer(template))

        template_re = self._params_re.sub(".+?", template)
        self.pattern = re.compile(fr"^{template_re}$")

    def matches(self, key):
        """Check if a given key matches the template

        Args:
            key (str): Key that should be checked

        Returns:
            bool: True of the given key matches the key template
        """
        return self.pattern.match(key) is not None

    def create(self, obj, **kwargs):
        """Create a key for an object

        Args:
            obj: Object from which attributes are looked up
            **kwargs: Additional parameters that will be used if a parameter
                cannot loaded as attribute from the given object.

        Returns:
            str: Key from the key template with all parameters substituted by
            either attributes or keyword arguments.

        Raises:
            TypeError: If a required parameter is missing or an unexpected
                keyword is passed.
        """
        params = {}

        for param in map(itemgetter(1), self.parameters):
            try:
                params[param] = getattr(obj, param)
            except AttributeError:
                try:
                    params[param] = kwargs.pop(param)
                except KeyError:
                    raise TypeError(f"Missing key parameter {param!r}")

        if kwargs:
            key, _ = kwargs.popitem()
            raise TypeError(f"Got unexpected key parameter {key!r}")

        return self.template.format(**params)

    def prefix(self, obj, **kwargs):
        """Create a partial key (prefix) for a given object.

        Args:
            obj: Object from which attributes are looked up
            **kwargs: Additional parameters that will be used if a parameter
                cannot loaded as attribute from the given object.

        Returns:
            str: Partial key from the key template with some parameters
            substituted by either attributes or keyword arguments.

        Raises:
            TypeError: If a parameter is passed as keyword argument but a
                preceding parameter is not given.

        """
        template = self.template
        params = {}

        for match in self.parameters:
            try:
                params[match[1]] = getattr(obj, match[1])
            except AttributeError:
                try:
                    params[match[1]] = kwargs.pop(match[1])
                except KeyError:
                    template = match.string[:match.start()]
                    break

        if kwargs:
            key, _ = filters.popitem()
            raise TypeError(
                f"Got parameter {key!r} without preceding parameter {match[1]!r}"
            )

        return template.format(**params)


def matches_key(cls, key):
    """Check if a given string matches they key of a class

    Args:
        cls (type): Class with ``__metadata__["key"]`` attribute
        key (str): String that should be matched

    Returns:
        bool: True if the key matches the key of the class
    """
    return cls.__metadata__["key"].matches(key)


def create_key(obj, **kwargs):
    """Create a key from a key template of an object

    Args:
        obj: Object providing a key template in ``__metadata__["key"]``
        **kwargs: Keyword arguments that will be used for parameter
            substitution in the key template

    Returns:
        str: Key generated from the key template of the object with all
        parameters replaced by keyword arguments.
    """
    return obj.__metadata__["key"].create(obj, **kwargs)


def create_prefix(obj, **kwargs):
    """Create a prefix key from a key template of an object

    Args:
        obj: Object providing a key template in ``__metadata__["key"]``
        **kwargs: Keyword arguments that will be used for parameter
            substitution in the key template

    Returns:
        str: Prefix key generated from the key template of the object with some
        parameters replaced by keyword arguments.
    """
    return obj.__metadata__["key"].prefix(obj, **kwargs)
