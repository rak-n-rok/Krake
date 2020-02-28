============================
Scheduling using ``Metrics``
============================

Goal: Explore the metrics mechanisms.

.. note::

    Refer to the :ref:`user/user-story/2-labels:Introduction to Scheduling mechanisms` for useful commands to observe the migration mechanism.

Preparation
===========

- Add the ``static_provider`` ``MetricsProvider`` using the bootstrap script (from the root of the Krake repository):

.. prompt:: bash $ auto

    $ krake_bootstrap_db support/static_metrics.yaml

- Check that the ``MetricsProvider`` and ``Metrics`` objects have been successfully added:

.. prompt:: bash $ auto

    $ sudo apt install etcd-client
    $ ETCDCTL_API=3 etcdctl get --prefix /metricsprovider/static_provider
    {"metadata": {"namespace": null, "uid": "26ef45e8-e5c8-44fe-8a7f-a3f40944c925", "labels": {}, "modified": "2020-01-21T10:50:11.500376", "deleted": null, "name": "static_provider", "owners": [], "created": "2020-01-21T10:50:11.500376", "finalizers": []}, "spec": {"type": "static", "static": {"metrics": {"electricity_cost_1": 0.9, "latency_1": 0.1}}}, "api": "core", "kind": "MetricsProvider"}
    $ ETCDCTL_API=3 etcdctl get --prefix /metric/electricity_cost_1
    {"metadata": {"namespace": null, "uid": "a3f2ac17-4557-4b7c-b545-45925c48cb7b", "labels": {}, "modified": "2020-01-21T10:50:11.491919", "deleted": null, "name": "electricity_cost_1", "owners": [], "created": "2020-01-21T10:50:11.491919", "finalizers": []}, "spec": {"min": 0.0, "max": 1.0, "provider": {"name": "static_provider", "metric": "electricity_cost_1"}}, "api": "core", "kind": "Metric"}
    $ ETCDCTL_API=3 etcdctl get --prefix /metric/latency_1
    {"metadata": {"namespace": null, "uid": "078a4035-8493-4638-ab99-4b09a4a095ed", "labels": {}, "modified": "2020-01-21T10:50:11.478440", "deleted": null, "name": "latency_1", "owners": [], "created": "2020-01-21T10:50:11.478440", "finalizers": []}, "spec": {"min": 0.0, "max": 1.0, "provider": {"name": "static_provider", "metric": "latency_1"}}, "api": "core", "kind": "Metric"}

- Register ``minikube-cluster-demoenv-1`` and ``minikube-cluster-demoenv-1`` clusters, and associate the ``electricity_cost_1`` and ``latency_1`` ``Metrics`` to them using different weights to get different ranking scores:

.. prompt:: bash $ auto

    $ rok kube cluster create clusters/config/minikube-cluster-demoenv-1 --metric electricity_cost_1 10 --metric latency_1 1
    $ rok kube cluster create clusters/config/minikube-cluster-demoenv-2 --metric electricity_cost_1 1 --metric latency_1 10

Scheduling of an application
============================

- Create the ``echo-demo`` application and check where it is deployed.

.. prompt:: bash $ auto

    $ rok kube app create -f git/krake/rak/functionals/echo-demo.yaml echo-demo
    $ rok kube app get echo-demo -f json | jq .status.running_on  # The Application is running on "minikube-cluster-demoenv-1"

.. note::

    You can observe the scheduler logs in ``DEBUG`` mode to gather additional understanding of the scheduling mechanism.

Observe a migration
===================

- Trigger the migration by updating the exported value of the Metrics in the StaticProvider resource.

.. prompt:: bash $ auto

    $ ETCDCTL_API=3 etcdctl put /metricsprovider/static_provider -- '{"metadata": {"namespace": null, "uid": "26ef45e8-e5c8-44fe-8a7f-a3f40944c925", "labels": {}, "modified": "2020-01-21T10:50:11.500376", "deleted": null, "name": "static_provider", "owners": [], "created": "2020-01-21T10:50:11.500376", "finalizers": []}, "spec": {"type": "static", "static": {"metrics": {"electricity_cost_1": 0.1, "latency_1": 0.9}}}, "api": "core", "kind": "MetricsProvider"}'
    $ rok kube app get echo-demo -f json | jq .status.running_on  # The Application is now running on "minikube-cluster-demoenv-2"

Cleanup
=======

- Delete the ``echo-demo`` Kubernetes ``Application`` and both Kubernetes ``Clusters``.

.. code:: bash

    $ rok kube app delete echo-demo
    $ rok kube cluster delete minikube-cluster-demoenv-1
    $ rok kube cluster delete minikube-cluster-demoenv-2

