==============================================================
Scheduling a Cluster using ``Labels`` and ``LabelConstraints``
==============================================================

Goal: Explore the labels mechanisms and schedule a Cluster based on labels and label constraints.

Introduction
============

.. note::

    Refer to the :ref:`dev/scheduling:Label constraints` for useful information about label constraints.

Krake allows the user to define a label constraint and restrict the deployment of
Cluster resources only to cloud backends that match **all** defined labels.


Preparation
===========

Please go through the :ref:`user/user-story/6-infrastructure-provider:Preparation` as well as
through the :ref:`user/user-story/6-infrastructure-provider:Register an existing infrastructure provider to Krake`
and register an infrastructure provider. Validate the infrastructure provider registration as follows:

.. prompt:: bash $ auto

    $ rok infra provider list
    +-------------+--------------+--------+---------------------+---------------------+---------+------+-----------------------+
    |    name     |  namespace   | labels |       created       |      modified       | deleted | type |          url          |
    +=============+==============+========+=====================+=====================+=========+======+=======================+
    | im-provider | system:admin | None   | 2000-01-01 08:00:00 | 2000-01-01 08:00:00 | None    | im   | http://localhost:8800 |
    +-------------+--------------+--------+---------------------+---------------------+---------+------+-----------------------+

Register ``os-cloud-1`` and ``os-cloud-2`` Clouds, and associate the `location` Label.
Each label always has a key and a value. We follow the same specifications as the Kubernetes_ project.

.. note::

    Refer to the :ref:`user/user-story/6-infrastructure-provider:Register an existing OpenStack based cloud to Krake` for useful information about Cloud
    attributes.

.. prompt:: bash $ auto

    rok infra cloud register -l location=DE --type openstack --url <os-auth-url> --project <os-project-name> --username <os-username> --password <os-password> --infra-provider im-provider os-cloud-1
    rok infra cloud register -l location=SK --type openstack --url <os-auth-url> --project <os-project-name> --username <os-username> --password <os-password> --infra-provider im-provider os-cloud-2

.. tip::

    You do not need access to the two OpenStack projects for ``os-cloud-1`` and ``os-cloud-2`` registration.
    It is possible to register one OpenStack project two times in Krake with different labels. Do not use
    this setup in the production environment!

Scheduling of a Cluster
=======================

Create ``my-cluster`` cluster with a `location` LabelConstraints, and observe where it is spawned.

.. prompt:: bash $ auto

    rok kube cluster create -f git/krake/rak/functionals/im-cluster.yaml my-cluster -L location=SK
    rok kube cluster get my-cluster -o json | jq .status.running_on  # Cluster is running on "os-cloud-2"

.. note::

    You can observe the scheduler logs in `DEBUG` mode to gather additional understanding of the scheduling mechanism.


Cleanup
=======

Delete the Cluster, both Clouds and the IM InfrastructureProvider.

.. code:: bash

    rok kube cluster delete my-cluster
    rok infra cloud delete os-cloud-1
    rok infra cloud delete os-cloud-2
    rok infra provider delete im-provider


.. _Kubernetes: https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/#syntax-and-character-set
