==========
Scheduling
==========

.. todo::

    Right now, the scheduler does just select a random Kubernetes cluster for
    Kubernetes applications. It does not use any external metrics.

    The precise interactions between the scheduler and the metrics providers
    are currently work in progress.


Constraints
===========

This section describes the application constraints definition used in Krake scheduling algorithm.

The Krake scheduler filters appropriate clusters based on defined application constraints.
A Cluster can be accepted by scheduler as a potential destination for given application only if it matches
all defined application constraints.

.. note::

    The application constraints are defined in rok CLI i.e. Krake user is allowed to define the
    restrictions for scheduling algorithm of Krake.


Custom resources:
-----------------

- Krake allows the user to deploy an application made on the Custom Resources (CR).

  The user can define which CRs are available on his cluster. A CR is defined
  by the Custom Resource Definition (CRD) and Krake uses CRD name in format ``<plural>.<group>``
  as a marker.
  The supported CRD names are defined by ``-R`` or ``--custom-resource`` option in rok CLI.

  See also :ref:`user/rok-documentation:Rok documentation`.

  Example:

  .. code:: bash

    rok kube cluster create <kubeconfig> --custom-resource <plural>.<group>

  The applications made on the CR has to be explicitly labeled by ``cluster resource constraint``.
  This explicit label is used in Krake decision algorithm to select an appropriate
  cluster where the CR is supported. A Cluster resource constraints are defined by CRD name
  in format ``<plural>.<group>`` using ``-R`` or ``--cluster-resource-constraint`` option in rok CLI.

  See also :ref:`user/rok-documentation:Rok documentation`.

  Example:

  .. code:: bash

    rok kube app create <application_name> -f <path_to_manifest> --cluster-resource-constraint <plural>.<group>
