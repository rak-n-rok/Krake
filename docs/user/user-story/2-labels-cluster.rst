===================================================================
Scheduling an Application using ``Labels`` and ``LabelConstraints``
===================================================================

Goal: Explore the labels mechanisms and schedule an application based on labels and label constraints

Introduction to Scheduling mechanisms
=====================================

.. note::

    After its initial scheduling, an application location is re-evaluated every 60 seconds by the Scheduler - the so-called "rescheduling". In the following scenarios, we observe both the initial scheduling of an application, and a migration triggered by the rescheduling. To correctly observe this mechanism, it is recommended to check the Scheduler logs, the Application status, and the resources running on the Kubernetes clusters directly, by running the following commands in separate terminals:

- Watch the ``echo-demo`` Kubernetes ``Application`` status, and more precisely its current location:

.. prompt:: bash $ auto

    $ watch "krakectl kube app get echo-demo -o json | jq .status.running_on"

- Watch Scheduler logs:

.. prompt:: bash $ auto

    $ docker logs -f krake_krake-ctrl-scheduler_1

- Observe k8s resources on both Minikube clusters:

.. prompt:: bash $ auto

    $ watch kubectl --kubeconfig clusters/config/minikube-cluster-1 get all

.. prompt:: bash $ auto

    $ watch kubectl --kubeconfig clusters/config/minikube-cluster-2 get all

Preparation
===========

- Register the two clusters with a ``location`` ``Label``.

.. note::
    Each label always have a key and a value. We follow the same specifications as
    Kubernetes_.

.. prompt:: bash $ auto

    $ krakectl kube cluster register -k clusters/config/minikube-cluster-1 -l location=DE
    $ krakectl kube cluster register -k clusters/config/minikube-cluster-2 -l location=SK

Spawn the demo application
==========================

- Create an application with a ``location`` ``LabelConstraints``, and observe where it is deployed.

.. prompt:: bash $ auto

    $ krakectl kube app create -f git/krake/templates/applications/k8s/echo-demo.yaml echo-demo -L location=DE
    $ krakectl kube app get echo-demo -o json | jq .status.running_on

Observe a migration
===================

- Update an application's ``LabelConstraints`` and observe the migration to the second Kubernetes cluster.

.. prompt:: bash $ auto

    $ krakectl kube app update echo-demo -L location=SK
    $ krakectl kube app get echo-demo -o json | jq .status.running_on  # The Application is now running on "minikube-cluster-2"

Cleanup
=======

- Delete the ``echo-demo`` Kubernetes ``Application`` and both Krake Kubernetes ``Clusters``

.. prompt:: bash $ auto

    $ krakectl kube app delete echo-demo
    $ krakectl kube cluster delete minikube-cluster-1
    $ krakectl kube cluster delete minikube-cluster-2


.. _Kubernetes: https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/#syntax-and-character-set
