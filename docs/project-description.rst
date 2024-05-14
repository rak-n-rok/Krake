===================
Project description
===================

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
The goal of Krake is to combine multiple cloud resources into a virtual resource.
This should provide the ability to deploy applications to suitable locations
with regards to things like compute power, energy consumption or available GPUs.

The Krake_ repository contains the code for this project. There are multiple subprojects
integrated into it at the moment.

Components
==========

-----
Krake
-----

The Krake module provides the main features of this project. It contains all services that compose a complete Krake instance as well as some additional modules.
This module also provides the requirements to install Krake in a system, and makes it possible to emit a PyPi package, which can be found in the PyPi_ repository.

--------
krakectl
--------

krakectl provides a command-line interface to interact with Krake. It provides simple commands, that are used to interact with the Krake API.
It is suggested, that this module gets placed in its own repository in the future, in order to simplify the project structure.

---
rak
---

rak (named partly from the old project name `rak'n'rok`) was first envisioned to be a tool to set up a working Krake infrastructure. At this point in time, the module/directory is used to store example K8s files, demo K8s files, end-to-end tests and additional files to create a working testing environment.
It is likely, that this directory gets removed in the future. The files in them would therefore be rellocated to more descriptive directories.


.. _Krake: https://gitlab.com/rak-n-rok/krake
.. _PyPi: https://pypi.org/project/krake/
