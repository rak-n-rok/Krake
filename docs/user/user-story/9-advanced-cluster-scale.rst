==========================
Horizontal Cluster Scaling
==========================

Goal: Scale up and then down (horizontally) the actual Kubernetes cluster using Krake.

This is an advanced user scenario where the user should register an existing infrastructure provider backend (IM)
as well as an existing IaaS cloud deployment (OpenStack) before the actual cluster creation and scaling it horizontally.
Horizontal scaling is the act of adding (or removing) nodes of the same size to the cluster.


.. note::

    Keep in mind that Krake is able to actually **create** and then **scale** (update) the Kubernetes cluster by supported
    infrastructure providers. Please refer to the :ref:`dev/infrastructure-controller:Infrastructure Controller` and visit related
    user stories for more information about how the actual Kubernetes cluster could be managed by Krake.

.. note::

    Note that file paths mentioned in this tutorial are relative to the root of the Krake repository.


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


Please go through the :ref:`user/user-story/6-infrastructure-provider:Register an existing OpenStack based cloud to Krake`
and register an existing OpenStack cloud to Krake. Validate the cloud registration as follows:

.. prompt:: bash $ auto

    $ rok infra cloud list
    +----------+--------------+--------+---------------------+---------------------+---------+-----------+---------+----------------+--------+
    |   name   |  namespace   | labels |       created       |      modified       | deleted |   type    | metrics | infra_provider | state  |
    +==========+==============+========+=====================+=====================+=========+===========+=========+================+========+
    | os-cloud | system:admin | None   | 2000-01-01 08:00:00 | 2000-01-01 08:00:00 | None    | openstack | []      | im-provider    | ONLINE |
    +----------+--------------+--------+---------------------+---------------------+---------+-----------+---------+----------------+--------+


Create the Cluster
==================

Create the ``my-cluster`` cluster using the example TOSCA template stored in `rak/functionals/im-cluster.yaml`.
This TOSCA template should create a Kubernetes cluster with one control plane node and one worker node.

.. prompt:: bash $ auto

    rok kube cluster create -f rak/functionals/im-cluster.yaml my-cluster

The creation of the cluster can take up to 15 minutes to complete. The fully created and configured cluster
should be in the `ONLINE` state. You should also see that 2 from 2 nodes total are healthy (nodes: 2/2).
Validate them as follows:

.. prompt:: bash $ auto

    $ rok kube cluster get my-cluster
    +-----------------------+---------------------------------------------------------------------------------------------+
    | name                  | my-cluster                                                                                  |
    | namespace             | system:admin                                                                                |
    | labels                | None                                                                                        |
    | created               | 2000-01-01 08:00:00                                                                         |
    | modified              | 2000-01-01 08:00:00                                                                         |
    | deleted               | None                                                                                        |
    | state                 | ONLINE                                                                                      |
    | reason                | None                                                                                        |
    | custom_resources      | []                                                                                          |
    | metrics               | []                                                                                          |
    | failing_metrics       | None                                                                                        |
    | label constraints     | []                                                                                          |
    | metric constraints    | []                                                                                          |
    | scheduled_to          | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | scheduled             | 2000-01-01 08:00:00                                                                         |
    | running_on            | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | nodes                 | 2/2                                                                                         |
    | nodes_pid_pressure    | 0/2                                                                                         |
    | nodes_memory_pressure | 0/2                                                                                         |
    | nodes_disk_pressure   | 0/2                                                                                         |
    +-----------------------+---------------------------------------------------------------------------------------------+


Optionally, you can export the ``my-cluster`` kubeconfig file and validate the cluster health and nodes count
directly by the kubectl_ CLI. You can do this as follows (with the help of jq_ command-line JSON processor):


.. prompt:: bash $ auto

    rok kube cluster get my-cluster -o json | jq .spec.kubeconfig > kubeconfig.json

Access the  ``my-cluster`` cluster:

.. prompt:: bash $ auto

    $ kubectl --kubeconfig=kubeconfig.json get nodes
    NAME                     STATUS   ROLES                  AGE     VERSION
    kubeserver.localdomain   Ready    control-plane,master   10m     v1.22.9
    vnode-1.localdomain      Ready    <none>                 9m46s   v1.22.9



Scale up the Cluster
====================

Scale the created cluster up using the example TOSCA template stored in `rak/functionals/im-cluster-scale-up.yaml`.
This TOSCA template should add one worker node. Its size (flavor) should be the same as the size of the previously created worker node.

  Alternatively, you can adjust the worker node number on your own. In this case, find and adjust the ``wn_num``
  variable count in the TOSCA template:

  .. code:: yaml

      wn_num:
        type: integer
        description: Number of WNs in the cluster
        default: 2
        required: yes


Scale up the cluster:

.. prompt:: bash $ auto

    rok kube cluster update -f rak/functionals/im-cluster-scale-up.yaml my-cluster


The scaling of the cluster can take up to 5 minutes to complete. The fully scaled and configured cluster
should be in the `ONLINE` state. You should also see that one node has been successfully added i.e.
3 from 3 nodes total are healthy (nodes: 3/3).
Validate them as follows:

.. prompt:: bash $ auto

    $ rok kube cluster get my-cluster
    +-----------------------+---------------------------------------------------------------------------------------------+
    | name                  | my-cluster                                                                                  |
    | namespace             | system:admin                                                                                |
    | labels                | None                                                                                        |
    | created               | 2000-01-01 08:00:00                                                                         |
    | modified              | 2000-01-01 08:00:00                                                                         |
    | deleted               | None                                                                                        |
    | state                 | ONLINE                                                                                      |
    | reason                | None                                                                                        |
    | custom_resources      | []                                                                                          |
    | metrics               | []                                                                                          |
    | failing_metrics       | None                                                                                        |
    | label constraints     | []                                                                                          |
    | metric constraints    | []                                                                                          |
    | scheduled_to          | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | scheduled             | 2000-01-01 08:00:00                                                                         |
    | running_on            | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | nodes                 | 3/3                                                                                         |
    | nodes_pid_pressure    | 0/3                                                                                         |
    | nodes_memory_pressure | 0/3                                                                                         |
    | nodes_disk_pressure   | 0/3                                                                                         |
    +-----------------------+---------------------------------------------------------------------------------------------+


Access the  ``my-cluster`` cluster again and validate the cluster health and nodes count
directly by the kubectl_ CLI:

.. prompt:: bash $ auto

    $ kubectl --kubeconfig=kubeconfig.json get nodes
    NAME                     STATUS     ROLES                  AGE    VERSION
    kubeserver.localdomain   Ready      control-plane,master   34m    v1.22.9
    vnode-1.localdomain      Ready      <none>                 32m    v1.22.9
    vnode-2.localdomain      NotReady   <none>                 9m8s   v1.22.9



Scale down the Cluster
======================

Scale the created cluster down using the example TOSCA template stored in `rak/functionals/im-cluster-scale-down.yaml`.
This TOSCA template should remove one worker node.

  Alternatively, you can adjust the worker node number on your own. In this case, find and adjust the ``wn_num`` and
  ``removal_list`` variables in the TOSCA template:

  .. code:: yaml

      wn_num:
        type: integer
        description: Number of WNs in the cluster
        default: 1
        required: yes

      ...

      wn:
        type: tosca.nodes.indigo.Compute
        capabilities:
          scalable:
            properties:
              count: { get_input: wn_num }
              removal_list: ['2']

  The ``removal_list`` variable should be defined and should contain the ID(s) of the VM(s) which should be removed from the cluster.
  You can find the VM IDs in the ``cluster.status.nodes`` section of the Krake cluster resource as
  follows (with the help of jq_ command-line JSON processor):

  .. prompt:: bash $ auto

      $ rok kube cluster get my-cluster -o json | jq .status.nodes[].metadata.name
      "kubeserver.localdomain"
      "vnode-1.localdomain"
      "vnode-2.localdomain"


  Find the more detailed description about ``removal_list`` in the `IM documentation`_.

Scale down the cluster:

.. prompt:: bash $ auto

    rok kube cluster update -f rak/functionals/im-cluster-scale-down.yaml my-cluster


The scaling of the cluster can take up to 5 minutes to complete. The fully scaled and configured cluster
should be in the `ONLINE` state. You should also see that one node has been successfully removed i.e.
2 from 2 nodes total are healthy (nodes: 2/2).
Validate them as follows:

.. prompt:: bash $ auto

    $ rok kube cluster get my-cluster
    +-----------------------+---------------------------------------------------------------------------------------------+
    | name                  | my-cluster                                                                                  |
    | namespace             | system:admin                                                                                |
    | labels                | None                                                                                        |
    | created               | 2000-01-01 08:00:00                                                                         |
    | modified              | 2000-01-01 08:00:00                                                                         |
    | deleted               | None                                                                                        |
    | state                 | ONLINE                                                                                      |
    | reason                | None                                                                                        |
    | custom_resources      | []                                                                                          |
    | metrics               | []                                                                                          |
    | failing_metrics       | None                                                                                        |
    | label constraints     | []                                                                                          |
    | metric constraints    | []                                                                                          |
    | scheduled_to          | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | scheduled             | 2000-01-01 08:00:00                                                                         |
    | running_on            | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | nodes                 | 2/2                                                                                         |
    | nodes_pid_pressure    | 0/2                                                                                         |
    | nodes_memory_pressure | 0/2                                                                                         |
    | nodes_disk_pressure   | 0/2                                                                                         |
    +-----------------------+---------------------------------------------------------------------------------------------+


Access the  ``my-cluster`` cluster again and validate the cluster health and nodes count
directly by the kubectl_ CLI:

.. prompt:: bash $ auto

    $ kubectl --kubeconfig=kubeconfig.json get nodes
    NAME                     STATUS   ROLES                  AGE   VERSION
    kubeserver.localdomain   Ready    control-plane,master   40m   v1.22.9
    vnode-1.localdomain      Ready    <none>                 38m   v1.22.9


Cleanup
=======

Delete the Cluster, Cloud and the InfrastructureProvider.

.. code:: bash

    rok kube cluster delete my-cluster
    rok infra cloud delete os-cloud
    rok infra provider delete im-provider

Automatic Cluster scaling
=========================

Clusters can also be scaled automatically, if some specific conditions are met. The cloud that should be used must have
metrics and/or labels in order to provide a basis for the scheduling decision of Krake. Additionally, the users app needs
to have set the ``--auto-cluster-create`` flag, which enables the automatic creation of a new cluster, if the underlying
cloud has a better score than all the other clusters available.

After the creation of the app, a cluster should be created by infrastructure provider. This can be checked by looking at
the status of the app.

.. prompt:: bash $ auto

    $ rok kube app get my-app
    +-----------------------+-----------------------------------------------+
    | name                  | my-app                                        |
    | namespace             | system:admin                                  |
    | labels                | None                                          |
    | created               | 2000-01-01 08:00:00                           |
    | modified              | 2000-01-01 08:00:00                           |
    | deleted               | None                                          |
    | state                 | WAITING_FOR_CLUSTER_CREATION                  |
    | container_health      | 0 active / 0 failed / 0 succeeded / 1 desired |
    | services              | None                                          |
    | ...                   | ...                                           |
    +-----------------------+-----------------------------------------------+

After several minutes have elapsed (depending on the system where the cluster is deployed), a new cluster should have been
created. This cluster inherits the metrics and labels of the underlying cloud in order to provide the correct scheduling
location for the app.
When viewing the created cluster, the inherited values should be visible, since they're marked accordingly.

.. prompt:: bash $ auto

    $ rok kube cluster get auto-created-cluster
    +-----------------------+---------------------------------------------------------------------------------------------+
    | name                  | auto-created-cluster                                                                        |
    | namespace             | system:admin                                                                                |
    | labels                | location: DE (inherited)                                                                    |
    | created               | 2000-01-01 08:00:00                                                                         |
    | modified              | 2000-01-01 08:00:00                                                                         |
    | deleted               | None                                                                                        |
    | state                 | ONLINE                                                                                      |
    | reason                | None                                                                                        |
    | custom_resources      | []                                                                                          |
    | metrics               | [{'weight': 1.0, 'namespaced': False, 'name': 'electricity_cost_1', 'inherited': true}      |
    | failing_metrics       | None                                                                                        |
    | label constraints     | []                                                                                          |
    | metric constraints    | []                                                                                          |
    | scheduled_to          | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | scheduled             | 2000-01-01 08:00:00                                                                         |
    | running_on            | {'namespace': 'system:admin', 'kind': 'Cloud', 'name': 'os-cloud', 'api': 'infrastructure'} |
    | nodes                 | 2/2                                                                                         |
    | nodes_pid_pressure    | 0/2                                                                                         |
    | nodes_memory_pressure | 0/2                                                                                         |
    | nodes_disk_pressure   | 0/2                                                                                         |
    +-----------------------+---------------------------------------------------------------------------------------------+


.. _jq: https://stedolan.github.io/jq/
.. _kubectl: https://kubernetes.io/docs/tasks/tools/#kubectl
.. _IM documentation: https://imdocs.readthedocs.io/en/latest/REST.html?highlight=removal_list#im-rest-api
