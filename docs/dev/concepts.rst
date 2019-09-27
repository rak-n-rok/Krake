========
Concepts
========

Krake is heavily inspired by the concepts of Kubernetes. If you are familiar
with the internal mechanisms of Kubernetes you should find many similarities
within Krake.


Overview
========

The central service of Krake is a RESTful HTTP API. The API is structured in
groups of APIs covering different technologies, e.g. ``core`` for the core
functionalities or ``kubernetes`` for Kubernetes-specific features. Each API
comprises multiple kinds of resources, e.g. the ``kubernetes`` API contains
*Application* or *Cluster* resources. The resources are used to describe the
*desired state*. The user can update the desired state by updating the
resource via simple PUT requests to the API.

In concept, every resource is handled by a *Controller*. The responsibility of
a controller is to bring the described *desired state* of a resource in sync
with the real world state. Some of the resources act as mere data bags, e.g.
*kubernetes/Cluster* resources simply describe how to connect to an existing
Kubernetes cluster. These resources do not have a corresponding controller
because no logic is needed for syncing desired and real world state.


API Conventions
===============

Krake uses abstractions for real world resources managed by Krake, e.g.
Kubernetes clusters spawned on top of an OpenStack deployment. These
abstractions are represented as API resources encoded  as nested JSON objects.

--------
Metadata
--------

Every resource *MUST* have the following metadata in a nested field called
``metadata`` with the following structure:

namespace
    A namespace is used to isolate access resources. Normally, a user does only
    get access to a specific namespace. See
    :ref:`dev/concepts:Authentication and Authorization` for more details. This
    field is immutable which means a resource cannot be migrated to another
    namespace.

name
    A string uniquely identifying a resource in its namespace. This name is
    used in URLs when operating on an individual resource. This field is
    immutable.

uid
    A unique string in time and space used to distinguish between objects of the
    same name that have been deleted and recreated. This field is immutable.

finalizers
    A list of strings that can be added by controllers to block the deletion
    of the resource in order to do some clean up work (finalizing). A resource
    *MUST* not be deleted if there is at least one finalizer.

    Controllers *SHOULD* process only finalizers that were added by them and
    that are at the tail of the list. This ensures a strict finalizing order.

created
    The timestamp when the resource was created. This field is immutable.

modified
    The timestamp when the ``spec`` field of the resource was changed.

deleted
    The timestamp when the resource was deleted. If this field is set, the
    resource is in the *in deletion* state. This transition is irreversible.
    In this state, no changes to the resource are allowed except removing
    items from ``finalizers`` and updating the ``status``. If ``finalizers``
    is empty and the resource is *in deletion* it will be removed from the
    database. See :ref:`dev/garbage-collection:Garbage Collection` for more
    details.


---------------
Spec and Status
---------------

By convention, the Krake API distinguishes between *desired state* of a
resource -- a nested field called ``spec`` -- and its *real world state* -- a
nested field called ``status``.

Every resource representing a real world object managed by Krake *SHOULD* have
a field called ``spec``. If the state of the represented object cannot change,
the resource *MAY* have a ``spec`` field only which *MAY* be renamed to a more
appropriate name.


----
etcd
----

Internally, the Krake API uses etcd_ -- a distributed and reliable key-value
store -- as persistence layer. But this is considered an implementation detail
and no etcd-specific mechanisms are exposed via the REST API. This means that
the underlying database could be potentially replaced in the future if the
requirements of the project change. The "killer" feature of etcd is the
watching of keys and prefixes for changes.

.. note::

    The distributed nature of etcd and its built-in support for observing
    changes for specific keys were the main motivation why Krake switched from
    a SQL-based persistence layer to etcd.


Control Plane
=============

The API does not implement control logic. The task of reconciling between
*desired state* and *real world state* is done by so-called controllers.
Controllers are independent services watching API resources and reacting on
changes. The set of all controllers forms the *Control Plane* of Krake.

Controllers communicate with the API server: the desired state is fetched from
the API and status updates are pushed to the API. In theory, controllers can
be programmed with any technology (programming language) capable of
communicating with a REST HTTP interface.

.. note::

    The first system architecture of Krake was event-based using message
    queuing (RabbitMQ). The main issue with event-driven systems is that the
    they get out-of-sync if a message gets lost. Hence, a lot of effort is
    involved to make sure that no message loss occurs.

    On the other hand, level-based logic operates given a desired state and
    the current observed state. The functionality is resilient against loss of
    intermediate state updates. Hence, a component can recover easily from
    crashes and outages, which makes the overall system more robust. This was
    the motivation for moving from an event-based system with message queuing
    to a level-based system with reconciliation.


Authentication and Authorization
================================

Access to the API is provided through a two-phased process.

Authentication
    Each request to the Krake API is authenticated. Authentication verifies
    the identity of the user. There are multiple authentication providers and
    the API can be extended by further authentication mechanisms. If no
    identity is provided, the request is considered to be *anonymous*. For
    internal communication between controllers and API, TLS certificates
    *SHOULD* be used.

Authorization
    After the identity of a user is verified, it needs to be decided if the
    user has permission to access a resource.

    Krake implements a simple but powerful role-based access control (RBAC)
    model. The ``core`` API provides ``Role`` resources describing access to
    specific operations on specific resources potentially in specific
    namespaces. A user is assigned to a role by another ``core`` resource
    called ``RoleBinding``.

    Roles in Krake are **permissive** only. There is no way to deny access to
    a resource through a role. At least one role a user is bound to needs to
    allow access to the requested resource and operation. Otherwise access is
    denied.

.. _etcd: https://etcd.io/
