=====================
Kubernetes Application Controller
=====================

Reconciliation loop
===================

In the following section, we describe what happens in the Kubernetes Application
controller when receiving a resource, and highlight the role of the observer
schema.

In this example, the user provides:

- Two resources (one ``Song`` and one ``Artist``) that should be created. This
  is provided in ``spec.manifest``.
- A custom observer schema for the ``Song``. This is provided in
  ``spec.observer_schema``

The first resource (``Song``) illustrates the use of a custom observer schema
and demonstrates the behavior of list length control. The second resource
(``Artist``) highlights the generation of a default observer schema and the
special case of mangled resources.


.. figure:: /img/kubernetes_controller_reconciliation_example.png


Step 0 (Optional)
------

If the resource is defined by the TOSCA template file or URL or by CSAR
archive URL, the controller translates the given TOSCA or CSAR to the Kubernetes manifest
file if possible, see :ref:`dev/tosca:TOSCA`.

The result of translation is stored in ``spec.manifest``.

This step is performed by the ``ApplicationToscaTranslation`` hook.


Step 1
------

First, the controller generates the default observer schema for resources,
where none have been provided. In our example, a default observer schema is
created for the ``Artist``, while the custom observer schema provided by the
user for the ``Song`` is used as-is.

The result is stored in ``status.mangled_observer_schema``.

This step is performed by the ``generate_default_observer_schema`` function.

Step 2
------

In this step, the controller initializes - or updates if previously
initialized - the ``status.last_applied_manifest``. This attribute represents
the **desired** state (i.e. which values should be set for which fields).

If empty (i.e. during the first reconciliation of the resource), it is
initialized as a copy of ``spec.manifest``. The
``status.last_applied_manifest`` might be augmented at a later step by
non-initialized observed fields (see Step 6). As a result, if this field has
already been initialized (i.e. during later reconciliation), this step
updates the observed fields present in ``spec.manifest``.

This the role of the ``update_last_applied_manifest_from_spec`` function.

In the example above, looking at the ``Song`` resource:

- ``key1`` is initialized in ``spec.manifest`` and is observed.
- ``key2`` is initialized in ``spec.manifest`` but is not observed. Its
  initial value is copied to the ``status.last_applied_manifest``, so that
  the Kubernetes resource can be created using this value. But as it's not
  observed, its value in ``status.last_applied_manifest`` will never be
  updated (see Step 6).
- ``key3`` is observed but is not set in ``spec.manifest``. Its value in
  ``status.last_applied_manifest`` is initialized as part of the Step 6 (see
  below).

Step 3
------

When an application is mangled, for instance if the Complete Hook has been
enabled for the application, some fields or resources are added to
``status.last_applied_manifest``. They should also be observed, so there are
added to ``status.mangled_observer_schema``.

This steps is performed in the ``mangle_app`` method of the ``Complete`` class.

In the example above, the ``Artist`` resource is mangled. The key
``spec.nickname`` is added to both ``spec.last_applied_manifest`` and
``mangled_observer_schema``.

Step 4
------

The controller compares the **desired** state
(``status.last_applied_manifest``) and the **current** state (represented in
``status.last_observed_manifest``). It creates a set of ``new``, ``updated``
and ``deleted`` resource, to be used in the next step:
- ``new`` resources are present in the **desired** state but not in
  the **current** state; they need to be created on the cluster.
- ``updated`` resources have a different definition in the **desired** and in
  the **current** state; they need to be updated on the cluster.
- ``deleted`` resources are not in the **desired** state anymore, but are in
  the **current** state; they need to be deleted from the cluster.

During the first reconciliation of the application, the **current** state is
empty. All resources present in the **desired** state needs to be created.

This steps occurs in ``ResourceDelta.calculate()`` function.

.. note::

  In order to calculate the "diff" between the desired state and the current
  state of a resource, the controller:
  - compares the value of the observed fields only. By definition, the
    controller should not act if a non-observed fields value changes.
  - checks if the lengths of lists are valid using the list control
    dictionary.

Step 5
------

The controller acts on the result of the comparison by either creating,
patching, or deleting resources on the cluster. In particular:

- A resource is *created* using the whole ``status.last_applied_manifest``.
  This ensures that all initialized fields (set by the user in
  ``spec.manifest``), are set on the selected cluster, regardless of whether
  they are observed. In the example above, this is especially the case for
  ``key2`` in the ``Song``.
- Only the observed fields of a resource are used in order to *patch* that
  resource.

In other words, the non-observed initialized fields (i.e. set by the user in
``spec.manifest``, however not in ``spec.observer_schema``):
- are used for the creation of the resource.
- are not used for patching the resource.

This reflects the fact that if a non-observed fields value changes on the
Kubernetes cluster, this update should not be reverted by the Kubernetes Application
controller, while providing the user with the ability to set the initial
value of a non-observed field.

Step 6
------

Using the Kubernetes response, the ``status.last_applied_manifest`` is
updated. It is augmented with observed fields which value was not yet known.

In the example above, this is the case of ``key3`` in the ``Song``. It is
observed (present in ``spec.observer_schema``) but not initialized
(not present in ``spec.manifest``). Its value in
``status.last_applied_manifest`` couldn't be initialized during Step 2. Its
value is initialized using the Kubernetes response.

This mechanism provides the user with the ability to request a specific field
to remain constant, while not providing an initial value for it. It uses the
value set initially by the Kubernetes cluster on resource creation.

This task is performed by the hook ``update_last_applied_manifest_from_resp``.

.. note::

    Only the observed which are not yet known are added to
    ``status.last_applied_manifest``.

    In the unlikely event where a field, which value is already known, has a
    different value in the Kubernetes response (for instance if ``key1``
    would have a different value in the Kubernetes response), this value is
    *not* updated in ``status.last_applied_manifest``. The user's input
    prevails in the definition of the **desired** state, represented by
    ``status.last_applied_manifest``.

.. note::

    The ``rythms`` list possess two elements in the Kubernetes API response.
    As only the first element is observed, the value of the second element is
    not saved in ``status.last_applied_manifest``.

Step 7
------

Similarly, the ``status.last_observed_manifest`` also needs to be updated in
order to reflect the **current** state. It holds all observed fields which
are present in the Kubernetes response.

This task is performed by the hook
``update_last_observed_manifest_from_resp``.
