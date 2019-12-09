.. _bootstrapping:

=============
Bootstrapping
=============

After Krake has been installed and runs, the database is still empty. To allow easy
insertion of resources during initialisation, a bootstrap script is present, namely:
``bootstrapping/bootstrap``. It can be used along with YAML files in which the
resources are defined.

Example:

.. code:: bash

    $ bootstrapping/bootstrap file_1.yaml file_2.yaml


Structure
=========

Each file must have a YAML format, with each resources separated with the ``---``
separator. The API name, the resource kind and its name must be specified (in the
``metadata`` for the name).

Thus the minimal resource to add must have the following structure:

.. code:: yaml

    api: foo
    kind: Bar
    metadata:
      name: foo_bar

This will add a ``Bar`` object with the name ``foo_bar``, with ``Bar`` defined in the
API with name ``foo``.

An actual resource would have more values to fill, see the following example with a
Krake ``Role`` and ``RoleBinding`` definitions:

.. code:: yaml

    api: core
    kind: Role
    metadata:
      name: my-role
    rules:
    - api: 'my-api'
      namespaces:
      - 'my-namespace'
      resources:
      - 'my-resource'
      verbs:
      - list
      - get
    ---

    api: core
    kind: RoleBinding
    metadata:
      name: my-rolebinding
    roles:
    - my-role
    users:
      - me



Existing definitions
====================

Some files are already present in the Krake repository with the definitions of
different resources.


Authorization
-------------

To use the RBAC authorization mode, roles need to be defined, using ``Role`` objects.
They need to be present in the database, and can either be added manually, using the
API, or with the bootstrapping:

.. code:: bash

    $ bootstrapping/bootstrap bootstrapping/base_roles.yaml


Development and tests
---------------------

To test the migration, ``support/prometheus`` or ``support/prometheus-mock`` script can
be used, or simply static metrics. However, in this case, ``Metric`` and
``MetricsProvider`` objects need to be created. Two bootstrap definition files are
present in ``support/`` for adding Prometheus and static metrics and metrics provider,
respectively ``prometheus_metrics.yaml`` and ``static_metrics.yaml``.

They can be easily processed using:

.. code:: bash

    $ bootstrapping/bootstrap support/prometheus_metrics.yaml support/static_metrics.yaml
