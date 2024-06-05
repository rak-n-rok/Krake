=======================================
Scheduling an Application Using Metrics
=======================================

Goal: Explore the metrics mechanisms and schedule an application based on cluster metrics.

.. note::

    Refer to the :ref:`user/user-story/2-labels-cluster:Introduction to Scheduling mechanisms` for useful commands to observe the migration mechanism.


Introduction
============

Metrics in the Krake sense have two meanings. The first one is an actual value for some
parameter, which can be measured or computed in the real world. For instance the current
space available on a data center, its latency, the amount of green energy used by the
data center could all be metrics. This value may be dynamic and change over time.
A ``GlobalMetric`` is also a resource in Krake. It represents an actual metric,
is stored in the database, and defines a few elements, such as the minimum and
maximum values (Krake only considers numbers for the metrics).

The Krake scheduler can use these metrics to compute the score of a Krake Kubernetes
``Cluster``. Each cluster is associated with a list of metrics and their respective
weights for this cluster. This list is defined by the user who added the ``Cluster``
resource into Krake. A higher weight means that the metric has a higher influence in the
score: a metrics with a low value, but a high weight may have more impact on the score
than a metric with medium value but low weight. The ``Cluster`` metrics and
the computed score is then used in the ``Application`` scheduling process.

``Metrics`` and ``GlobalMetrics`` are provided with a minimum and maximum value, which define the
range in which the final values will be. Alternatively, specific allowed values
(either via command line paramater, e.g. ``--allowed-values 1 2 3`` or as a list in a bootstrap file,
see :ref:`support/prometheus_metrics.yaml``) can be set.

For Krake to fetch the current value of a metric, a user needs to define where and how
it can be requested. ``GlobalMetricsProvider`` resources can be created for this
purpose. They have different types, to support different technologies. There is for
example a support for Prometheus_. The ``GlobalMetricsProvider`` resource will define
the URL of the Prometheus instance and some other metadata, and afterwards, Krake's
scheduler can automatically fetch the current value of the metrics for the score's
computation.

The static providers are simple metric providers usually only set during tests. They
allow a Krake resource to be associated with simple metrics, for which the value can be
fetched easily, without having to set up a whole infrastructure.

The static providers thus give values for ``GlobalMetric`` resources. This value is
only defined in the resource (stored in the database). Updating the
``GlobalMetricsProvider`` resource definition thus implies updating the value of
the metrics.

An example of a static ``GlobalMetricsProvider`` resource is given in the following.
It is used in the next steps of this guide. As explained, the value of the metrics
it provides are directly set inside its definition:

.. code:: yaml

    api: core
    kind: GlobalMetricsProvider
    metadata:
      created: '2020-01-21T10:50:11.500376'
      deleted: null
      finalizers: []
      labels: {}
      modified: '2020-01-21T10:50:11.500376'
      name: static_provider
      namespace: null
      owners: []
      uid: 26ef45e8-e5c8-44fe-8a7f-a3f40944c925
    spec:
      static:
        metrics:
          electricity_cost_1: 0.9  # Set the value that will be provided for this metric
          green_energy_ratio_1: 0.1  # Set the value that will be provided for this metric
      type: static

To get additional information about the metrics and metrics providers, please read the
documentation about them, see :ref:`dev/scheduling:Metrics and Metrics Providers`.


Preparation
===========

- Add the ``static_provider`` metrics provider using the bootstrap script (from the root of the Krake repository):

.. prompt:: bash $ auto

    $ cd <path_to_krake_root>
    $ krake_bootstrap_db support/static_metrics.yaml

- Check that the ``GlobalMetricsProvider`` and ``GlobalMetrics`` objects have been successfully added:

.. prompt:: bash $ auto

    $ rok core globalmetricsprovider get static_provider
    +-----------+---------------------------+
    | name      | static_provider           |
    | namespace | None                      |
    | labels    | None                      |
    | created   | 2000-01-01 08:00:00       |
    | modified  | 2000-01-01 08:00:00       |
    | deleted   | None                      |
    | type      | static                    |
    | metrics   | electricity_cost_1: 0.9   |
    |           | green_energy_ratio_1: 0.1 |
    +-----------+---------------------------+
    $ rok core globalmetric get electricity_cost_1
    +-----------+---------------------+
    | name      | electricity_cost_1  |
    | namespace | None                |
    | labels    | None                |
    | created   | 2000-01-01 08:00:00 |
    | modified  | 2000-01-01 08:00:00 |
    | deleted   | None                |
    | provider  | static_provider     |
    | min       | 0                   |
    | max       | 1                   |
    +-----------+---------------------+
    $ rok core globalmetric get green_energy_ratio_1
    +-----------+----------------------+
    | name      | green_energy_ratio_1 |
    | namespace | None                 |
    | labels    | None                 |
    | created   | 2000-01-01 08:00:00  |
    | modified  | 2000-01-01 08:00:00  |
    | deleted   | None                 |
    | provider  | static_provider      |
    | min       | 0                    |
    | max       | 1                    |
    +-----------+----------------------+


- Register ``minikube-cluster-1`` and ``minikube-cluster-2`` clusters, and associate the ``electricity_cost_1`` and ``green_energy_ratio_1`` metrics to them using different weights to get different ranking scores:

.. prompt:: bash $ auto

    $ rok kube cluster register -k clusters/config/minikube-cluster-1 --global-metric electricity_cost_1 10 --global-metric green_energy_ratio_1 1
    $ rok kube cluster register -k clusters/config/minikube-cluster-2 --global-metric electricity_cost_1 1 --global-metric green_energy_ratio_1 10

- The clusters ``minikube-cluster-1``/``-2`` have been defined with the following
  weights for the two static metrics:

  +--------------------------+------------------------+------------------------+-------+
  |                          | ``minikube-cluster-1`` | ``minikube-cluster-2`` | Value |
  +==========================+========================+========================+=======+
  | ``electricity_cost_1``   | Weight: 10             | Weight: 1              | 0.9   |
  +--------------------------+------------------------+------------------------+-------+
  | ``green_energy_ratio_1`` | Weight: 1              | Weight: 10             | 0.1   |
  +--------------------------+------------------------+------------------------+-------+
  | Score                    | **9.1**                | **1.9**                |       |
  +--------------------------+------------------------+------------------------+-------+

  As the score of ``minikube-cluster-1`` is higher, it will been chosen, and the
  Application will be deployed on it. The score is computed like the following:

    .. math::

        10 \cdot 0.9 + 1 \cdot 0.1 = 9.1


Scheduling of an application
============================

- Create the ``echo-demo`` application and check it is actually deployed on the first
  cluster:

.. prompt:: bash $ auto

    $ rok kube app create -f git/krake/templates/applications/k8s/echo-demo.yaml echo-demo
    $ rok kube app get echo-demo  # See "running_on": the Application is running on "minikube-cluster-1"

.. note::

    You can observe the scheduler logs in ``DEBUG`` mode to gather additional understanding of the scheduling mechanism.

Observe a migration
===================

- The Scheduler regularly performs a check, to ensure the current cluster on which an
  Application is running is the best, depending on its score. This check is done by
  default every minute (see the configuration of the
  :ref:`user/configuration:Scheduler`). If an available cluster with a better score than
  the one of the current cluster is found, the Application is migrated from the current
  to the better cluster.

  As the score is computed using the metrics, we can trigger the migration by updating
  the exported value of the metrics in the ``static_provider`` ``GlobalMetricsProvider``
  resource. The following command updates the value of the static metrics:

  * ``electricity_cost_1``: to have a value of 0.1;
  * ``green_energy_ratio_1``: to have a value of 0.9;

  +--------------------------+------------------------+------------------------+-----------+
  |                          | ``minikube-cluster-1`` | ``minikube-cluster-2`` | New value |
  +==========================+========================+========================+===========+
  | ``electricity_cost_1``   | Weight: 10             | Weight: 1              | 0.1       |
  +--------------------------+------------------------+------------------------+-----------+
  | ``green_energy_ratio_1`` | Weight: 1              | Weight: 10             | 0.9       |
  +--------------------------+------------------------+------------------------+-----------+
  | Score                    | **1.9**                | **9.1**                |           |
  +--------------------------+------------------------+------------------------+-----------+

.. note::

    This is not the actual score but a simplification, as stickiness is also part of the
    computation, see :ref:`dev/scheduling:Scheduling of Applications`

- Update the value of the metrics, by updating the ``static_provider`` GlobalMetricsProvider:

.. prompt:: bash $ auto

    $ rok core globalmetricsprovider update static_provider --metric electricity_cost_1 0.1 --metric green_energy_ratio_1 0.9
    +-----------+---------------------------+
    | name      | static_provider           |
    | namespace | None                      |
    | labels    | None                      |
    | created   | 2021-04-08 08:04:23       |
    | modified  | 2021-04-08 08:10:34       |
    | deleted   | None                      |
    | type      | static                    |
    | metrics   | electricity_cost_1: 0.1   |
    |           | green_energy_ratio_1: 0.9 |
    +-----------+---------------------------+


- Now, by waiting a bit (maximum 60 seconds if you kept the default configuration), the
  Scheduler should have checked the new values of the metrics, and have requested a
  migration of the Application onto ``minikube-cluster-2``, which has now the better
  score:

.. prompt:: bash $ auto

    $ rok kube app get echo-demo  # See "running_on": the Application is running on "minikube-cluster-2"


Cleanup
=======

- Delete the ``echo-demo`` Kubernetes ``Application`` and both Kubernetes ``Clusters``.

.. code:: bash

    $ rok kube app delete echo-demo
    $ rok kube cluster delete minikube-cluster-1
    $ rok kube cluster delete minikube-cluster-2


.. _Prometheus: https://prometheus.io/
