import sys
from setuptools import setup, find_packages


install_requires = [
    "aiohttp<4",
    "etcd3-py==0.1.*",
    "keystoneauth1",
    "kubernetes-asyncio<11.*",
    "lark-parser==0.8.*",
    "makefun==1.*",
    "marshmallow>=3",
    "marshmallow-enum",
    "marshmallow-oneofschema",
    "pyOpenSSL",
    "python-magnumclient==2.*",
    "PyYAML==5.*",
    "requests==2.*",
    "webargs==5.*",
]

# dataclasses backport
if sys.version_info < (3, 7):
    install_requires.append("dataclasses==0.6.*")

setup(
    name="krake",
    version="1.0.0",
    python_requires=">=3.6",
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={
        "dev": {
            "factory-boy==2.*",
            "prometheus-async",
            "prometheus-client==0.7.*",
            "pytest",
            "pytest-aiohttp==0.3.*",
            "pytz",
            "tox==3.*",
        }
    },
    scripts=["scripts/krake_bootstrap_db", "scripts/krake_generate_config"],
)
