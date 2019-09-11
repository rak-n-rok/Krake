# Krake

Welcome to the Krake repository! :octopus:


## Rak'n'Rok vision: The Future of Compute

In the current paradigm, cloud infrastructure is typically built on top of a
few large to very large data centers. The user must blindly trust their code
and data to the centralized cloud service provider. This leads to security and
privacy concerns when they sit in a different regulation zone. Users located in
geographically distant places get high latencies and cannot run fast or
real-time applications. Finally, the energy efficiency optimization of a
single site is reaching its limits.

Because it can overcome all these concerns, we are convinced that the future
of cloud computing is decentralized. It is composed of a multitude of
heterogeneous geographically distributed data centers, offering different
technical layers (IaaS, PaaS, SaaS, ...) with different technologies
(OpenStack, VMware, ... OpenShift, Kubernetes, ...) for each layer. The
resulting aggregation is presented as one logical data center to the cloud
user.

Running a highly distributed cloud infrastructure allows the cloud user to
choose a site suiting his/her needs in term of regulation and latencies.
Furthermore, the cloud provider can take advantage of the distributed nature
of the cloud to optimize its resource utilization and improve its global
energy efficiency.

The Rak'n'Rok project builds a federation layer on top of a multitude of
heterogeneous sites and optimizes the efficiency and utilization through
scheduling and balancing of compute jobs.

Krake [ˈkʀaːkə] is the first (and at the moment only) software / tool of the
Rak'n'Rok project. It is also the central component of this approach as it
creates the data center aggregation and present a unique interface to the
cloud user. It uses a scheduling algorithm to distribute workloads across
multiple sites (and/or platforms) to achieve a more global optimization.
Multiple metrics can be incorporated into the scheduling decision, e.g. Power
Usage Effectiveness (PUE), Energy Reuse Factor (ERF) or cost of the
electricity but also latency between sites. The scheduling metrics can always
be extended or changed to fit the need of a specific technology stack.


## Get Started

In order to get started and play with Krake, you'll need to deploy besides
Krake itself at least one Kubernetes cluster to act as a backend for Krake. We
recommend
[Minikube](https://kubernetes.io/docs/setup/learning-environment/minikube/),
which is a simple way to get a Kubernetes environment for development
purposes. The whole process of deploying and testing a full Krake environment
is described in the [Developer
Documentation](CONTRIBUTING.md#setup-a-development-environment).


## Get in touch!

If you need help to setup things, have a question, or simply want to chat with
us, find us on our [Krake Matrix
room](https://riot.im/app/#/room/#krake:matrix.org)

If you wish to contribute, you can also check the
[Contributing](CONTRIBUTING.md) guide.


## Project Background

The Rak'n'Rok project have orginially been developped at Cloud&Heat. The
development of Krake was open-sourced in September 2019.
