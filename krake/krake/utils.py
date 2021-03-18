import asyncio
import re
import dataclasses
from datetime import datetime, timezone


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


async def aenumerate(iterable):
    i = 0
    async for item in iterable:
        yield i, item
        i += 1


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
