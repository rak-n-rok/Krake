.. _bootstrapping:

=============
Bootstrapping
=============

After Krake has been installed and runs, the database is still empty. To allow easy
insertion of resources during initialisation, a bootstrap script is present, namely:
``krake_bootstrap_db``. It is used along with YAML files in which the resources
are defined.

Requirements for bootstrapping:

 * Krake should be installed;
 * the database should be started.


Usage
=====

Workflow
--------

The script is given several files, each with one or several resource definitions.
These definitions should follow the structure of the data defined in ``krake.data``.
See :ref:`admin/bootstrapping:Structure`.

If the insertion of at least one resource fails, all previous insertions are rolled
back. This ensures that the database remains in a clean state in all cases.

The insertion will be rolled back in the following cases:

 * the structure of a resource was invalid and its deserialization failed;
 * a resource belongs to an API or a kind not supported by the bootstrapping script;
 * a resource is already present in the database. This can be overridden using the
   ``--force`` flag (see the force_ argument). In this case, a resource already present
   will be replaced in the database with the currently read definition. In case of
   rollback, the previous version of the resource will be put back in the database.


Command line
------------

The simplest command is to give one or several files as input, for example:

.. code:: bash

    $ krake_bootstrap_db file_1.yaml file_2.yaml


Other arguments can be used:

``--db-host`` (address):
    If the database is not present locally, the host or address can be specified
    explicitly. Default: ``localhost``.

``--db-port`` (integer):
    If the database is not present locally, the port can be specified explicitly.
    Default: ``2379``.

``--force``:
    .. _force:

    If set, when the script attempts to insert a resource that is already in the
    database, the resource will be replaced with its new definition. If not, an error
    occurs, and a rollback is performed.


Structure
=========

Only resources defined in ``krake.data`` that are augmented with the
``krake.data.persistent`` decorator should be inserted with the
``bootstrapping/bootstrap`` script.

Each file must have a YAML format, with each resource separated with the ``---``
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


.. danger::

  The structure of a resource added in the database is checked against the definition
  of this resource kind. This means that the attributes' name and kind are checked.
  However, the bootstrapping script does not ensure that the relationships between the
  resources are valid.

  For instance, the ``RoleBinding`` ``my-rolebinding`` refers to the ``Role``
  ``my-role``. If this role is not in the database, or its name has been misspelled,
  the bootstrapping script will not detect it, and the database will be inconsistent.


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

    $ krake_bootstrap_db bootstrapping/base_roles.yaml


Development and tests
---------------------

To test the migration, ``support/prometheus`` or ``support/prometheus-mock`` script can
be used, or simply static metrics. However, in this case, ``Metric`` and
``MetricsProvider`` objects need to be created. Two bootstrap definition files are
present in ``support/`` for adding Prometheus and static metrics and metrics provider,
respectively ``prometheus_metrics.yaml`` and ``static_metrics.yaml``.

They can be easily processed using:

.. code:: bash

    $ krake_bootstrap_db support/prometheus_metrics.yaml support/static_metrics.yaml
