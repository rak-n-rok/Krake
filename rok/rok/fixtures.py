import os
from inspect import signature, isgeneratorfunction
from collections import deque
from urllib.parse import urljoin
import yaml
import requests


def fixture(func):
    if func.__name__ in fixture.mapping:
        raise RuntimeError(
            f"Fixture {func.__name__!r} already registered by "
            f"{fixture.mapping[func.__name__]}"
        )
    fixture.mapping[func.__name__] = func
    return func


fixture.mapping = {}


def use(argname):
    def decorator(func):
        if not hasattr(func, "depends"):
            func.depends = [argname]
        else:
            func.depends.append(argname)
        return func

    return decorator


class Resolver(object):
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


class BaseUrlSession(requests.Session):
    def __init__(self, base_url=None, raise_for_status=True):
        self.base_url = base_url
        self.raise_for_status = raise_for_status
        super().__init__()

    def request(self, method, url, *args, **kwargs):
        url = self.create_url(url)
        resp = super().request(method, url, *args, **kwargs)
        if self.raise_for_status:
            resp.raise_for_status()
        return resp

    def create_url(self, url):
        if self.base_url:
            return urljoin(self.base_url, url)
        return url


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


@fixture
@use("config")
def session(config):
    with BaseUrlSession(base_url=config["api_url"]) as session:
        yield session
