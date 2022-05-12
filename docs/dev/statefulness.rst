=================
Statefulness
=================

Statefulness is a *property* of an application, if it creates, uses, controls and / or manages
some persistent data. We also talk about a *stateful application* in this context.

  .. note::

      This feature is still under development in Krake, so new features could
      be added or removed in the future. Also, some implementation details might
      change.

      Therefore, this page is subject to changes until this note is removed.

Krake enables statefulness with its shutdown hook :ref:`dev/hooks:Shutdown`, a full
explanation for this mechanism can be found in the linked chapter.
This hook enables Krake to safely shutdown an application for migration or complete deletion.
The following picture shows the overall mechanism.

.. figure:: /img/shutdown_hook.png

    Shutdown hook workflow in Krake

It is important to note, that the shutdown hook itself does NOT save the data or even
stops the application. If the hook is active for a specific application, Krake only calls
a *micro-service* through a network call. This service preferably sits in the same
container as the stateful application; its only task is to stop the corresponding application,
if it receives the command, and then report back, if the application really stopped.
You can view this *micro-service* as the extended arm of Krake.
But this service also doesn't ensure that the data of an application is saved before a
shutdown, since it only initiates the graceful shutdown.
The actual application needs to handle its data integrity and storage itself during the
shutdown process.

External storage
================

At the moment, Krake implements statefulness through external storage solutions like buckets
(e.g. Amazon S3, Minio) or other network accessible options.
This is only a very simple form of statefulness, which would require a user to also
have access to external storage or setup some solution himself.

The following figure demonstrates this principle.

.. figure:: /img/shutdown_hook__external_storage.png

    Shutdown hook workflow with an external persistent storage

This solution requires no mechanism for transferring storage by Krake itself, since the
storage isn't managed by Krake; the storage solution basically acts as a static backend.
