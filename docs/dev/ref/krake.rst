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

krake.apidef
    .. _krake.apidef:

    This module contains the definitions of the resources accessible via the
    API. Operations to access these resources are defined there.

krake.client
    .. _krake.client:

    This module contains all the necessary logic for any kind of client to
    communicate with the API described in the krake.api_ module. All routes
    are automatically generated using the definitions of krake.apidef_.

krake.controller
    This module contains the base controller and the definition for several
    controllers. Each one of these controllers is a separate process, that
    communicates with the API or the database. For this, the controllers use
    elements provided by the krake.client_ module.

    All new controller should be added in this module.

    krake.controller.kubernetes
        This sub-module contains the definition of the controllers specialized
        for the Kubernetes clusters and applications handling.

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

API Generator
~~~~~~~~~~~~~

.. automodule:: krake.api.generator
    :members:
    :show-inheritance:

API Definitions
---------------

.. automodule:: krake.apidefs
    :members:
    :show-inheritance:

.. automodule:: krake.apidefs.definitions
    :members:
    :show-inheritance:

Client
------

.. automodule:: krake.client
    :members:
    :show-inheritance:

Client Generator
~~~~~~~~~~~~~~~~

.. automodule:: krake.client.generator
    :members:
    :show-inheritance:

Client APIs
~~~~~~~~~~~

.. automodule:: krake.client.core
    :members:
    :show-inheritance:

.. automodule:: krake.client.kubernetes
    :members:
    :show-inheritance:

Controllers
-----------

.. automodule:: krake.controller
    :members:
    :show-inheritance:

Data Abstration
---------------

.. automodule:: krake.data
    :members:
    :show-inheritance:

.. automodule:: krake.data.serializable
    :members:
    :show-inheritance:

.. automodule:: krake.data.core
    :members:
    :show-inheritance:

.. automodule:: krake.data.kubernetes
    :members:
    :show-inheritance:

