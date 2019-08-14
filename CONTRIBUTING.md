# Introduction

First off, thank you for considering contributing to Krake! There are many
ways to contribute, such as improving the documentation, submitting bug
reports and feature requests or writing code which can be incorporated into
Krake itself.

Please, don't use the issue tracker for support questions. Connect with us on
the [Krake Matrix room](https://riot.im/app/#/room/#krake:matrix.org)


# Setup a Development Environment

This section describes a quickstart for developers to get started with a Krake
development setup.


## Requirements

 - [etcdv3](https://github.com/etcd-io/etcd/releases/)
 - [Python](https://www.python.org/downloads/) >= 3.6
 - [pre-commit](https://pre-commit.com/)
 - [cfssl](https://cfssl.org/) (optional) – for setting up a development PKI
 - [keystone](https://pypi.org/project/keystone/) (optional) – for testing
 keystone server authentication


## Installation

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


## Running

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
#   This required "cfssl" to be installed.
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


## Testing

Tests are placed in the `tests/` directory inside the Python packages and can
be run via `pytest`.


```bash
# Run tests of the "krake" package
pytest krake/tests

# Run tests of the "rok" package
pytest rok/tests
```


## Documentation

```bash
# Install Sphinx
pip install sphinx

# Build HTML documentation
cd docs/
make html
```


## Access to local Keystone

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


# Developer Certificate of Origin (DCO)

The Krake project uses a mechanism known as a Developer Certificate of Origin
(DCO). The DCO is a legally binding statement that asserts that you are the
creator of your contribution, and that you wish to allow Krake to use your
work.

Acknowledgement of this permission is done using a sign-off process in Git.
The sign-off is a simple line at the end of the explanation for the patch. The
text of the DCO is fairly simple (from developercertificate.org):

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
1 Letterman Drive
Suite D4700
San Francisco, CA, 94129

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

If you are willing to agree to these terms, you just add a line to every git
commit message:

`Signed-off-by: Joe Smith <joe.smith@email.com>`

If you set your `user.name` and `user.email` as part of your git
configuration, you can sign your commit automatically with `git commit -s`.

Unfortunately, you have to use your real name (i.e., pseudonyms or anonymous
contributions cannot be made). This is because the DCO is a legally binding
document, granting the Krake project to use your work.


# Commit message convention

We follow the guidelines on [How to Write a Git Commit
Message](https://chris.beams.io/posts/git-commit/)


# How to report a bug

If you find a security vulnerability, do NOT open an issue. Get in touch with
`mgoerens` on the [Krake Matrix
room](https://riot.im/app/#/room/#krake:matrix.org).

For any other type of bug, please create a issue using the "Issue" template.
Make sure to answer at least these three questions:
1. What did you do?
2. What did you expect to see?
3. What did you see instead?

General questions should be asked on the Matrix chat instead of the issue
tracker. The developers there will answer or ask you to file an issue if
you've tripped over a bug.


# How to suggest a feature or enhancement

Open an issue on our issues tracker on GitLab which describes the feature you
would like to see, why you need it, and how it should work.
