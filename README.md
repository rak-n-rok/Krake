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
[minikube][minikube] or [kind][kind], which are a simple ways to get a Kubernetes
environment for development purposes.

This section describes a quickstart for developers to get started with a Krake
development setup. Advanced topics are covered in the
[Developer Documentation][dev-docs] and the [Admin Documentation][admin-docs].

Krake can also be found as a [PyPi package][pypi], if an integration in another
project is desired or required.

### Requirements

#### Krake deployment

- [etcdv3][etcd]
- [Python][python] >= 3.7
- [Setup at least one minikube VM][minikube] or [kind instance][kind] alternatively

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

Clone the repository into a location of your choice.
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

### Setup

#### Configuration

First, the configuration files need to be generated with a script. They can
then be modified at will.

```bash
# First, start the generate script to have initial config files
krake_generate_config config/*.template rok.yaml.template

krake_generate_config --allow-anonymous --static-authentication-enabled config/api.yaml.template

# You can then modify each file at your preference.
# afterwards create that folder which is expected:
sudo mkdir /etc/krake

# Last, copy generated files to that directory with
sudo cp *.yaml /etc/krake

# Optional: you can use the rok configuration template as you prefer. It can also be generated.
# Otherwise rok will use the default configuration
krake_generate_config rok.yaml.template
```

The `--allow-anonymous` and `--static-authentication-enabled` options set the API with
minimal authentication and authorization protections. It should not be used with a
production deployment, but are easier to work with in a test deployment. For more
information, take a look at the "Security principles" chapter of the [Admin Documentation][admin-docs].

#### Bootstrapping the database

The `etcd` database can be bootstrapped, by adding resources to it before
starting Krake:

```bash
# Run the neccessary etcd server first
# NOTE: Make sure `etcd` is in your $PATH
support/etcd
# Create roles for the RBAC authorization mode.
krake_bootstrap_db bootstrapping/base_roles.yaml

# Create metrics and metrics providers, for development purposes.
krake_bootstrap_db support/prometheus_metrics.yaml support/static_metrics.yaml
```

### Basic Usage

This provides a simple demonstration of Krake's functionalities. Please refer
to the [User Documentation][user-docs] for extended usage guidelines,
explanations, and examples.

#### Prepare Kubernetes environment

Initialize folders needed to store certificates and configuration files. These will be used in the next steps.

```bash
# In Krake folder execute this command
mkdir -p cluster_certs/certs cluster_certs/config
```

#### Setup Kubernetes cluster

Use any Kubernetes cluster you prefer. For starters, we recommend either [minikube](#minikube) or [kinD](#kind) as a first cluster.

##### Minikube

Create a minikube instance and download the kubeconfig file, as well as the certificate and key file
necessary to connect to your minikube instance.

```bash
minikube start
# Copy client and ca certificate to the above created folders
cp ~/.minikube/profiles/minikube/client.* cluster_certs/certs
cp ~/.minikube/ca.crt cluster_certs/certs

# Copy/generate config.yaml for later use with krake
minikube kubectl config view >> cluster_certs/config/minikube_conf.yaml

# Adjust the following paths in the copied config.yaml:
# - clusters.*.cluster.certificate-authority: "./cluster_certs/certs/ca.crt"
# - users.*.user.client-certificate: "./cluster_certs/certs/client.crt"
# - users.*.user.client-key: "./cluster_certs/certs/client.key"
```

**Attention:** If you have installed both kind and minikube this command would list both configurations. In this case, you should remove the kind configuration.

Here you can see an example configuration of minikube for Krake:

```bash
apiVersion: v1
clusters:
- cluster:
    certificate-authority: /home/USER/repos/krake/cluster_certs/certs/ca.crt
    extensions:
    - extension:
        last-update: Wed, 30 Mar 2022 12:36:02 CEST
        provider: minikube.sigs.k8s.io
        version: v1.23.2
      name: cluster_info
    server: https://192.168.49.2:8443
  name: minikube2
contexts:
- context:
    cluster: minikube2
    extensions:
    - extension:
        last-update: Wed, 30 Mar 2022 12:36:02 CEST
        provider: minikube.sigs.k8s.io
        version: v1.23.2
      name: context_info
    namespace: default
    user: minikube2
  name: minikube2
current-context: minikube2
kind: Config
preferences: {}
users:
- name: minikube2
  user:
    client-certificate: /home/USER/repos/krake/cluster_certs/certs/client.crt
    client-key: /home/USER/repos/krake/cluster_certs/certs/client.key
```

##### KinD

Create a kind instance and save the kubeconfig file in the `cluster_certs` directory

Prerequisites

- [Docker][docker]
- [kind][kind]

```bash
# Set the name of your k8s cluster
CLUSTER_NAME="mykindcluster"
# Start single node k8s cluster
kind create cluster --name $CLUSTER_NAME --kubeconfig cluster_certs/config/$CLUSTER_NAME.yaml
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
python3 -m krake.api

# Run the Garbage Collector
python3 -m krake.controller.gc

# Run the krake Scheduler
python3 -m krake.controller.scheduler

# Run the Kubernetes cluster controller
python3 -m krake.controller.kubernetes.cluster

# Run the Kubernetes application controller
python3 -m krake.controller.kubernetes.application

# Run the Infrastructure controller
python3 -m krake.controller.infrastructure
```

There is also a [script](https://gitlab.com/rak-n-rok/krake/-/snippets/2042674) (see snippets section on git) provided in the git repository to start all parts of Krake using „tmux“.

Finally we register the minikube (or kind) instance as a Krake backend and use Krake to
deploy an `echoserver` application.

```bash
# List current clusters; there should be none
$ rok kube cluster list
+------+-----------+--------+---------+----------+---------+-------+
| name | namespace | labels | created | modified | deleted | state |
+======+===========+========+=========+==========+=========+=======+
+------+-----------+--------+---------+----------+---------+-------+

# Register your minikube instance
$ rok kube cluster register -k cluster_certs/config/minikube_conf.yaml
+------------------+---------------------+
| name             | minikube2           |
| namespace        | system:admin        |
| labels           | None                |
| created          | 2022-03-30 16:00:21 |
| modified         | 2022-03-30 16:00:21 |
| deleted          | None                |
| state            | ONLINE              |
| custom_resources | []                  |
| metrics          | []                  |
| failing_metrics  | None                |
+------------------+---------------------+

# Now there is a cluster named minikube2
$ rok kube cluster list
+-----------+--------------+--------+---------------------+---------------------+---------+--------+
|   name    |  namespace   | labels |       created       |      modified       | deleted | state  |
+===========+==============+========+=====================+=====================+=========+========+
| minikube2 | system:admin | None   | 2022-03-30 16:00:21 | 2022-03-30 16:00:21 | None    | ONLINE |
+-----------+--------------+--------+---------------------+---------------------+---------+--------+

# Run an application on Krake
$ rok kube app create -f rak/functionals/echo-demo.yaml echo-demo
+-----------------------+---------------------+
| name                  | echo-demo           |
| namespace             | system:admin        |
| labels                | None                |
| created               | 2022-03-30 16:01:03 |
| modified              | 2022-03-30 16:01:03 |
| deleted               | None                |
| state                 | PENDING             |
| reason                | None                |
| services              | None                |
| allow migration       | True                |
| label constraints     | []                  |
| resources constraints | []                  |
| hooks                 | []                  |
| scheduled_to          | None                |
| scheduled             | None                |
| running_on            | None                |
+-----------------------+---------------------+

# Check the status of the application
$ rok kube app get echo-demo
+-----------------------+-------------------------------------------------------------------------------------------+
| name                  | echo-demo                                                                                 |
| namespace             | system:admin                                                                              |
| labels                | None                                                                                      |
| created               | 2022-03-30 16:01:03                                                                       |
| modified              | 2022-03-30 16:01:05                                                                       |
| deleted               | None                                                                                      |
| state                 | RUNNING                                                                                   |
| reason                | None                                                                                      |
| services              | echo-demo: 192.168.49.2:30285                                                             |
| allow migration       | True                                                                                      |
| label constraints     | []                                                                                        |
| resources constraints | []                                                                                        |
| hooks                 | []                                                                                        |
| scheduled_to          | {'kind': 'Cluster', 'api': 'kubernetes', 'name': 'minikube2', 'namespace': 'system:admin'}|
| scheduled             | 2022-03-30 16:01:04                                                                       |
| running_on            | {'kind': 'Cluster', 'api': 'kubernetes', 'name': 'minikube2', 'namespace': 'system:admin'}|
+-----------------------+-------------------------------------------------------------------------------------------+

# Access the application
$ curl 192.168.49.2:30285

Hostname: echo-demo-6ff4d6b744-mcxhb

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
  request_uri=http://192.168.49.2:8080/

Request Headers:
  accept=*/*
  host=192.168.49.2:30285
  user-agent=curl/7.74.0

Request Body:
  -no body in request-

# Delete the application
$ rok kube app delete echo-demo
+-----------------------+-----------------------------------------------+
| name                  | echo-demo                                     |
| namespace             | system:admin                                  |
| labels                | None                                          |
| created               | 2022-03-30 16:09:34                           |
| modified              | 2022-03-30 16:09:34                           |
| deleted               | 2022-03-30 16:11:30                           |
| state                 | FAILED                                        |
| reason                | code: NO_SUITABLE_RESOURCE                    |
|                       | message: No matching Kubernetes cluster found |
| services              | None                                          |
| allow migration       | True                                          |
| label constraints     | []                                            |
| resources constraints | []                                            |
| hooks                 | []                                            |
| scheduled_to          | None                                          |
| scheduled             | None                                          |
| running_on            | None                                          |
+-----------------------+-----------------------------------------------+

# Delete the cluster
$ rok kube cluster delete minikube2
+------------------+---------------------+
| name             | minikube2           |
| namespace        | system:admin        |
| labels           | None                |
| created          | 2022-03-30 16:00:21 |
| modified         | 2022-03-30 16:00:21 |
| deleted          | 2022-03-30 16:08:18 |
| state            | ONLINE              |
| custom_resources | []                  |
| metrics          | []                  |
| failing_metrics  | None                |
+------------------+---------------------+

# Check that cluster is deleted
$ rok kube cluster list
+------+-----------+--------+---------+----------+---------+-------+
| name | namespace | labels | created | modified | deleted | state |
+======+===========+========+=========+==========+=========+=======+
+------+-----------+--------+---------+----------+---------+-------+
```

### Advanced setups

Krake can use metrics and/or labels to schedule applications to specific clusters or
clusters to specific clouds based on the calculated metric values from the scheduling
algorithm and the label constraints of the resources.

Possible usable Metrics Providers can be found in the corresponding
[section][https://rak-n-rok.readthedocs.io/projects/krake/en/latest/dev/scheduling.html#metrics-and-metrics-providers]
.

To work with these more complex examples, see the respective User Stories about
[Metrics][https://rak-n-rok.readthedocs.io/projects/krake/en/latest/user/user-story/3-metrics-cluster.html]
and
[Labels][https://rak-n-rok.readthedocs.io/projects/krake/en/latest/user/user-story/2-labels-cluster.html]
.


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
[pypi]: https://pypi.org/project/krake/
