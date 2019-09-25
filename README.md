# Krake

Welcome to the Krake repository! :octopus:

Krake [ˈkʀaːkə] is an orchestrator engine for containerized and virtualized
workloads accross distributed and heterogeneous cloud platforms. It creates a
thin layer of aggregaton on top of the different platforms (such as OpenStack,
Kubernetes or OpenShift) and presents them through a single interface to the
cloud user. The user's workloads are scheduled depending on both user
requirements (hardware, latencies, cost) and platforms characteristics (energy
efficiency, load). The scheduling algorithm can be optimized for example on
latencies, cost, or energy. 
Krake can be leveraged for a wide range of application scenarios such as 
central management of distributed compute capacities as well as application 
management in Edge Cloud infrastructures.


## Getting Started

In order to get started and play with Krake, you'll need to deploy Krake
plus at least one Kubernetes cluster to act as a backend for Krake. We
recommend
[Minikube](https://kubernetes.io/docs/setup/learning-environment/minikube/),
which is a simple way to get a Kubernetes environment for development
purposes. The whole process of deploying and testing a full Krake environment
is described in the [Contributor
Guidelines](CONTRIBUTING.md#setup-a-development-environment).


## Get in touch!

If you need help to setup things, have a question, or simply want to chat with
us, find us on our [Krake Matrix
room](https://riot.im/app/#/room/#krake:matrix.org)

If you wish to contribute, you can also check the
[Contributing](CONTRIBUTING.md) guide.


## Project Background

The Rak'n'Rok project has initially been developped at Cloud&Heat. The
development of Krake was transformed to an open source project in September 2019.
