"""Simple dependency injection module for rok inspired by pytest's fixtures.

There is a simple registration decorator :func:`fixture` that can be used to
mark functions as fixtures. Functions using these fixtures can declare their
dependency with the :func:`use` decorator. Finally, :class:`Resolver` is used
to wire fixtures and dependencies.
"""
import os
from inspect import signature, isgeneratorfunction
from collections import deque
from urllib.parse import urljoin
import yaml
import requests


def fixture(func):
    """Mark a function or generator as fixtures. The name of the function is
    used as fixture name.

    If the marked function is a generator function, the fixture can be used
    as kind of context manager:

    .. code:: python

        @fixture
        def session():
            with Session() as session:
                yield session

    Attributes:
        mapping (dict): Mapping of registered fixture names to functions

    Args:
        func: Function that should be registered as fixture

    Raises:
        RuntimeError: If the a fixtures with the same name is already
            registered.

    """
    if func.__name__ in fixture.mapping:
        raise RuntimeError(
            f"Fixture {func.__name__!r} already registered by "
            f"{fixture.mapping[func.__name__]}"
        )
    fixture.mapping[func.__name__] = func
    return func


fixture.mapping = {}


def use(argname):
    """Decorator function for declaring fixture dependencies on functions

    Example:
        .. python:: code

            from rok.fixtures import use

            @use("config")
            def my_func(config):
                # do something with the configuration ...

    Args:
        argname (str): Name of the fixture that should be passed as keyword
            argument.

    Returns:
        Function that can be used as decorator for declaring the dependency
        of a decoratored function on the fixtures with name ``argname``.

    """

    def decorator(func):
        if not hasattr(func, "depends"):
            func.depends = [argname]
        else:
            func.depends.append(argname)
        return func

    return decorator


class Resolver(object):
    """Dependency resolver for functions marked via :func:`use` and fixtures.

    Resolver uses the context manager protocol to manage the lifecycle of
    generator-based fixtures.

    Example:
        .. code:: python

            from sqlalchemy import create_engine
            from krake.fixtures import fixture, use, Resolver

            @fixture
            def engine():
                yield create_engine("postgresql://user:passwd@localhost:5432/database")

            @use("engine")
            def fetch(engine, min_uid):
                with engine.begin() as connection:
                    result = connection.execute(
                        "SELECT username FROM users WHERE uid >= ?", min_uid
                    )
                    for row in result:
                        print(row["username"])

            with Resolver() as resolver:
                # Execute function "fetch" with resolved fixtures. Additional
                # keyword arguments can be passed. These can also be used to
                # overwrite fixtures.
                resolver(fetch, min_uid=1000)

    Args:
        fixtures (dict, optional): A mapping of fixture names to functions. Defaults
            to the mapping of :attr:`fixture.mapping`

    """

    def __init__(self, fixtures=None):
        if fixtures is None:
            fixtures = fixture.mapping
        self.resolved = None
        self.fixtures = fixtures

    def __enter__(self):
        self.resolved = {}
        self.resolving = deque()
        self.generators = {}
        return self

    def __exit__(self, *exc):
        for name, gen in self.generators.items():
            try:
                next(gen)
            except StopIteration:
                pass
            else:
                raise RuntimeError(f"Fixture {name} yielded multiple values")

    def __call__(self, func, **kwargs):
        depends = getattr(func, "depends", [])

        for name in depends:
            # Dependency overwritten
            if name in kwargs:
                pass

            # Dependency already resolved
            elif name in self.resolved:
                kwargs[name] = self.resolved[name]

            # Load fixture
            elif name in self.fixtures:

                if name in self.resolving:
                    raise RuntimeError(
                        f"Circular dependency detected for {name!r}, "
                        f"circle is {self.resolving}"
                    )

                self.resolving.append(name)
                value = self(self.fixtures[name])
                assert self.resolving.pop() == name

                if isgeneratorfunction(self.fixtures[name]):
                    self.generators[name] = value
                    value = next(value)

                self.resolved[name] = value
                kwargs[name] = value

            else:
                raise RuntimeError(
                    f"No fixture found for parameter {name!r} in "
                    f"function '{func.__module__}.{func.__name__}()'"
                )

        return func(**kwargs)


# -----------------------------------------------------------------------------
# Fixture definitions
# -----------------------------------------------------------------------------


@fixture
def config():
    try:
        XDG_CONFIG_HOME = os.environ["XDG_CONFIG_HOME"]
    except KeyError:
        XDG_CONFIG_HOME = os.path.join(os.environ["HOME"], ".config")

    config_paths = [
        ".rok.yaml",
        os.path.join(XDG_CONFIG_HOME, "rok.yaml"),
        "/etc/rok/rok.yaml",
    ]

    for path in config_paths:
        try:
            with open(path, "r") as fd:
                return yaml.load(fd)
        except FileNotFoundError:
            pass

    # No config file was found. Use defaults
    return {"api_url": "http://localhost:8080"}


class BaseUrlSession(requests.Session):
    """Simple requests session using a base URL for all requests.

    Args:
        base_url (str, optional): Base URL that should be used as prefix for
            every request.
        raise_for_status (bool, optional): Automatically raise an exception of
            for error response codes. Default: True

    """

    def __init__(self, base_url=None, raise_for_status=True):
        self.base_url = base_url
        self.raise_for_status = raise_for_status
        super().__init__()

    def request(self, method, url, *args, raise_for_status=None, **kwargs):
        if raise_for_status is None:
            raise_for_status = self.raise_for_status
        url = self.create_url(url)
        resp = super().request(method, url, *args, **kwargs)
        if raise_for_status:
            resp.raise_for_status()
        return resp

    def create_url(self, url):
        if self.base_url:
            return urljoin(self.base_url, url)
        return url


@fixture
@use("config")
def session(config):
    with BaseUrlSession(base_url=config["api_url"]) as session:
        yield session
