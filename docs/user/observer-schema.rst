======================
Custom Observer Schema
======================

Purpose
=======

When a user creates Kubernetes resources on a Kubernetes cluster via Krake, those
resources are managed by Krake and should be "observed". That's the role of the
Kubernetes Observer (see the :ref:`dev/observers:Observers` documentation). But what
parts of the Kubernetes resources should be "observed" by Krake? The purpose of the
Observer Schema is to provide a flexible mean for the Krake users to define which fields
of the Kubernetes resources should be "observed" and which shouldn't.

When a field is "observed", every change to the value of this field made outside of
Krake is reverted to the last known state of this field. When a field is not "observed",
Krake doesn't act on external changes made to this field. This is needed to keep a
consistent and predictable application state, especially since changes could also be
done in the Kubernetes infrastructure or by the Kubernetes plane itself.


.. note::

  The custom observer schema could be used even when the application is described by a TOSCA template or CSAR archive.
  Both file types are translated to Kubernetes manifests in Krake's Kubernetes application controller,
  hence the custom observer schema file will be applied to the Kubernetes resources just like it happens during a "regular" 
  workflow, when a Kubernetes manifest is used, see :ref:`dev/tosca:TOSCA Workflow`.


.. note::

  As Kubernetes manages some fields of a Kubernetes resource (for instance the
  ResourceVersion), simply observing the entirety of a Kubernetes resource is not
  possible. This would lead to infinite reconciliation loops between
  Krake and Kubernetes, which is not a desirable state.

Format
======

Example
-------

This basic example will be re-used at different part of this documentation.

Example of manifest file provided by the user:

.. code:: yaml

    ---
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: echo-demo
      namespace: secondary
    spec:
      selector:
        matchLabels:
          app: echo
      template:
        metadata:
          labels:
            app: echo
        spec:
          containers:
          - name: echo
            image: k8s.gcr.io/echoserver:1.10
            ports:
            - containerPort: 8080
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: echo-demo
      namespace: secondary
    spec:
      type: NodePort
      selector:
        app: echo
      ports:
      - port: 8080
        protocol: TCP
        targetPort: 8080


Example of custom observer schema provided by the user.

.. code:: yaml

    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: echo-demo
      namespace: default
    spec:
      selector:
        app: null
      ports:
      - port: null
        protocol: null
        targetPort: null
      - port: null
        protocol: null
        targetPort: null
      - observer_schema_list_min_length: 1
        observer_schema_list_max_length: 4
      sessionAffinity: null

Default observer schema
-----------------------

By default, all fields defined in ``spec.manifest`` are observed. All other fields are
not observed. By defining a custom observer schema, the user is able to overwrite the
default behavior and precisely define the observed fields.

In the example above, the user didn't specify a custom observer schema file for the
``Deployment`` resource. Therefore Krake will generate a default observer schema, and
observe only the fields which are specified in the manifest file.

The result default observer schema for the ``Deployment`` resource is:

.. code:: yaml

    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: echo-demo
      namespace: secondary
    spec:
      selector:
        matchLabels:
          app: null
      template:
        metadata:
          labels:
            app: null
        spec:
          containers:
          - name: null
            image: null
            ports:
            - containerPort: null
            - observer_schema_list_min_length: 1
              observer_schema_list_max_length: 1
          - observer_schema_list_min_length: 1
            observer_schema_list_max_length: 1


Resource identification
-----------------------

In order to identify which resource a schema is referring to, the ``apiVersion``,
``kind`` and ``name`` need to be specified. Those fields are also the minimum fields a
user can specify in order to observe a resource. As a result, and without additional
fields to observe, the Kubernetes Observer will simply check the presence of a
Kubernetes resource with this ``apiVersion``, ``kind`` and ``name``.

Example of a minimal observer schema for the ``Service`` resource:

.. code:: yaml

    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: echo-demo


.. note::

    The Kubernetes namespace key ``metadata.namespace`` is not mandatory, as it is not
    used in the identification of a resource in Krake. Indeed, its value is not always
    known at the creation of the application. It can depend from the Kubernetes cluster
    the application is scheduled to.

    Please note that not all Kubernetes objects are in a namespace. Most Kubernetes
    resources (e.g. pods, services, replication controllers, and others) are in some
    namespaces. However, namespace resources are not themselves in a namespace.
    And low-level resources, such as nodes and persistentVolumes, are not in any
    namespace.

    Therefore, Krake (by default) does not observe a Kubernetes namespace field.

    Users may choose to add the ``metadata.namespace`` key to their custom observer schema,
    then the ``metadata.namespace`` field will be observed.


Observed fields
---------------

A field value will be observed if it is defined in the observer schema. Its value should
be ``null`` (in YAML), except for fields used for the resource identification.

In the example above:

- the ``spec.type`` of the Service is not observed, as it is not present in the custom
  observer schema. Its original value is specified in the manifest file, but Krake
  doesn't guarantee this value to remain.
- the ``spec.selector.app`` of the ``Service`` is observed as it is present in the
  custom observer schema. Krake guarantee that its original value will remain the same, by
  observing the value and reverting any changes which were not made through Krake.
- the ``spec.sessionAffinity`` of the ``Service`` is observed. As it is not present in
  the manifest, the Kubernetes API will initialize it. Once it has been initialized by
  Kubernetes, Krake guarantee that its value will not be modified outside of Krake.


.. warning::

    A non-observed field cannot be updated by Krake. In order to update such a field,
    one also need to observe it (i.e. update the custom observer schema to add this
    field).


.. note::

    Except for the fields used for identifying the Kubernetes resource, all fields value
    MUST be ``null``. Otherwise, the custom observer schema is invalid.


List length control
-------------------

A list's length is controlled though the used of a special control dictionary, added as
the last element of a list. The minimum and maximum length of the list must be
specified.

In the example ``Service``'s custom observer schema, the number of ``ports`` must be
between 1 and 4. If the length of the ``ports`` list is below 1 or above 4, Krake
reverts the ``Service`` to its last known value.

For the first port, the value of ``port``, ``protocol``, ``targetPort`` are defined in
the manifest file.

The presence of a second element in the ``ports`` list in the custom observer schema
doesn't guarantee its presence. Krake guarantee that, if a second port is set, its value
won't be allowed to change outside of Krake. It can be removed and re-added, as long as
its value remains unchanged.

.. tip::

    Krake doesn't allow to set a minimum list length value below the number of element
    specified in the manifest file.

.. tip::

    An unlimited list length can be specified by setting
    ``observer_schema_list_max_length`` to 0.

.. note::

    A list MUST contain the special control dictionary. Otherwise, the custom observer
    schema is invalid.


Usage
=====

A custom observer schema can be specified in ``rok`` with the argument ``-O`` or
``--observer_schema``. If none is provided, a default observer schema is generated and
all fields defined in ``spec.manifest`` are observed
