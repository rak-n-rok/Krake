import sys
from setuptools import setup, find_packages
import codecs
import os.path


def read(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, rel_path), 'r') as fp:
        return fp.read()


def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith('__version__'):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    else:
        raise RuntimeError("Unable to find version string.")


install_requires = [
    "aiohttp==3.*",
    "aiohttp-cors==0.7.*",
    "etcd3-py==0.1.*",
    "keystoneauth1==4.*",
    "kubernetes",
    "kubernetes-asyncio==22.*",
    "lark-parser==0.11.*",
    "makefun==1.*",
    "marshmallow==3.*",
    "marshmallow-enum",
    "marshmallow-oneofschema",
    "marshmallow-union",
    "mock",
    "pyOpenSSL",
    "python-magnumclient==3.*",
    "PyYAML==5.*",
    "requests==2.*",
    "SQLAlchemy==1.4.46",
    "oslo.db==11.3.0",
    "tosca-parser==2.6.*",
    "deepdiff==6.2.*",
    "yarl==1.8.*",
    "influxdb_client",
]

# webargs
if sys.version_info < (3, 10):
    install_requires.append("webargs==8.*")
else:
    install_requires.append("webargs==6.*")

# The newest importlib_metadata version isn't completely compatible with the oldest
# python version Krake supports (or better so, the tests we wrote with that).
if sys.version_info < (3, 8):
    install_requires.append("importlib_metadata==3.6.*")


setup(
    name="krake",
    version=get_version("krake/__about__.py"),
    description="",
    url="https://gitlab.com/rak-n-rok/krake",
    maintainer="Krake Development Team",
    maintainer_email="krake@cloudandheat.com",
    python_requires=">=3.8",
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={
        "dev": {
            "factory-boy==2.*",
            "mock==4.*",
            "prometheus-async==19.*",
            "prometheus-client==0.7.*",
            "pytest==6.*",
            "pytest-aiohttp==0.3.*",
            "pytest-cov==3.*",
            "pytest-httpserver==1.*",
            "pytz==2021.*",
            "tox==3.*",
            "pre-commit==2.*",
            "keystone==20.*",
            "pytest-httpserver==1.*",
        },
        "ansible": {
            "ansible>=2.9",
            "python-openstackclient",
            "openstacksdk"
        },
        "api_generator": {
            "black==21.11b1",
            "jinja2==3.*"
        },
    },
    scripts=[
        "scripts/krake_bootstrap_db",
        "scripts/krake_generate_config"
    ],
)
