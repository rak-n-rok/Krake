# Krake v2 Prototype

The current Krake v2 prototype comprises two Python packages:

 - krake -- Krake microservices as Python submodules
 - rok -- command line interface for the Krake API


### Requirements

 - [etcdv3](https://github.com/etcd-io/etcd/releases/)
 - [Python](https://www.python.org/downloads/) >= 3.6
 - [pre-commit](https://pre-commit.com/)


### Installation

All dependencies can be installed via the corresponding `setup.py` scripts.

```bash
# Install git pre-commit hooks
pre-commit install

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

# Run local Keystone server. Related data is stored in "tmp/keystone".
support/keystone

# Run the API server
py -m krake.api

# Run the scheduler
py -m krake.controller.scheduler

# Run the Kubernetes controller
py -m krake.controller.kubernetes
```


### Testing

Tests are placed in the `tests/` directory inside the Python packages and can
be run via `pytest`.


```bash
# Run tests of the "krake" package
pytest krake/tests

# Run tests of the "rok" package
cd rok/tests
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
the following OpenStack ``clouds.yaml`` settings:

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
