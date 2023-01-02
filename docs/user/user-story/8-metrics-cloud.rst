==================================
Scheduling a Cluster using Metrics
==================================

Goal: Schedule the cluster based on cloud metrics.

Introduction
============

.. note::

    Refer to the :ref:`user/user-story/3-metrics-cluster:Introduction` and
    :ref:`dev/scheduling:Metrics and Metrics Providers` for useful information about metrics.


The Krake scheduler can use metrics to compute the score of a Krake Cloud resource.
Each Cloud is associated with a list of metrics and their respective
weights for this Cloud. This list is defined by the user who added the Cloud
resource into Krake. A higher weight means that the metric has a higher influence in the
score: a metric with a low value, but a high weight may has more impact on the score
than a metric with a medium value but low weight. The Cloud metrics and
the computed score are then used in the Cluster scheduling process.


.. note::

    Note that file paths mentioned in this tutorial are relative to the root of the Krake repository.


Preparation
===========

Add the ``static_provider`` metrics provider using the bootstrap script (from the root of the Krake repository):

.. prompt:: bash $ auto

    cd <path_to_krake_root>
    krake_bootstrap_db support/static_metrics.yaml

Check that the GlobalMetricsProvider and GlobalMetrics objects have been successfully added:

.. prompt:: bash $ auto

    $ rok core globalmetricsprovider list
    +-----------------+-----------+--------+---------------------+---------------------+---------+---------+
    |      name       | namespace | labels |       created       |      modified       | deleted | mp_type |
    +=================+===========+========+=====================+=====================+=========+=========+
    | static_provider | None      | None   | 2000-01-01 08:00:00 | 2000-01-01 08:00:00 | None    | static  |
    +-----------------+-----------+--------+---------------------+---------------------+---------+---------+

    $ rok core globalmetric list
    +----------------------+-----------+--------+---------------------+---------------------+---------+-----------------+-----+-----+
    |         name         | namespace | labels |       created       |      modified       | deleted |    provider     | min | max |
    +======================+===========+========+=====================+=====================+=========+=================+=====+=====+
    | electricity_cost_1   | None      | None   | 2000-01-01 08:00:00 | 2000-01-01 08:00:00 | None    | static_provider | 0   | 1   |
    | green_energy_ratio_1 | None      | None   | 2000-01-01 08:00:00 | 2000-01-01 08:00:00 | None    | static_provider | 0   | 1   |
    +----------------------+-----------+--------+---------------------+---------------------+---------+-----------------+-----+-----+


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


Register ``os-cloud-1`` and ``os-cloud-2`` Clouds, and associate the ``electricity_cost_1`` and ``green_energy_ratio_1`` metrics to them using different weights to get different ranking scores:

.. note::

    Refer to the :ref:`user/user-story/6-infrastructure-provider:Register an existing OpenStack based cloud to Krake` for useful information about Cloud
    attributes.

.. prompt:: bash $ auto

    rok infra cloud register --global-metric electricity_cost_1 1 --global-metric green_energy_ratio_1 10 --type openstack --url <os-auth-url> --project <os-project-name> --username <os-username> --password <os-password> --infra-provider im-provider os-cloud-1
    rok infra cloud register --global-metric electricity_cost_1 10 --global-metric green_energy_ratio_1 1 --type openstack --url <os-auth-url> --project <os-project-name> --username <os-username> --password <os-password> --infra-provider im-provider os-cloud-2

.. tip::

    You do not need access to the two OpenStack projects for ``os-cloud-1`` and ``os-cloud-2`` registration.
    It is possible to register one OpenStack project two times in Krake with different metrics. Do not use
    this setup in the production environment!

The clouds ``os-cloud-1``/``-2`` have been defined with the following
weights for the two static metrics:

  +--------------------------+----------------+----------------+-------+
  |                          | ``os-cloud-1`` | ``os-cloud-2`` | Value |
  +==========================+================+================+=======+
  | ``electricity_cost_1``   | Weight: 1      | Weight: 10     | 0.9   |
  +--------------------------+----------------+----------------+-------+
  | ``green_energy_ratio_1`` | Weight: 10     | Weight: 1      | 0.1   |
  +--------------------------+----------------+----------------+-------+
  | Score                    | **1.9**        | **9.1**        |       |
  +--------------------------+----------------+----------------+-------+

  As the score of ``os-cloud-2`` is higher, it will been chosen, and the
  Cluster will be spawned on it. The score is computed like the following:

    .. math::

        10 \cdot 0.9 + 1 \cdot 0.1 = 9.1


Scheduling of a Cluster
=======================

Create the ``my-cluster`` cluster and check it is actually spawned on the second cloud:

.. prompt:: bash $ auto

    rok kube cluster create -f rak/functionals/im-cluster.yaml my-cluster
    rok kube cluster get my-cluster  -o json | jq .status.running_on  # Cluster is running on "os-cloud-2"

.. note::

    You can observe the scheduler logs in `DEBUG` mode to gather additional understanding of the scheduling mechanism.


Cleanup
=======

Delete the Cluster, both Clouds and the InfrastructureProvider.

.. code:: bash

    rok kube cluster delete my-cluster
    rok infra cloud delete os-cloud-1
    rok infra cloud delete os-cloud-2
    rok infra provider delete im-provider
