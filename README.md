# Krake

Welcome to the Krake project! :octopus:

## Introduction

Krake aims


Krake comprises two Python packages:

 - krake -- Krake microservices as Python submodules
 - rok -- command line interface for the Krake API


## Quick Start

This section describes how to run Krake locally.

### Requirements

 - [etcdv3](https://github.com/etcd-io/etcd/releases/)
 - [Python](https://www.python.org/downloads/) >= 3.6
 - Deploy a [Minikube](https://kubernetes.io/docs/setup/learning-environment/minikube/)
 VM to act as backend for Krake

### Installation

All dependencies can be installed via the corresponding `setup.py` scripts.

```bash
# Install "krake" and "rok" with dev dependencies
pip install --editable krake/[dev]
pip install --editable rok/[dev]
```

### Running

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
#	This required "cfssl" to be installed.
support/pki "system:api-server"
# An additional certificate can be created for each components (schedulers and controller),
# by adding the appropriate path to the configuration file. Example:
support/pki "system:scheduler"

# Run the API server
python -m krake.api

# Run the scheduler
python -m krake.controller.scheduler

# Run the Kubernetes application controller
python -m krake.controller.kubernetes.application

# Run the Kubernetes cluster controller
python -m krake.controller.kubernetes.cluster
```

### Usage

Download the kubeconfig file, as well as the certificate and key file
necessary to connect to your Minikube instance.

```bash
$ MINIKUBE_IP="" # Fill in with the Minikube IP address

$ mkdir -p my_minikube/certs

$ scp ubuntu@my_minikube:~/.kubectl/config my_minikube
$ scp  ubuntu@$MINIKUBE_IP:~/.minikube/\{ca.crt,client.crt,client.key\} my_minikube/certs

$ sed -i "/certificate-authority/c\    certificate-authority: `pwd`/my_minikube/certs/ca.crt" my_minikube/config
$ sed -i "/server:/c\    server: https://$MINIKUBE_IP:8443" my_minikube/config
$ sed -i "/client-certificate/c\    client-certificate: `pwd`/my_minikube/certs/client.crt" my_minikube/config
$ sed -i "/client-key/c\    client-key: `pwd`/my_minikube/certs/client.key" my_minikube/config
```

Use the `rok` CLI to register your Minikube instance as a Krake backend:

```bash
$ rok kube cluster create my_minikube/config
```

Run an application on Krake:

```bash
$ cd rok/
$ rok kube app create -f nginx_demo.yaml nginx_demo
```

Check the status of the application:

```bash
$ rok kube app get nginx_demo
+-----------+---------------------+
| reason    | None                |
| name      | nginx_demo          |
| namespace | system              |
| user      | system:anonymous    |
| created   | 2019-08-14 13:42:16 |
| modified  | 2019-08-14 13:42:17 |
| state     | RUNNING             |
+-----------+---------------------+
```

Access the application:

```bash
$ curl 185.128.118.244:32212
<!DOCTYPE html>
<html>
<head>
<title>Welcome to nginx!</title>
<style>
    body {
        width: 35em;
        margin: 0 auto;
        font-family: Tahoma, Verdana, Arial, sans-serif;
    }
</style>
</head>
<body>
<h1>Welcome to nginx!</h1>
<p>If you see this page, the nginx web server is successfully installed and
working. Further configuration is required.</p>

<p>For online documentation and support please refer to
<a href="http://nginx.org/">nginx.org</a>.<br/>
Commercial support is available at
<a href="http://nginx.com/">nginx.com</a>.</p>

<p><em>Thank you for using nginx.</em></p>
</body>
</html>
```

Delete the application:

```bash
$ rok kube app delete nginx_demo
```

## Get in touch!

If you need help to setup things, have a question, or simply want to chat with
us, find us on our [the Krake Matrix
room](https://riot.im/app/#/room/#krake:matrix.org)

If you wish to contribute, you can also check the
[Contributing](CONTRIBUTING.md) guide.
