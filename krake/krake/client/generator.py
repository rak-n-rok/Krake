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

    +-----------+-------------------------------+
    | Operation | Method                        |
    +===========+===============================+
    | Create    | create_{snake cased singular} |
    +-----------+-------------------------------+
    | List      | list_{snake cased plural}     |
    +-----------+-------------------------------+
    | ListAll   | list_all_{snake cased plural} |
    +-----------+-------------------------------+
    | Read      | read_{snake cased singular}   |
    +-----------+-------------------------------+
    | Update    | update_{snake cased singular} |
    +-----------+-------------------------------+
    | Delete    | delete_{snake cased singular} |
    +-----------+-------------------------------+

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

            for subresource in resource.subresources.values():
                create_subresource_handlers(resource, subresource, cls)

        if cls.__init__ == object.__init__:
            cls.__init__ = init_client

        if not cls.__doc__:
            cls.__doc__ = make_class_docstring(apidef, cls)

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
        api (krake.apidefs.ApiDef): API definition
        resource (krake.apidefs.Resource): Resource handlers are created
            for
        attrs (dict): Attributes of the generated class

    """
    if hasattr(resource, "Create"):
        name = f"create_{camel_to_snake_case(resource.singular)}"
        if not hasattr(cls, name):
            doc = make_docstring(
                resource, resource.Create, f"Create specified {resource.singular}"
            )
            handler = make_create_handler(resource, resource.Create, doc)
            setattr(cls, name, handler)

    if hasattr(resource, "List"):
        name = f"list_{camel_to_snake_case(resource.plural)}"
        if not hasattr(cls, name):
            if resource.scope == Scope.NAMESPACED:
                description = f"List {resource.plural} in the namespace"
            else:
                description = f"List all {resource.plural}"
            doc = make_docstring(resource, resource.List, description)
            handler = make_list_handler(resource, resource.List, doc)
            setattr(cls, name, handler)

        name = f"watch_{camel_to_snake_case(resource.plural)}"
        if not hasattr(cls, name):
            if resource.scope == Scope.NAMESPACED:
                description = f"Watch {resource.plural} in the namespace"
            else:
                description = f"Watch all {resource.plural}"
            doc = make_docstring(resource, resource.List, description)
            handler = make_watch_handler(resource, resource.List, doc)
            setattr(cls, name, handler)

    if hasattr(resource, "ListAll"):
        name = f"list_all_{camel_to_snake_case(resource.plural)}"
        if not hasattr(cls, name):
            doc = make_docstring(
                resource, resource.List, f"List {resource.plural} in all namespaces"
            )
            handler = make_list_all_handler(resource, resource.ListAll, doc)
            setattr(cls, name, handler)

        name = f"watch_all_{camel_to_snake_case(resource.plural)}"
        if not hasattr(cls, name):
            doc = make_docstring(
                resource, resource.List, f"Watch {resource.plural} in all namespaces"
            )
            handler = make_watch_all_handler(resource, resource.ListAll, doc)
            setattr(cls, name, handler)

    if hasattr(resource, "Read"):
        name = f"read_{camel_to_snake_case(resource.singular)}"
        if not hasattr(cls, name):
            doc = make_docstring(
                resource, resource.List, f"Read specified {resource.singular}"
            )
            handler = make_read_handler(resource, resource.Read, doc)
            setattr(cls, name, handler)

    if hasattr(resource, "Update"):
        name = f"update_{camel_to_snake_case(resource.singular)}"
        if not hasattr(cls, name):
            doc = make_docstring(
                resource, resource.Update, f"Update specified {resource.singular}"
            )
            handler = make_update_handler(resource, resource.Update, doc)
            setattr(cls, name, handler)

    if hasattr(resource, "Delete"):
        name = f"delete_{camel_to_snake_case(resource.singular)}"
        if not hasattr(cls, name):
            doc = make_docstring(
                resource, resource.List, f"Delete specified {resource.singular}"
            )
            handler = make_delete_handler(resource, resource.Delete, doc)
            setattr(cls, name, handler)


def create_subresource_handlers(resource, subresource, cls):
    if hasattr(subresource, "Create"):
        name = (
            f"create_{camel_to_snake_case(resource.singular)}"
            f"_{camel_to_snake_case(subresource.__name__)}"
        )
        if not hasattr(cls, name):
            doc = make_docstring(
                resource,
                resource.List,
                f"Create {subresource.__name__} of specified {resource.singular}",
            )
            handler = make_create_handler(subresource, subresource.Create, doc)
            setattr(cls, name, handler)

    if hasattr(subresource, "List"):
        name = (
            f"list_{camel_to_snake_case(resource.plural)}"
            f"_{camel_to_snake_case(subresource.__name__)}"
        )
        if not hasattr(cls, name):
            doc = make_docstring(
                resource,
                resource.List,
                f"List {subresource.__name__} of specified {resource.singular}",
            )
            handler = make_list_handler(subresource, subresource.List, doc)
            setattr(cls, name, handler)

        name = (
            f"watch_{camel_to_snake_case(resource.plural)}"
            f"_{camel_to_snake_case(subresource.__name__)}"
        )
        if not hasattr(cls, name):
            handler = make_watch_handler(subresource, subresource.List, doc)
            setattr(cls, name, handler)

    if hasattr(subresource, "Read"):
        name = (
            f"read_{camel_to_snake_case(resource.singular)}"
            f"_{camel_to_snake_case(subresource.__name__)}"
        )
        if not hasattr(cls, name):
            doc = make_docstring(
                resource,
                resource.List,
                f"Read {subresource.__name__} of specified {resource.singular}",
            )
            handler = make_read_handler(subresource, subresource.Read, doc)
            setattr(cls, name, handler)

    if hasattr(subresource, "Update"):
        name = (
            f"update_{camel_to_snake_case(resource.singular)}"
            f"_{camel_to_snake_case(subresource.__name__)}"
        )
        if not hasattr(cls, name):
            doc = make_docstring(
                resource,
                resource.List,
                f"Update {subresource.__name__} of specified {resource.singular}",
            )
            handler = make_update_handler(subresource, subresource.Update, doc)
            setattr(cls, name, handler)

    if hasattr(subresource, "Delete"):
        name = (
            f"delete_{camel_to_snake_case(resource.singular)}"
            f"_{camel_to_snake_case(subresource.__name__)}"
        )
        if not hasattr(cls, name):
            doc = make_docstring(
                resource,
                resource.List,
                f"Delete {subresource.__name__} of specified {resource.singular}",
            )
            handler = make_delete_handler(subresource, subresource.Delete, doc)
            setattr(cls, name, handler)


def make_signature(resource, operation):
    parameters = [Parameter("self", kind=Parameter.POSITIONAL_OR_KEYWORD)]

    for _, name, _, _ in Formatter().parse(operation.path):
        if name is not None:
            parameters.append(Parameter(name, kind=Parameter.POSITIONAL_OR_KEYWORD))

    if operation.body is not None:
        parameters.append(Parameter("body", kind=Parameter.POSITIONAL_OR_KEYWORD))

    return Signature(parameters)


def make_docstring(resource, operation, description):
    pathargs = []

    for _, name, _, _ in Formatter().parse(operation.path):
        if name is not None:
            pathargs.append(f"{name} (str): {name.title()} of the {resource.singular}")

    pathargs = "\n    ".join(pathargs)

    if operation.body:
        body = (
            f"body ({operation.body.__module__}.{operation.body.__qualname__}): "
            "Body of the HTTP request"
        )
    else:
        body = ""

    if operation.response:
        returns = (
            f"Returns:\n    "
            f"{operation.response.__module__}.{operation.response.__qualname__}: "
            "Body of the HTTP response"
        )

    return f"""{description}

{"Args:" if pathargs or body else ""}
    {pathargs}
    {body}

{returns}

"""


def make_create_handler(resource, operation, doc):
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
    async def create_resource(self, body, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(
            operation.method,
            url,
            json=body.serialize(subresources=set(), readonly=False),
        )
        data = await resp.json()
        return operation.response.deserialize(data)

    return create_resource


def make_list_handler(resource, operation, doc):
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
    async def list_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(operation.method, url)
        data = await resp.json()
        return operation.response.deserialize(data)

    return list_resources


def make_watch_handler(resource, operation, doc):
    # Infer the type of the watch event objects from the type of the list
    # of items.
    model, = get_field(operation.response, "items").type.__args__
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
    def watch_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path).with_query({"watch": ""})

        return Watcher(self.client.session, url, model)

    return watch_resources


def make_list_all_handler(resource, operation, doc):
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
    async def list_all_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(operation.method, url)
        data = await resp.json()
        return operation.response.deserialize(data)

    return list_all_resources


def make_watch_all_handler(resource, operation, doc):
    # Infer the type of the watch event objects from the type of the list
    # of items.
    model, = get_field(operation.response, "items").type.__args__
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
    def watch_all_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path).with_query({"watch": ""})

        return Watcher(self.client.session, url, model)

    return watch_all_resources


def make_read_handler(resource, operation, doc):
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
    async def read_resources(self, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(operation.method, url)
        data = await resp.json()
        return operation.response.deserialize(data)

    return read_resources


def make_update_handler(resource, operation, doc):
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
    async def update_resource(self, body, **kwargs):
        path = operation.path.format(**kwargs)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request(
            operation.method,
            url,
            json=body.serialize(subresources=set(), readonly=False),
        )
        data = await resp.json()
        return operation.response.deserialize(data)

    return update_resource


def make_delete_handler(resource, operation, doc):
    signature = make_signature(resource, operation)

    @with_signature(signature, doc=doc)
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
        self.timeout = ClientTimeout(sock_read=float("inf"))

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
                already deserialized correctly occording to the API
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
