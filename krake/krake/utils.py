import asyncio
import re
import dataclasses
import functools
import json
from functools import lru_cache
from argparse import MetavarTypeHelpFormatter, ArgumentDefaultsHelpFormatter
from datetime import datetime, timezone


class KrakeArgumentFormatter(ArgumentDefaultsHelpFormatter, MetavarTypeHelpFormatter):
    """Custom formatter class which allows argparse help to display both the default
    value and the expected type (str, int...) for each arguments.

    To use for the ``formatter_class`` parameter of the
    :class:`argparse.ArgumentParser` constructor.
    """


def camel_to_snake_case(name):
    """Converts camelCase to the snake_case

    Args:
        name (str): Camel case name

    Returns:
        str: Name in stake case

    """
    cunder = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", cunder).lower()


def get_field(cls, name):
    for f in dataclasses.fields(cls):
        if f.name == name:
            return f

    raise AttributeError(f"{cls} does not have field {name!r}")


class cached_property(object):
    """A property that is only computed once per instance and then replaces itself
    with an ordinary attribute. Deleting the attribute resets the property.
    Inspired from:
    https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
    """

    def __init__(self, func):
        self.__doc__ = getattr(func, "__doc__")
        self.func = func

    def __get__(self, obj, cls):
        if obj is None:
            return self

        if asyncio.iscoroutinefunction(self.func):

            async def wrapper():
                task = asyncio.get_event_loop().create_task(self.func(obj))
                obj.__dict__[self.func.__name__] = task
                return await task

            return wrapper()

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


def cache_non_hashable(maxsize=1024):
    """Decorator to wrap a function with a memorizing callable with potentially
    non-hashable parameters.

    This decorator extends the build-in :func:`functools.lru_cache`, that supports
    only hashable parameters of decorated callables.

    Note:
        !Be aware that the lru_cache maxsize could affect the Krake memory
        footprint significantly!
        !Count the memory footprint before you use this decorator!

    Example:
        .. code:: python

            @hashable_lru
            def foobar(foo):
                return foo

            assert foobar({"foo": ["bar", "baz"]}) == {"foo": ["bar", "baz"]}

    Args:
        maxsize (int, optional): lru_cache maxsize. Defaults to 1024.

    Returns:
        callable: Decorator for hashable lru cache.

    """

    def decorator(func):
        cache = lru_cache(maxsize=maxsize)

        def deserialize(value):
            """Deserialize JSON document to a Python object.

            Args:
                value (str): JSON document

            Returns:
                dict, if the JSON document is valid and could be
                deserialized, the :args:`value` otherwise.

            """
            try:
                return json.loads(value)
            except json.decoder.JSONDecodeError:
                return value

        def func_with_serialized_params(*args, **kwargs):
            """Deserialize decorated callable parameters.

            This function deserializes the decorated callable
            parameters. Parameters were serialized before within
            the :func:`lru_decorator`.

            Args:
                args: Variable length argument list.
                kwargs: Arbitrary keyword arguments.

            Returns:
                callable: Decorated function with deserialized parameters.

            """
            _args = tuple([deserialize(arg) for arg in args])
            _kwargs = {k: deserialize(v) for k, v in kwargs.items()}
            return func(*_args, **_kwargs)

        cached_function = cache(func_with_serialized_params)

        @functools.wraps(func)
        def lru_decorator(*args, **kwargs):
            """Serialize and cache decorated callables.

            Args:
                args: Variable length argument list.
                kwargs: Arbitrary keyword arguments.

            Returns:
                callable: LRU-cached function with serialized parameters.

            """
            _args = tuple(
                [
                    json.dumps(arg, sort_keys=True)
                    if type(arg) in (list, dict)
                    else arg
                    for arg in args
                ]
            )
            _kwargs = {
                k: json.dumps(v, sort_keys=True) if type(v) in (list, dict) else v
                for k, v in kwargs.items()
            }
            return cached_function(*_args, **_kwargs)

        lru_decorator.cache_info = cached_function.cache_info
        lru_decorator.cache_clear = cached_function.cache_clear

        return lru_decorator

    return decorator


def now():
    """Returns the current time in the UTC timezone.

    Returns:
        datetime.datetime: the current time (UTC timezone)

    """
    return datetime.now(timezone.utc)


def get_namespace_as_kwargs(namespace):
    """Create keyword arguments using the provided namespace. If it is None, then return
    empty keywords arguments.

    Mostly for the case of having namespaced or non-namespaced resources in the same
    function or method.

    Args:
        namespace (str): the given namespace.

    Returns:
        dict[str, str]: The generated keywords arguments.

    """
    kwargs = {}
    if namespace:
        kwargs["namespace"] = namespace
    return kwargs


def get_kubernetes_resource_idx(manifest, resource, check_namespace=False):
    """Get a resource identified by its resource api, kind and name, from a manifest
    file

    Args:
        manifest (list[dict]): Manifest file to get the resource from
        resource (dict[str, dict|list|str]): resource to find
        check_namespace (bool): Flag to decide, if the namespace should be checked

    Raises:
        IndexError: If the resource is not present in the manifest

    Returns:
        int: Position of the resource in the manifest

    """
    for idx, found_resource in enumerate(manifest):
        api_version = resource.get("apiVersion") or resource["api_version"]
        if (
            found_resource["apiVersion"] == api_version
            and found_resource["kind"] == resource["kind"]
            and found_resource["metadata"]["name"] == resource["metadata"]["name"]
            and (
                not check_namespace
                or found_resource["metadata"].get("namespace")
                == resource["metadata"].get("namespace")
            )
        ):
            return idx

    raise IndexError
