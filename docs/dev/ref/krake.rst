===============
Krake Reference
===============

This is the code reference for the Krake project.


Module hierarchy
-----------------

This section presents the modules and sub-modules of the Krake project present
in the ``krake/`` directory.

The tests for Krake are added in the ``krake/tests/`` directory. The
``pytest`` module is used to launch all unit tests.


krake
    The ``krake`` module itself only contains a few utility functions, as well
    as functions for reading and validating the environment variables and the
    configuration provided. However, this module contains several sub-modules
    presented in the following.

krake.api
    .. _krake.api:

    This module contains the logic needed to start the API as a an ``aiohttp``
    application. It exchanges objects with the various clients defined in
    krake.client_. These objects are the ones defined in krake.data_.

krake.client
    .. _krake.client:

    This module contains all the necessary logic for any kind of client to
    communicate with the API described in the krake.api_ module.

krake.controller
    This module contains the base controller and the definition for several
    controllers. Each one of these controllers is a separate process, that
    communicates with the API or the database. For this, the controllers use
    elements provided by the krake.client_ module.

    All new controller should be added in this module.

    krake.controller.kubernetes.application
        This sub-module contains the definition of the controller specialized
        for the Kubernetes application handling.

    krake.controller.kubernetes.cluster
        This sub-module contains the definition of the controller specialized
        for the Kubernetes cluster handling.

    krake.controller.scheduler
        This sub-module defines the Scheduler controller, responsible for binding
        the Krake applications and magnum clusters to the specific backends.

    krake.controller.gc
        This sub-module defines the Garbage Collector controller, responsible for
        handling the dependencies during the deletion of a resource. It marks as
        deleted all dependents of a resource marked as deleted, thus triggering their
        deletion.

    krake.controller.magnum
        This sub-module defines the Magnum controller, responsible for managing
        Magnum cluster resources and creating their respective Kubernetes cluster.

krake.data
    .. _krake.data:

    This module defines all elements used by the API and the controllers. It
    contains the definition of all these objects, and the logic to allow them
    to be serialized and deserialized.


----------------------------------------

Krake
-----

.. automodule:: krake
    :members:
    :show-inheritance:

API Server
----------

.. automodule:: krake.api
    :members:
    :show-inheritance:

.. automodule:: krake.api.app
    :members:
    :show-inheritance:

Authentication and Authorization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: krake.api.auth
    :members:
    :show-inheritance:

Database Abstraction
~~~~~~~~~~~~~~~~~~~~

.. automodule:: krake.api.database
    :members:
    :show-inheritance:

Helpers
~~~~~~~

.. automodule:: krake.api.helpers
    :members:
    :show-inheritance:

Middlewares
~~~~~~~~~~~

.. automodule:: krake.api.middlewares
    :members:
    :show-inheritance:

Client
------

.. automodule:: krake.client
    :members:
    :show-inheritance:

Client APIs
~~~~~~~~~~~

.. automodule:: krake.client.core
    :members:
    :show-inheritance:

.. automodule:: krake.client.infrastructure
    :members:
    :show-inheritance:

.. automodule:: krake.client.kubernetes
    :members:
    :show-inheritance:

.. automodule:: krake.client.openstack
    :members:
    :show-inheritance:

Controllers
-----------

.. automodule:: krake.controller
    :members:
    :show-inheritance:

Controller Kubernetes Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: krake.controller.kubernetes.application
    :members:
    :show-inheritance:

Controller Kubernetes Cluster
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: krake.controller.kubernetes.cluster
    :members:
    :show-inheritance:

Controller Scheduler
~~~~~~~~~~~~~~~~~~~~

.. automodule:: krake.controller.scheduler
    :members:
    :show-inheritance:

Controller Garbage Collector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: krake.controller.gc
    :members:
    :show-inheritance:

Controller Magnum
~~~~~~~~~~~~~~~~~

.. automodule:: krake.controller.magnum
    :members:
    :show-inheritance:

Data Abstraction
----------------

.. automodule:: krake.data
    :members:
    :show-inheritance:

.. automodule:: krake.data.serializable
    :members:
    :show-inheritance:

.. automodule:: krake.data.core
    :members:
    :show-inheritance:

.. automodule:: krake.data.infrastructure
    :members:
    :show-inheritance:

.. automodule:: krake.data.kubernetes
    :members:
    :show-inheritance:
