=================================================
Creation and deployment of a stateful application
=================================================

Goal: Create and deploy a stateful application to Krake.

Introduction to statefulness
============================

Statefulness with regard to an application means, that this application stores information about the changes since its
start and possible adapts according to these changes. A restart without these information would put the application
in a different state.
This type of application could best be described with a database filled with information or an AI model being trained
on a dataset. Both applications contain data that specifies their current state.

For an application like Krake, it is important to transfer the state of an application to the current location of this
application, e.g. during a migration. This must be done by Krake, because the applications are deployed via images,
which only start in their initial state. Providing the correct data should put these migrated or restarted applications
in their previous state.

Creating a stateful application
===============================

Creating a stateful application in Krake is easily done. The only requirement is, that migrations are enabled for the application (which is the default setting) and that the application has a PersistentVolumeClaim, where the data its holding will be saved.
In order to test a migration, it is also necessary to provide two clusters.

A possible example file can be found under `templates/applications/k8s/pvc-pod.yaml`. If this file should be deployed, it is also important to
add its observer schema file found under `templates/applications/observer-schema/pvc-pod-observer-schema.yaml`.

.. prompt:: bash $ auto

    $ rok kube app create pvc -f pvc-pod.yaml -O pvc-pod-observer-schema.yaml

This should create an application, that generates a log entry with the
current date and time every minute on the mounted volume.

Migrating a stateful application
================================

A migration of the application can be triggered exactly as described in
:ref:`user/user-story/2-labels-cluster:Introduction to Scheduling mechanisms`
and :ref:`user/user-story/3-metrics-cluster:Scheduling an Application using Metrics`.
In this case, a migration will be triggered by changing the metrics weights.

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

After this step, the scheduler should schedule the application to the second cluster. The application should be migrated
with all its files depending on the available network speed and the file size. You can approve this by checking the current
location of the application

.. prompt:: bash $ auto

    $ rok kube app get pvc
    +-----------------------+----------------------------------------------------------------------------------------------+
    | name                  | pvc                                                                                          |
    | namespace             | system:admin                                                                                 |
    | labels                | None                                                                                         |
    | created               | 2000-01-01 08:00:00                                                                          |
    | modified              | 2000-01-01 08:00:00                                                                          |
    | deleted               | None                                                                                         |
    | state                 | RUNNING                                                                                      |
    | container_health      | 1 active / 0 failed / 0 succeeded / 1 desired                                                |
    | services              | None                                                                                         |
    | scheduled_to          | {'namespace': 'system:admin', 'kind': 'Cluster', 'name': 'cluster2', 'api': 'kubernetes'}    |
    | scheduled             | 2000-01-01 08:00:00                                                                          |
    | running_on            | {'namespace': 'system:admin', 'kind': 'Cluster', 'name': 'os-cluster2', 'api': 'kubernetes'} |
    +-----------------------+----------------------------------------------------------------------------------------------+
