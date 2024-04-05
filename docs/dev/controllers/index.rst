=================
Krake Controllers
=================

This chapter provides an overview of the Krake controllers
(see also :doc:`../architecture`)
as well as documentation of the general architecture and work flow of a Krake controller
along with individual documentation of each controller variant.

To date Krake consists of the following controllers:

* :doc:`Infrastructure controller <./infrastructure-controller/infrastructure-controller>`

  Controls the harbor infrastructure layer of Kubernetes clusters
  that were created by Krake through an infrastructure provider
  and thus are fully managed by Krake.

* :doc:`Kubernetes cluster controller <./kubernetes-cluster-controller/kubernetes-cluster-controller>`

  Controls the Kubernetes layer of clusters registered in Krake.

* :doc:`Kubernetes application controller <./kubernetes-application-controller/kubernetes-application-controller>`

  Controls the Kubernetes applications registered in Krake.

As you can see Krake controllers roughly map to a logic layer.

.. toctree::
    :caption: Table of Contents
    :maxdepth: 3

    index
    infrastructure-controller/infrastructure-controller
    kubernetes-cluster-controller/kubernetes-cluster-controller
    kubernetes-application-controller/kubernetes-application-controller


General architecture
====================

Krake's controller architecture follows the producer consumer pattern
around a queue as decoupling element.
Both producers and consumers are run as worker tasks of the controller.
The queue is filled by a so called reflector.
This component watches Krake API resources of a specific type, e.g. application, cluster
and puts resources with new state into the controller's worker queue for processing.
Resource items in the queue are then consumed
by (one but usually) multiple instances of the controller's resource handler.
The resource handler is in charge of performing the controller specific actions
on the real world counterpart of a resource.
In general there are two distinct actions:

a) ensuring monitoring of the real world resources
   and pushing the actual resource state into the Krake API
b) adjusting the real world resources to match their desired state in the API

Finally, to produce the executable application
the controller is encapsulated into an executor object
which takes care of all the surrounding logic,
such as managing the execution process
and handling UNIX signals.


Executor
--------

Component used to encapsulate the controller.
It takes care of starting and stopping the controller in an async event loop,
and handles all logic not directly dependent on the controller,
such as reacting to UNIX signals.

The :class:`Executor` class implements the asynchronous context manager protocol.
Upon entering the execution context
the executor attaches its signal handlers to the execution event loop
and creates an event loop task from the controller's :meth:`Controller.run` method.
Awaiting the executor context then starts the async controller task
and blocks until the controller terminates (which should not happen normally).
When stop has been signaled (``SIGINT``, ``SIGTERM``) or the execution context is left
the controller task is canceled.


Controller
----------

Component that controls a core logic layer of Krake.
The currently implemented controllers all manage a single resource type.

From the introductory part of this section
you could already get an idea of the basic architecture of a controller.
From this basis we will now go through the general controller flow.

1. Controller initialization
````````````````````````````
:class:`Controller` objects are initialized before being passed to an executor.
During initialization the following attributes are set:

* the event loop (:attr:`Controller.loop`)
* the :class:`WorkQueue` work queue (:attr:`Controller.queue`)
* the worker task registry (:attr:`Controller.tasks`)
* the Krake API endpoint (:attr:`Controller.api_endpoint`)
* run control (:attr:`Controller.max_retry`, :attr:`Controller.burst_time`)

... and a few more.

.. _dev-controllers-controller-controller-prep:

2. Controller preparation
`````````````````````````
When a controller starts up after its :meth:`Controller.run` method has been called
(this is normally done by the encapsulating executor)
it performs the controller type specific preparation steps
by calling the :meth:`Controller.prepare` method.
In order to setup communication with the Krake API a base client is created
and passed to the preparation method.

The following preparation steps are performed by all controller types:

* Derive the required Krake API clients, e.g. Krake Kubernetes API client, Krake Infrastructure API client

* Create and register a given amount of resource handler tasks.

  All tasks are instances of the :meth:`Controller.handle_resource` method.
  See :ref:`dev-controllers-arch-resource-handler`
  on how a resource handler component works.

* Create and register a single reflector task.

  The task is an instance of the :class:`Reflector` class.
  See :ref:`dev-controllers-arch-reflector`.
  on how the reflector component works.

  The reflector object is usually stored in a controller attribute,
  e.g. ``cluster_reflector``, ``application_reflector``
  and is supplied with a the following callables...

  * to list all resources (of one type) in the Krake API
    in order to receive all resources once on startup.

    The ``Reflector.listing`` callable must be a Krake API client method.

  * to continously watch all resources (of one type) in the Krake API
    in order to receive resource changes after the initial listing.

    The ``Reflector.watching`` callable must be a Krake API client method.

  * to handle the following resource event types: list, add, update, delete
    Event handlers must be controller methods.

    Event handlers should first check
    whether the received resource is to be accepted or rejected/ignored
    (e.g. only accept clusters that are accessible)
    before putting it into the controller's work queue.

    Usually the same event handler is used for all event types but 'list'.
    This event handler should additionally register an observer for the resource
    to ensure that all resources (of one type) in the Krake API are updated
    with data from their real world counter parts.
    See :ref:`dev-controllers-arch-observer`
    on how the observer component works.

3. Controller run
``````
After finishing the preparation
the :meth:`Controller.run` method proceeds with opening a session with the Krake API
and running all tasks that were registered during controller preparation.
These tasks ultimately make up the controller.

Tasks are restarted if they don't fail too regularly.
:class:`BurstWindow` is used to make this decision.


.. _dev-controllers-arch-work-queue:

Work queue
----------

Component to decouple the reception of items from processing them.

The work queue stores arbitary key-value pairs
and guarantees strictly sequential processing of each queue key
meaning a key-value pair retrieved from the queue (via :meth:`get`)
cannot be retrieved again until the corresponding key is marked as done (via :meth:`done`)
even if a new key-value pair with the corresponding key was put into the queue (via :meth:`put`)
during the time of processing.


.. _dev-controllers-arch-reflector:

Reflector
---------

Component to connect to the Krake API and fetch resources.

A reflector is executed as a controller worker.
When run (by direct call of the object)
it calls its :meth:`Reflector.list_and_watch` method
to perform listing and watching concurrently.
The listing (with :attr:`Reflector.list_resource`) will return
once it called the :attr:`Reflector.on_list` event handler
for every resource received from the API using :attr:`Reflector.client_list`,
while the watching (with :attr:`Reflector.watch_resource`) will continue
to call the correct resource event handler
(:attr:`Reflector.on_add`, :attr:`Reflector.on_update` and :attr:`Reflector.on_delete`)
on every resource event emitted by the API watcher :attr:`Reflector.client_watch`.

If the API connection fails a delayed retry is attempted.
The delay is dynamically increased and reset
based on the connection failure frequency.


.. _dev-controllers-arch-observer:

Observer
--------

Component to watch the real world counter part of a single resource
and observe changes.

An observer is executed as a controller worker and always attached to a single resource.

Observers are created and hooked up to a controller specific event handler
that is to be called on real world resource changes.
Every resource-observer pair is registered in the controller's observer registry
(:attr:`Controller.observers`).

Observers are specific to a resource type.
Currently the following variants exist:

* :doc:`KubernetesApplicationObserver <./kubernetes-application-controller/kubernetes-application-observer>`
* :doc:`KubernetesClusterObserver <./kubernetes-cluster-controller/kubernetes-cluster-observer>`
* :doc:`InfrastructureProviderClusterObserver <./infrastructure-controller/infrastructure-provider-cluster-observer>`

Observer registration
`````````````````````

Initially every resource received by the controller has an observer registered
(see :ref:`dev-controllers-controller-controller-prep`).
During resource handling observers may be reregistered,
temporarily removed (in certain resource states)
or permanently removed (when the resource is deleted).
(see :ref:`dev-controllers-arch-resource-handler`).

The function to actually perform the registration is
:func:`krake.controller.*.hooks.register_observer`.
It first selects the suitable observer class for the given resource,
then creates, registers and starts the observer finally running :meth:`Observer.run`.

While the initial observer registration on startup is usually done directly
it is mainly triggered through a hooking mechanism during resource handling.

Observer run
````````````

The infinite observer loop (started by :meth:`Observer.run`) is build from
a watcher that emits an updated resource object
whenever a real world resource change is observed,
and an updater that attempts to push the real world resource change into the Krake API.

Observer watcher
''''''''''''''''
The watcher (:meth:`Observer.observe_resource`) is implemented as async generator
which continously loops through
fetching specified data about the real world resource (aka. observation)
and checking whether it changed.
The check is done against the observer's internal mirror of the API resource.
If changes are determined an updated resource representation with the new data
is generated.
Fetching and checking is specific to the observer type.

Observer updater
''''''''''''''''
The updater (:meth:`Observer.update_resource`) calls
the :meth:`Observer.on_res_update` hook that was given to the observer.
This hook should then update the Krake API with the observed change.
On success the hook must return the resource representation now stored in the API
to sync up the observer internal mirror as well.
On failure the internal mirror is not updated
so that the update is retriggered with the next check.


.. _dev-controllers-arch-resource-handler:

Resource handler
----------------

Component to continously process resources from the controller's work queue.

Resource handlers are executed as controller workers.
In an infinite loop they
consume a resource from the queue
and hand it over to the right cascade of resource processors.
The queue behaves such that resources in the queue
are handled by one resource handler at a time
(see :ref:`dev-controllers-arch-work-queue`).
``done`` is signaled to the queue after the resource processing finishes.

Resource processors are specific to the controller type,
see the respective controller variant for details.
