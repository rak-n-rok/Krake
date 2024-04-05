=========================
Infrastructure Controller
=========================

This part of the documentation presents the Infrastructure Controller control plane component, and
how the life-cycle management of real-world Kubernetes clusters is handled.

.. note::

   For a description of the architecture and work flow of a controller refer to
   :ref:`dev/controllers`.


The Infrastructure Controller should process Clusters that are bound (scheduled) to
any Cloud or GlobalCloud resource. It should also process Clusters that were deleted and contain
an Infrastructure Controller specific deletion finalizer: `infrastructure_resources_deletion`.

.. note::

    Refer to the :ref:`dev/scheduling:Cluster handler` for useful information about cluster scheduling process.


Bound GlobalCloud or Cloud resources correspond to an IaaS cloud deployment
(e.g. OpenStack, AWS, etc.) that will be managed by the infrastructure provider backend.
Krake currently supports only OpenStack_ as a GlobalCloud or Cloud backend.

The GlobalCloud or Cloud resource should contain a reference to the GlobalInfrastructureProvider or
InfrastructureProvider resource that corresponds to an infrastructure provider backend, that is able
to deploy infrastructures (e.g. Virtual machines, Kubernetes clusters, etc.) on IaaS cloud deployments.
Krake currently supports only IM_ (Infrastructure Manager) as an infrastructure provider backend.

.. note::

    The `global` resource (e.g. GlobalInfrastructureProvider, GlobalCloud) is a
    non-namespaced resource that could be used by any (even namespaced) Krake
    resource. For example, the GlobalCloud resource could be used by any Cluster
    which needs to be scheduled to some cloud.

.. toctree::
    :hidden:

    infrastructure-controller
    infrastructure-provider-cluster-observer

Reconciliation loop
===================

In the following section, we describe what happens in the Infrastructure Controller
when receiving a Cluster resource.

.. figure:: /img/infrastructure_controller_reconciliation_example.png


Step 1
------

Infrastructure Controller handles Cluster resources that have been deleted and contain
the  `infrastructure_resources_deletion` (1).
If the above is true, the controller requests the cloud's infrastructure provider for the deletion of the actual
cluster counterparts (1a). The controller waits in an infinite loop for the actual cluster
deletion (1b). Finally, the controller removes the finalizer from the Cluster resource (1c).
This allows the garbage collector controller to remove the Cluster resource from the Krake DB.


Step 2
------

The Infrastructure Controller handles Cluster resources that are bound (scheduled) to
any Cloud or GlobalCloud resource (2). The Cloud or GlobalCloud resource contains cloud API
endpoints and access credentials as well as a reference to the infrastructure provider
resource through which Krake can manage actual Kubernetes clusters on the bounded cloud.


Step 3
------

If the Cluster is bound (scheduled) to some cloud, the controller recursively looks for
all the changes between the desired state (which is represented by the ``cluster.spec.tosca``
field) and the current state (which is stored in the ``cluster.status.last_applied_tosca``
field) (3).


Step 4
------

If there is a difference between the desired and the current state, the controller checks
the resource field ``cluster.status.running_on`` (4).

If it is empty, the resource is considered new, and the controller requests the cloud's
infrastructure provider for the creation of the actual cluster counterparts (4a).
The TOSCA template stored in ``cluster.spec.tosca`` represents the desired state and it is applied here.
After a successful request for creation, the ``cluster.status.last_applied_tosca`` field is updated
with the copy of the ``cluster.spec.tosca`` field as well as the ``cluster.status.running_on`` is
updated with the copy of the ``cluster.status.scheduled_to`` field (scheduled_to field contains
the bound cloud resource reference).

If the ``cluster.status.running_on`` field is not empty, the controller requests the cloud's
infrastructure provider for the reconciliation (update) of the actual cluster counterparts (4b).
The TOSCA template stored in ``cluster.spec.tosca`` represents the desired state and it is applied here.
After a successful request for reconciliation, the ``cluster.status.last_applied_tosca`` field is updated
with the copy of the ``cluster.spec.tosca`` field.

Then, the controller waits for the cluster is being successfully configured in the infinite loop (7).


Step 5
------

If the desired and the current state are in sync, the controller checks whether the Cluster resource state
is ``FAILING_RECONCILIATION`` (5). If so, the controller requests the cloud's infrastructure provider
for the reconfiguration of the actual cluster counterparts (5a). This is a "special" call that may or may not be
required in case of infrastructure provider failures (e.g. restart). It depends on the underlying infrastructure
provider implementation which action should be performed under the hood of the abstract infrastructure
controller function `reconfigure`.

Then, the controller waits for the cluster is being successfully configured in the infinite loop (7).


Step 6
------

The controller finishes the reconciliation if the Cluster resource state is ``ONLINE`` or ``CONNECTING`` (6). If it is not the case,
the controller waits for the cluster is being successfully configured in the infinite loop (7).


Step 7
------

The controller waits in an infinite loop for the actual cluster creation/reconciliation/(re)configuration (7).
When the actual cluster is fully configured, the controller updates the Cluster state to
``CONNECTING`` and also saves its kubeconfig manifest to the ``cluster.spec.kubeconfig`` field.
Finally, the controller finishes the reconciliation.


.. note::

    Once the Cluster is configured, has ``CONNECTING`` state, and contains kubeconfig manifest, the
    :ref:`dev/kubernetes-cluster-controller:Kubernetes Cluster Controller` takes over the Cluster and
    :ref:`dev/kubernetes-cluster-observer:Kubernetes Cluster Observer` observes its actual status.

States
======

A Kubernetes Cluster resource managed by the Infrastructure Controller can have
the following infrastructure related states:

- PENDING
- CONNECTING
- CREATING
- RECONCILING
- DELETING
- FAILING_RECONCILIATION
- FAILED

.. note::

    Refer to the :ref:`dev/kubernetes-cluster-observer:States` for the observer related cluster states.

``PENDING``
    This state is initially set when a Kubernetes cluster resource is created in Krake.

``CONNECTING``
    It is set when the actual Kubernetes cluster has been successfully reconciled.

``CREATING``
    It is set when the actual Kubernetes cluster is going to be created.

``RECONCILING``
    It is set when the actual Kubernetes cluster is going to be updated.

``DELETING``
    It is set when the actual Kubernetes cluster is going to be deleted.

``FAILING_RECONCILIATION``
    It is set when the reconciliation process of the actual Kubernetes cluster failed.

``FAILED``
    It is set on the global Infrastructure Controller level when an exceptions is raised during the reconciliation process.

.. note::

    Since this is a relatively new implementation, the Infrastructure Controller
    will certainly be extended by additional features and functionalities
    in the future, e.g. Infrastructure Observer.


.. _IM: https://github.com/grycap/im
.. _OpenStack: https://www.openstack.org/
