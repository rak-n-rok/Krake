# Introduction

First off all, thank you for considering contributing to Krake! 

There are many ways to contribute, such as improving the documentation, 
submitting bug reports and feature requests or writing code which can be 
incorporated into Krake itself.

Please, don't use the issue tracker for support questions. Connect with us on
the [Krake Matrix room](https://riot.im/app/#/room/#krake:matrix.org) if you 
have any questions or need support.


# Setup a Development Environment

This section describes a quickstart for developers to get started with a Krake
development setup. Advanced topics are covered in the [Developer
Documentation](docs/dev/index.rst) and the [Admin
Documentation](docs/admin/index.rst)


## Requirements

- [etcdv3](https://github.com/etcd-io/etcd/releases/)
- [Python](https://www.python.org/downloads/) >= 3.6
- [pre-commit](https://pre-commit.com/)
- [cfssl](https://cfssl.org/) (optional) – for setting up a development PKI
- [keystone](https://pypi.org/project/keystone/) (optional) – for testing
keystone server authentication
- [Setup at least one Minikube
VM](https://kubernetes.io/docs/setup/learning-environment/minikube/)


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

# Start by copying the template of the configuration file. You can then modify without any issue
cp krake.yaml.template krake.yaml

# Optional: you can use the rok configuration template as you prefer.
#   Otherwise rok will use the default configuration
cp rok.yaml.template rok.yaml

# Run etcd server. This will store the data in "tmp/etcd".
support/etcd

# Run local Keystone server. Related data is stored in "tmp/keystone". This
# requires keystone to be installed (pip install keystone)
support/keystone

# Optional: If the API server should be encrypted with TLS and support client
#   certificate authentication, create a certificate for the API server.
#   This required "cfssl" to be installed.
support/pki "system:api-server"
# An additional certificate can be created for each components (schedulers and controller),
# by adding the appropriate path to the configuration file. Example:
support/pki "system:scheduler"

# Run the API
python -m krake.api

# Run the krake Scheduler
python -m krake.controller.scheduler

# Run the Kubernetes application controller
python -m krake.controller.kubernetes.application

# Run the Kubernetes cluster controller
python -m krake.controller.kubernetes.cluster
```


## Basic Usage

This provides a simple demonstration of Krake's functionalities. Please
refer to the [User Documentation](docs/user/index.rst) for extended usage
guidelines, explanations, and examples.

Download the kubeconfig file, as well as the certificate and key file
necessary to connect to your Minikube instance.

```bash
$ MINIKUBE_IP="" # Fill in with the Minikube IP address

$ mkdir -p cluster_certs/certs cluster_certs/config

$ scp ubuntu@$MINIKUBE_IP:~/.kubectl/config cluster_certs/config/
$ scp ubuntu@$MINIKUBE_IP:~/.minikube/\{ca.crt,client.crt,client.key\} cluster_certs/certs

$ sed -i "/certificate-authority/c\    certificate-authority: `pwd`/cluster_certs/certs/ca.crt" cluster_certs/config
$ sed -i "/server:/c\    server: https://$MINIKUBE_IP:8443" cluster_certs/config
$ sed -i "/client-certificate/c\    client-certificate: `pwd`/cluster_certs/certs/client.crt" cluster_certs/config
$ sed -i "/client-key/c\    client-key: `pwd`/cluster_certs/certs/client.key" cluster_certs/config
```

Use the `rok` CLI to register your Minikube instance as a Krake backend:

```bash
$ rok kube cluster create cluster_certs/config
```

Run an application on Krake:

```bash
$ cd rok/
$ rok kube app create -f tests/echo-demo.yaml echo-demo
```

Check the status of the application:

```bash
$ rok kube app get echo-demo
+-----------+-------------------------------+
| reason    | None                          |
| name      | echo-demo                     |
| namespace | system                        |
| user      | system:anonymous              |
| created   | 2019-08-14 13:42:16           |
| modified  | 2019-08-14 13:42:17           |
| services  | echo-demo: 192.168.0.15:30421 |
| state     | RUNNING                       |
+-----------+-------------------------------+
```

Access the application:

```bash
$ curl 192.168.0.15:30421


Hostname: echo-demo-79bd46c485-qq75m

Pod Information:
  -no pod information available-

Server values:
  server_version=nginx: 1.13.3 - lua: 10008

Request Information:
  client_address=172.17.0.1
  method=GET
  real path=/
  query=
  request_version=1.1
  request_scheme=http
  request_uri=http://192.168.0.15:8080/

Request Headers:
  accept=*/*
  host=192.168.0.15:30421
  user-agent=curl/7.58.0

Request Body:
  -no body in request-

```

Delete the application:

```bash
$ rok kube app delete echo-demo
```

Delete the cluster:

```bash
$ rok kube cluster delete minikube
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
text of the [DCO](DCO.md) is fairly simple. It is also available on
developercertificate.org.

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
