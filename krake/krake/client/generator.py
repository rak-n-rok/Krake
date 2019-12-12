"""This module provides a decorator for generating Krake API clients based on
API definitions (see :mod:`krake.apidefs`).
"""
import json
from string import Formatter
from inspect import Signature, Parameter
from makefun import with_signature
from aiohttp.client_exceptions import ClientPayloadError
from aiohttp.client import ClientTimeout

from krake.data.core import WatchEvent
from ..apidefs.definitions import Scope
from ..utils import camel_to_snake_case, get_field


def generate_client(apidef):
    """Decorator function for generating API clients.

    The decorator generates default methods based on the operations and
    subresources of the passed API definition. All default methods can be
    overwritten by defining methods with the same name.

    The methods will generated for every resource in the API definition and
    will be named according to the following schema:

    ``{operation.name}_{resource.singular | resource.plural based on operation.number}``

    All names are converted into *snake_case*.

    The following table shows some examples for the ``Book`` API example (see
    :mod:`krake.apidefs.definitions``).

    +-----------+----------------+
    | Operation | Method         |
    +===========+================+
    | Create    | create_book    |
    +-----------+----------------+
    | List      | list_books     |
    +-----------+----------------+
    | ListAll   | list_all_books |
    +-----------+----------------+
    | Read      | read_book      |
    +-----------+----------------+
    | Update    | update_book    |
    +-----------+----------------+
    | Delete    | delete_book    |
    +-----------+----------------+

    Examples:
        .. code:: python

            from krake.client.generator import generate_client
            from krake.apidefs.book import book

            @generate_client(book)
            class BookApi:

                def list_books(self, namespace):
                    # Custom implementations here ...
                    pass

        The API objects are used together with a client:

        .. code:: python

            from krake.client import Client

            with Client(url="http://localhost:8080") as client:
                book_api = BookApi(client)

    Args:
        apidef (krake.apidefs.ApiDef): API definition that is handled by this
            client.

    Returns:
        callable: Decorator generating default resource handler methods

    """

    def decorator(cls):
        for resource in apidef.resources:
            create_resource_handlers(resource, cls)

            for subresource in resource.subresources:
                create_subresource_handlers(subresource, cls)

        if cls.__init__ == object.__init__:
            cls.__init__ = init_client

        if not cls.__doc__:
            cls.__doc__ = make_class_docstring(apidef, cls)

        cls.api_name = apidef.name
        return cls

    return decorator


def init_client(self, client):
    self.client = client


def make_class_docstring(apidef, cls):
    return f"""{apidef.name.title()} API client

Example:
    .. code:: python

        from krake.client import Client

        with Client(url="http://localhost:8080") as client:
            {apidef.name.lower()}_api = {cls.__name__}(client)

Args:
    client (krake.client.Client): API client for accessing the Krake HTTP API

"""


def create_resource_handlers(resource, cls):
    """Create resource handlers for a given resource of an API

    Args:
        resource (krake.apidefs.Resource): Resource handlers are created
            for
        cls (type): the handlers will be added to this client class.

    """
    for operation in resource.operations:
        if operation.name == "Create":
            name = f"create_{camel_to_snake_case(resource.singular)}"
            if not hasattr(cls, name):
                doc = make_docstring(operation, f"Create specified {resource.singular}")
                handler = make_create_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "List":
            name = f"list_{camel_to_snake_case(resource.plural)}"
            if not hasattr(cls, name):
                if resource.scope == Scope.NAMESPACED:
                    description = f"List {resource.plural} in the namespace"
                else:
                    description = f"List all {resource.plural}"
                doc = make_docstring(operation, description)
                handler = make_list_handler(operation, doc)
                setattr(cls, name, handler)

            name = f"watch_{camel_to_snake_case(resource.plural)}"
            if not hasattr(cls, name):
                if resource.scope == Scope.NAMESPACED:
                    description = f"Watch {resource.plural} in the namespace"
                else:
                    description = f"Watch all {resource.plural}"
                doc = make_docstring(operation, description, {"heartbeat"})
                handler = make_watch_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "ListAll":
            name = f"list_all_{camel_to_snake_case(resource.plural)}"
            if not hasattr(cls, name):
                doc = make_docstring(
                    operation, f"List {resource.plural} in all namespaces"
                )
                handler = make_list_all_handler(operation, doc)
                setattr(cls, name, handler)

            name = f"watch_all_{camel_to_snake_case(resource.plural)}"
            if not hasattr(cls, name):
                doc = make_docstring(
                    operation,
                    f"Watch {resource.plural} in all namespaces",
                    {"heartbeat"},
                )
                handler = make_watch_all_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "Read":
            name = f"read_{camel_to_snake_case(resource.singular)}"
            if not hasattr(cls, name):
                doc = make_docstring(operation, f"Read specified {resource.singular}")
                handler = make_read_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "Update":
            name = f"update_{camel_to_snake_case(resource.singular)}"
            if not hasattr(cls, name):
                doc = make_docstring(operation, f"Update specified {resource.singular}")
                handler = make_update_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "Delete":
            name = f"delete_{camel_to_snake_case(resource.singular)}"
            if not hasattr(cls, name):
                doc = make_docstring(operation, f"Delete specified {resource.singular}")
                handler = make_delete_handler(operation, doc)
                setattr(cls, name, handler)

        else:
            if operation.number == "singular":
                resource_name = camel_to_snake_case(resource.singular)
            else:
                resource_name = camel_to_snake_case(resource.plural)
            opname = camel_to_snake_case(operation.name)
            name = f"{opname}_{resource_name}"

            if not hasattr(cls, name):
                raise NotImplementedError(
                    f"Generator for operation {operation!r} not implemented"
                )


def create_subresource_handlers(subresource, cls):
    resource = subresource.resource

    for operation in subresource.operations:
        if operation.name == "Create":
            name = (
                f"create_{camel_to_snake_case(resource.singular)}"
                f"_{camel_to_snake_case(subresource.name)}"
            )
            if not hasattr(cls, name):
                doc = make_docstring(
                    operation,
                    f"Create {subresource.name} of specified {resource.singular}",
                )
                handler = make_create_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "List":
            name = (
                f"list_{camel_to_snake_case(resource.plural)}"
                f"_{camel_to_snake_case(subresource.name)}"
            )
            if not hasattr(cls, name):
                doc = make_docstring(
                    operation,
                    f"List {subresource.name} of specified {resource.singular}",
                )
                handler = make_list_handler(operation, doc)
                setattr(cls, name, handler)

            name = (
                f"watch_{camel_to_snake_case(resource.plural)}"
                f"_{camel_to_snake_case(subresource.name)}"
            )
            if not hasattr(cls, name):
                handler = make_watch_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "Read":
            name = (
                f"read_{camel_to_snake_case(resource.singular)}"
                f"_{camel_to_snake_case(subresource.name)}"
            )
            if not hasattr(cls, name):
                doc = make_docstring(
                    operation,
                    f"Read {subresource.name} of specified {resource.singular}",
                )
                handler = make_read_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "Update":
            name = (
                f"update_{camel_to_snake_case(resource.singular)}"
                f"_{camel_to_snake_case(subresource.name)}"
            )
            if not hasattr(cls, name):
                doc = make_docstring(
                    operation,
                    f"Update {subresource.name} of specified {resource.singular}",
                )
                handler = make_update_handler(operation, doc)
                setattr(cls, name, handler)

        elif operation.name == "Delete":
            name = (
                f"delete_{camel_to_snake_case(resource.singular)}"
                f"_{camel_to_snake_case(subresource.name)}"
            )
            if not hasattr(cls, name):
                doc = make_docstring(
                    operation,
                    f"Delete {subresource.name} of specified {resource.singular}",
                )
                handler = make_delete_handler(operation, doc)
                setattr(cls, name, handler)

        else:
            subname = camel_to_snake_case(operation.subresource.name)
            resource_name = camel_to_snake_case(resource.singular)
            opname = camel_to_snake_case(operation.name)
            name = f"{opname}_{resource_name}_{subname}"

            if not hasattr(cls, name):
                raise NotImplementedError(
                    f"Generator for operation {operation!r} not implemented"
                )


def make_signature(operation, query=set()):
    parameters = [Parameter("self", kind=Parameter.POSITIONAL_OR_KEYWORD)]

    for _, name, _, _ in Formatter().parse(operation.path):
        if name is not None:
            parameters.append(Parameter(name, kind=Parameter.POSITIONAL_OR_KEYWORD))

    if operation.body is not None:
        parameters.append(Parameter("body", kind=Parameter.POSITIONAL_OR_KEYWORD))

    if operation.query:
        for name, field in operation.query.items():
            if name in query:
                parameters.append(
                    Parameter(name, default=None, kind=Parameter.POSITIONAL_OR_KEYWORD)
                )

    return Signature(parameters)


class DocString(object):
    def __init__(self, description=""):
        self.description = description
        self.args = []
        self.returns = ""

    def add_argument(self, name, type, description):
        self.args.append(f"{name} ({self._type_ref(type)}): {description}")

    def add_return(self, type, description):
        self.returns = f"{self._type_ref(type)}: {description}"

    def _type_ref(self, type):
        if type.__module__ == "builtins":
            return type.__name__

        return f"{type.__module__}.{type.__qualname__}"

    def __str__(self):
        args = "\n                ".join(self.args)

        return f"""{self.description}

            {"Args:" if args else ""}
                {args}

            {"Returns:" if self.returns else ""}
                {self.returns}

        """


def make_docstring(operation, description, query=set()):
    doc = DocString(description)
    singular = operation.resource.singular

    for _, name, _, _ in Formatter().parse(operation.path):
        if name is not None:
            doc.add_argument(name, str, f"{name.title()} of the {singular}")

    if operation.body:
        doc.add_argument("body", operation.body, "Body of the HTTP request")

    if operation.query:
        for name, field in operation.query.items():
            if name in query:
                doc.add_argument(name, str, field.metadata["doc"])

    if operation.response:
        doc.add_return(operation.response, "Body of the HTTP response")

    return doc


def make_create_handler(operation, doc):
    signature = make_signature(operation)

    @with_signature(signature, doc=str(doc))
    async def create_resource(self, body, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(
            operation.method, url, json=body.serialize()
        )
        data = await resp.json()
        return operation.response.deserialize(data)

    return create_resource


def make_list_handler(operation, doc):
    signature = make_signature(operation)

    @with_signature(signature, doc=str(doc))
    async def list_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(operation.method, url)
        data = await resp.json()
        return operation.response.deserialize(data)

    return list_resources


def make_watch_handler(operation, doc):
    # Infer the type of the watch event objects from the type of the list
    # of items.
    model, = get_field(operation.response, "items").type.__args__
    signature = make_signature(operation, {"heartbeat"})

    @with_signature(signature, doc=str(doc))
    def watch_resources(self, heartbeat, **kwargs):
        path = operation.path.format(**kwargs)

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, model)

    return watch_resources


def make_list_all_handler(operation, doc):
    signature = make_signature(operation)

    @with_signature(signature, doc=str(doc))
    async def list_all_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(operation.method, url)
        data = await resp.json()
        return operation.response.deserialize(data)

    return list_all_resources


def make_watch_all_handler(operation, doc):
    # Infer the type of the watch event objects from the type of the list
    # of items.
    model, = get_field(operation.response, "items").type.__args__
    signature = make_signature(operation, query={"heartbeat"})

    @with_signature(signature, doc=str(doc))
    def watch_all_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path).with_query({"watch": ""})

        return Watcher(self.client.session, url, model)

    return watch_all_resources


def make_read_handler(operation, doc):
    signature = make_signature(operation)

    @with_signature(signature, doc=str(doc))
    async def read_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(operation.method, url)
        data = await resp.json()
        return operation.response.deserialize(data)

    return read_resources


def make_update_handler(operation, doc):
    signature = make_signature(operation)

    @with_signature(signature, doc=str(doc))
    async def update_resource(self, body, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(
            operation.method, url, json=body.serialize()
        )
        data = await resp.json()
        return operation.response.deserialize(data)

    return update_resource


def make_delete_handler(operation, doc):
    signature = make_signature(operation)

    @with_signature(signature, doc=str(doc))
    async def delete_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(operation.method, url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return operation.response.deserialize(data)

    return delete_resources


class Watcher(object):
    """Async context manager used by ``watch_*()`` methods of :class:`ClientApi`.

    The context manager returns the async generator of resources. On entering
    it is ensured that the watch is created. This means inside the context a
    watch is already established.

    Args:
        session (aiohttp.ClientSession): HTTP session that is used to access
            the REST API.
        url (str): URL for the watch request
        model (type): Type that will be used to deserialize
            :attr:`krake.data.core.WatchEvent.object`

    """

    def __init__(self, session, url, model):
        self.session = session
        self.url = url
        self.model = model
        self.response = None
        self.timeout = ClientTimeout(sock_read=None)

    async def __aenter__(self):
        self.response = await self.session.get(self.url, timeout=self.timeout)
        return self.watch()

    async def __aexit__(self, *exc):
        await self.response.release()
        self.response = None

    async def watch(self):
        """Async generator yielding watch events

        Yields:
            krake.data.core.WatchEvent: Watch events where ``object`` is
                already deserialized correctly according to the API
                definition (see ``model`` argument)

        """
        try:
            async for line in self.response.content:
                if not line:  # EOF
                    return
                if line == b"\n":  # Heartbeat
                    continue

                event = WatchEvent.deserialize(json.loads(line))
                event.object = self.model.deserialize(event.object)

                yield event

        except ClientPayloadError:
            return
