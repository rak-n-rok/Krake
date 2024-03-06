===========
Controllers
===========

This part of the documentation presents the current implementation of controllers.

Overview
========

The controller architecture's design goal allows a number of possibilities:

      - The worker objects or functions can be given access to the queues, which is for the moment not the case

      - If the need arise, a new Controller could be created to manage several kind of resources

      - Or a Controller could handle the same kind of resource in two different ways depending on the state, hence having two queues and two kind of workers for the same reflector

      - It allows a developer to create any kind of Controller the way he/she wants

The control flow is very strict which makes modifications and augmentations hard, e.g. introducing more than one queue.

Building Blocks
===============

The building blocks of controllers are:

  - Reflectors
  Instead of watching resources directly from a method of the controller, "reflector" objects should be used.
  Reflectors objects responsible for -- as the name suggests -- reflect on API resource: listing and watching resources, dealing with reconnects etc.
  This decouples the list-and-watch logic from the controller logic.

  - Queues
  Controllers should have complete freedom of how they organize their work. This means that queues are not necessary, or several can be used on one Controller.

  - Workers
  Queues are consumed by workers. There should be no restriction of how a worker is implemented. Most of the time, methods of the controller could be leveraged as queue workers.

  - Observer
  Observers can be added to the Controller to, as the name suggests, observe the status of the real world resources.
  When the real status is different from the status stored in the API, they should send an update to the API to request a change.
  Another possibility could be to add an updated resource to the WorkQueue.
  These Observers would be regularly polling the real world resources to get their current state.
  The Observers can be considered as a first step towards the implementation of self-healing in Krake.


General Architecture
--------------------

.. figure:: /img/controller.png

This diagram present one possible architecture.

The Controller holds two Reflectors et can handle two different types of Resource. Each Resource has one or several WorkQueue.
The implementation of the Reflector decides in which queue a resource is added.

For the resource A, two different types of Workers are used for the same Queue, while the Resource B uses two Queue, each with a specific Worker.

Each resource is then observed by a specific Observer, which triggers an update of a resource that has been modified in the real world.


Simpler Example
---------------

.. figure:: /img/controller_flow.png


Implementation
==============

Boilerplate
-----------

This architecture implies some more boilerplate if a specific architecture is wanted.

However, a base Controller will be added with simple components.
This one could be then used easily by inheriting it and changing the __init__ function.
Additionally, for both Reflector and Observer an interface/abstract class will be added.
The resulting architecture would be the one from the simpler example.

Lock
----

We take the case of a resource being updated by the API:

      1. The spec is different from the status. The Controller watches the update

      2. The Controller will update the real world status to match the spec

      3. The Controller requests an update to the API with the new status

Between steps 2 and 3, if the Observer sees the change in the real world status, it will not match the resource status.
In this case, the Observer will request an update of the resource.
This would force the resource to be reset to the previous state, and an infinite loop would be started.

To prevent this, the current idea is to use a lock between the Workers and the Observer.
When an update is run on a specific application, the Observer should not observe this application.
