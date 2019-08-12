# Krake v2 Prototype

The current Krake v2 prototype comprises two Python packages:

 - krake -- Krake microservices as Python submodules
 - rok -- command line interface for the Krake API


## Development Setup

This section describes a quickstart for developers to get started with a Krake
development setup.


### Requirements

 - [etcdv3](https://github.com/etcd-io/etcd/releases/)
 - [Python](https://www.python.org/downloads/) >= 3.6
 - [pre-commit](https://pre-commit.com/)
 - [cfssl](https://cfssl.org/) (optional) – for setting up a development PKI
 - [keystone](https://pypi.org/project/keystone/) (optional) – for testing keystone server authentication


### Installation

All dependencies can be installed via the corresponding `setup.py` scripts.

```bash
# Install git pre-commit hooks
pre-commit install

# Optional: libyaml development package if you want to use the PyYAML C extension.
sudo apt-get install libyaml-dev

# Install "krake" and "rok" with dev dependencies
pip install --editable krake/[dev]
pip install --editable rok/[dev]
```


### Running

All services can be run as Python modules with the `-m` option of the Python
interpreter:

```bash
cd krake/

# Run etcd server. This will store the data in "tmp/etcd".
support/etcd

# Run local Keystone server. Related data is stored in "tmp/keystone". This
# requires keystone to be installed (pip install keystone)
support/keystone

# Optional: If the API server should be encrypted with TLS and support client
#   certificate authentication, create a certificate for the API server.
#	This required "cfssl" to be installed.
support/pki "system:api-server"

# Run the API server
python -m krake.api

# Run the scheduler
python -m krake.controller.scheduler

# Run the Kubernetes application controller
python -m krake.controller.kubernetes.application

# Run the Kubernetes cluster controller
python -m krake.controller.kubernetes.cluster
```


### Testing

Tests are placed in the `tests/` directory inside the Python packages and can
be run via `pytest`.


```bash
# Run tests of the "krake" package
pytest krake/tests

# Run tests of the "rok" package
pytest rok/tests
```


### Documentation

```bash
# Install Sphinx
pip install sphinx

# Build HTML documentation
cd docs/
make html
```


### Access to local Keystone

The local Keystone service ``support/keystone`` can be accessed as admin with
the following OpenStack ``clouds.yaml`` settings (see
[OpenStack documentation](https://docs.openstack.org/python-openstackclient/latest/configuration/index.html#clouds-yaml))

```yaml
clouds:
  keystone:
    auth:
      auth_url: http://127.0.0.1:5000/v3
      username: system:admin
      password: admin
      project_name: system:admin
      user_domain_name: Default
      project_domain_name: Default
    region_name: RegionOne
```

Put the configuration abobe in a file `clouds.yaml` in the local working
directory and call the OpenStack command line tool as follows.

> **Note**: Make sure that no `OS_*` environmental variable is set. Otherwise
> these environmental variables overwrite settings in the `clouds.yaml`.

```bash
# Run local keystone service
support/keystone

# List all users
openstack --os-cloud keystone user list
```
