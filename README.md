# Krake

[![pipeline status](https://gitlab.com/rak-n-rok/krake/badges/master/pipeline.svg)](https://gitlab.com/rak-n-rok/krake/-/commits/master)
[![coverage report](https://gitlab.com/rak-n-rok/krake/badges/master/coverage.svg)](https://gitlab.com/rak-n-rok/krake/-/commits/master)
[![Support room on Matrix](https://img.shields.io/matrix/krake:matrix.org.svg?label=%23krake%3Amatrix.org&logo=matrix)](https://app.element.io/#/room/#krake:matrix.org
)

Welcome to the Krake repository! :octopus:

Krake [ˈkʀaːkə] is an orchestrator engine for containerized and virtualized
workloads across distributed and heterogeneous cloud platforms. It creates a
thin layer of aggregation on top of the different platforms (such as OpenStack,
Kubernetes or OpenShift) and presents them through a single interface to the
cloud user. The user's workloads are scheduled depending on both user
requirements (hardware, latencies, cost) and platforms characteristics (energy
efficiency, load). The scheduling algorithm can be optimized for example on
latencies, cost, or energy.
Krake can be leveraged for a wide range of application scenarios such as
central management of distributed compute capacities as well as application
management in Edge Cloud infrastructures.

## Getting Started

In order to get started and play with Krake, you'll need to deploy Krake plus
at least one Kubernetes cluster to act as a backend for Krake. We recommend
[Minikube][minikube] or [KinD][kind], which are a simple ways to get a Kubernetes
environment for development purposes.

This section describes a quickstart for developers to get started with a Krake
development setup. Advanced topics are covered in the
[Developer Documentation][dev-docs] and the [Admin Documentation][admin-docs].

### Requirements

#### Krake deployment

- [etcdv3][etcd]
- [Python][python] >= 3.6
- [Setup at least one Minikube VM][minikube] or [KinD instance][kind] alternatively

#### Test applications

- Zookeeper, Kafka and KSQL, for instance with the [Confluent Platform][confluent_packages]. The following commands need to be available:
  - `zookeeper-server-start`;
  - `kafka-server-start`;
  - `ksql-server-start`.

Optional requirement:

- [CFSSL][cfssl], also available in the official repository of the main distributions.
- [Prometheus][prometheus], also available in the official repository of the main
  distributions.

### Installation

As Krake is not yet on the Python Package Index (PyPI), the repository first
has to be cloned.

```bash
git clone https://gitlab.com/rak-n-rok/krake.git
cd krake
```

All dependencies can be installed via the corresponding `setup.py` scripts,
either with or without development dependencies. Installing them into a
[Python virtualenv][virtualenv] is recommended.

```bash
python3 -m venv .env
source .env/bin/activate
# Install "krake" and "rok" without development dependencies
pip install --editable rok/
pip install --editable krake/
```

```bash
# Install "krake" and "rok" with development dependencies
pip install --editable "rok/[dev]"
pip install --editable "krake/[dev]"
```

### Running

#### Configuration

First, the configuration files need to be generated with a script. They can
then be modified at will.

```bash
# first, start the generate script to have initial config files
krake_generate_config config/*.template rok.yaml.template

krake_generate_config --allow-anonymous --static-authentication-enabled config/api.yaml.template

# You can then modify each file at your preference.
# afterwards create that folder which is expected:
sudo mkdir /etc/krake

# last, copy generated files to that directory with 
sudo cp *.yaml /etc/krake

# Optional: you can use the rok configuration template as you prefer. It can also be generated.
# Otherwise rok will use the default configuration
krake_generate_config rok.yaml.template
```

The `--allow-anonymous` and `--static-authentication-enabled` options set the API with
minimal authentication and authorization protections. It should not be used with a
production deployment, but are easier to work with in a test deployment. For more
information, take a look at the "Security principle s" chapter of the
[Admin Documentation][admin-docs].

#### Bootstrapping of the database

The database can be bootstrapped, by adding resources in the database before
starting Krake:

```bash
# Create roles for the RBAC authorization mode.
krake_bootstrap_db bootstrapping/base_roles.yaml

# Create metrics and metrics providers, for development purposes.
krake_bootstrap_db support/prometheus_metrics.yaml support/static_metrics.yaml
```

#### Starting all components

All services can be run as Python modules with the `-m` option of the Python
interpreter:

```bash
# Run etcd server. This will store the data in "tmp/etcd".
support/etcd

# Run prometheus server. This will store the data in "tmp/prometheus".
support/prometheus

# Run the API
python -m krake.api

# Run the Garbage Collector
python -m krake.controller.gc

# Run the krake Scheduler
python -m krake.controller.scheduler

# Run the Kubernetes application controller
python -m krake.controller.kubernetes
```

### Basic Usage

This provides a simple demonstration of Krake's functionalities. Please refer
to the [User Documentation][user-docs] for extended usage guidelines,
explanations, and examples.

#### Prepare Kubernetes environment

##### Minikube

Create Minikube instance and download the kubeconfig file, as well as the certificate and key file
necessary to connect to your Minikube instance.

```bash
mkdir cluster_certs
minikube start


```

##### KinD

Create KinD instance and save the kubeconfig file in `cluster_certs` directory

Prerequisites

- [Docker][docker]
- [kind][kind]

```bash
mkdir cluster_certs
# The name of your k8s cluster
CLUSTER_NAME=""
# Start single node k8s cluster
kind create cluster --name $CLUSTER_NAME --kubeconfig cluster_certs/$CLUSTER_NAME.yaml
```

If your are planning to use Minikube you could use the ‚kubectl‘ command:

```bash
kubectl config view >> krake/cluster_certs/minikube_conf.yaml
```

Now we register the Minikube (or KinD) instance as a Krake backend and use Krake to
deploy an `echoserver` application.

```bash
# Register your Minikube instance
rok kube cluster create cluster_certs/config/minikube_conf.yaml

# Run an application on Krake
rok kube app create -f rak/functionals/echo-demo.yaml echo-demo

# Check the status of the application
rok kube app get echo-demo
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

# Access the application
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


# Delete the application
rok kube app delete echo-demo

# Delete the cluster
rok kube cluster delete minikube
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

## Documentation

The project's documentation is hosted on [Read the Docs][rtfd].

## Get in touch!

If you need help to setup things, have a question, or simply want to chat with
us, find us on our [Krake Matrix room][krake-matrix].

If you wish to contribute, you can also check the
[Contributing](CONTRIBUTING.md) guide.

## Project Background

The Rak'n'Rok project has initially been developed at
[Cloud&Heat](https://www.cloudandheat.com/). The development of Krake was
transformed to an open source project in September 2019.

<!-- References -->

[minikube]: https://kubernetes.io/docs/setup/learning-environment/minikube/
[etcd]: https://github.com/etcd-io/etcd/releases/
[prometheus]: https://prometheus.io/download/
[python]: https://www.python.org/downloads/
[rtfd]: https://rak-n-rok.readthedocs.io/
[dev-docs]: https://rak-n-rok.readthedocs.io/projects/krake/en/latest/dev/index.html
[admin-docs]: https://rak-n-rok.readthedocs.io/projects/krake/en/latest/admin/index.html
[user-docs]: https://rak-n-rok.readthedocs.io/projects/krake/en/latest/user/index.html
[sphinx]: http://www.sphinx-doc.org/
[krake-matrix]: https://app.element.io/#/room/#krake:matrix.org
[virtualenv]: https://virtualenv.pypa.io/en/stable
[confluent_packages]: https://docs.confluent.io/platform/current/installation/available_packages.html
[cfssl]: https://github.com/cloudflare/cfssl
[kind]: https://kind.sigs.k8s.io/
[docker]: https://www.docker.com/
