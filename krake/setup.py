import sys
from setuptools import setup, find_packages


install_requires = [
    "aiohttp",
    "marshmallow",
    "dataclasses",
    "etcd3-py",
    "requests",
    "pytz",
    "PyYAML",
    "webargs",
    "marshmallow_enum",
    "marshmallow_oneofschema",
    "kubernetes_asyncio",
    "makefun",
]

# dataclasses backport
if sys.version_info >= (3, 7):
    install_requires = ["dataclasses"]

setup(
    name="krake",
    version="1.0.0",
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={
        "dev": {"pytest", "pytest-aiohttp", "factory-boy", "prometheus-client"}
    },
)
