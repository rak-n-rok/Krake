=================
Design Principles
=================

This section contains a number of principles that should be followed when
extending Krake. The principles are very similar to the `Kubernetes design
principles`_.


API
===

See also :ref:`dev/concepts:API Conventions`.

- All APIs should be declarative.
- API resources should be *complementary* and *composable*, not opaque wrappers.

  .. note:: tip

      For example, a Kubernetes cluster could be created ontop of a managed
      OpenStack project.

- The control plane should be *transparent* -- there are no hidden internal
  APIs.
- Resource status must be *completly reconstructable by observation*. Any history
  kept (caching) must be just an optimization and not required for correct
  operation.
- Low-level APIs should be designed for control by higher-level systems.
- Higher-level APIs should be intent-oriented (think service level objectives)
  rather than implementation-oriented (think control knobs).


Control Logic
=============

- Functionality must be level-based, meaning the system must operate correctly
  given the desired state and the current/observed state, regardless of how
  many intermediate state updates may have been missed. Event/Edge-triggered
  behavior must be just an optimization.

  .. note::

      There should be a CAP_-like theorem regarding the trade-offs between
      driving control loops via polling or events about simultaneously
      achieving *high performance*, *reliability*, and *simplicity* -- pick
      any two.

- Assume an open world: continually verify assumptions and gracefully adapt to
  external events and/or actors.

  .. tip::

      For example, Krake allows users to kill Kubernetes resources under
      control of a Kubernetes application controller; the controller just
      replaces the killed resource.

- Do not define comprehensive state machines for objects with behaviors
  associated with state transitions and/or "assumed" states where these states
  or state transitions cannot be determined by observation.

- Do not assume a component's decisions will not be overridden or rejected, nor
  for the component to always understand why.

  .. tip::

      For example, etcd may reject writes. The scheduler may not be able to
      schedule applications. A Kubernetes cluster may reject requests.

- Retry, but back off and/or make alternative decisions.
- Components should be *self-healing*.

  .. tip::

      For example, if some state must be kept, e.g. cached, the content needs
      to be periodically refreshed, so that if an item does get incorrectly
      stored or a deletion event is missed, the kept state will be soon
      synchronized, ideally on timescales that are shorter than what will
      attract attention from humans.

- Component behavior should *degrade gracefully*. Actions should be prioritized
  such that the most important activities can continue to function even when
  overloaded and/or in states of partial failure.


Architecture
============

- Only the API server communicate with etcd/store, and no other components,
  e.g. scheduler, garbage collector, etc.
- Components should continue to do what they were last told in the absence of
  new instructions, e.g. due to network partition or component outage.
- All components should keep all relevant state in memory all the time. The
  API server write through to etcd/store, other components write
  through to the API server, and they watch for updates made by other
  clients.
- Watch is preferred over polling.


Extensibility
=============

- All components should be replaceable. This means there is no strong coupling
  between components.

  .. tip::

    For example, the different scheduler should be usable without any changes
    in another component.

- Krake is extended with new technologies/platforms by adding new APIs.


Availability
============

.. note::

    HA is about removing **single point of failure** (SPOF).

- High-availability (HA) is achieved by service replication.

.. todo::

    It needs to be decided on which level replication is introduced.

    Coarse grained
        Replicate "Krake master" with all included components, e.g. API server, controllers etc.

    Fine grained
        Replicate single components. If a component is stateful -- relevant
        state should be kept in memory as stated in section
        :ref:`dev/principles:Architecture` -- the components should follow an
        active-passive principle where only one replica of a component is
        active at the same time. A

        `etcd leases`_ may be a good option for this but only the API controller
        should have direct access to etcd. A solution for this would be to
        introduce special API endpoints for electing a leader across multiple
        replicas.


Development
===========

- Self-hosting of all components is the goal.
- Use standard tooling and defacto standards of the Python ecosystem.


.. _CAP: https://en.wikipedia.org/wiki/CAP_theorem
.. _Kubernetes design principles: https://github.com/kubernetes/community/blob/master/contributors/design-proposals/architecture/principles.md
.. _etcd leases: https://etcd.io/docs/v3.3.12/dev-guide/interacting_v3/#grant-leases
