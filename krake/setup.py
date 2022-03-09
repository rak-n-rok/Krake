import sys
from setuptools import setup, find_packages


install_requires = [
    "aiohttp==3.*",
    "aiohttp-cors==0.7.*",
    "etcd3-py==0.1.*",
    "keystoneauth1==4.*",
    "kubernetes-asyncio==12.*",
    "lark-parser==0.11.*",
    "makefun==1.*",
    "marshmallow==3.*",
    "marshmallow-enum",
    "marshmallow-oneofschema",
    "pyOpenSSL",
    "python-magnumclient==3.*",
    "PyYAML==5.*",
    "requests==2.*",
]

# webargs
if sys.version_info < (3, 10):
    install_requires.append("webargs==8.*")
else:
    install_requires.append("webargs==6.*")

setup(
    name="krake",
    version="1.0.0",
    python_requires=">=3.7",
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
            "pytz==2021.*",
            "tox==3.*",
            "pre-commit==2.*",
            "pytest-httpserver==1.*",
        },
        "api_generator": {"black==21.11b1", "jinja2==3.*"},
    },
    scripts=["scripts/krake_bootstrap_db", "scripts/krake_generate_config"],
)
