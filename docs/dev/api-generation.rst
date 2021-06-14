==============
API Generation
==============

This part of the documentation describes the API generator utility.

Role
====

The API generator was developed to automatically create the code for:

- the Krake API;
- the client for the Krake API;
- the unit tests for the Krake API;
- the unit tests for the client of the Krake API;
- the API definitions, which are the bases for the generation of the elements above.

.. note::

    Other cases will be added, as the generator was built to be modular.

The Krake API is separated into the different APIs that are managed: ``core``,
``kubernetes`` and ``openstack``. Each one of them handles the classic CRUD operations
on the different resources managed by the APIs. Having all their code written by hand
would not really follow the DRY principle. Previously, the handlers and the client
methods were generated dynamically when starting the API. This lead to the code of the
API and the client being not very flexible, but mostly, being harder to debug.

As a compromise, the API generator was introduced. It generates the code for any
resource of any API in a deterministic way. The code for the API, the client and their
respective unit tests are thus more or less "harcoded", as they are not generated on the
fly. This has several advantages:

- the code can be easily read, understood, and is accessible easily for debuggers and
  linters;
- the generation can be nicely integrated with versioning. For instance, when generating
  new resources or when updating the template of the handlers, the changes can be
  propagated easily. One only needs to rerun the generator and check the differences.

The API generator should be leveraged in the following cases:

- a new operation on an existing resource is inserted (like the binding for the
  ``Application`` resource, or the update of a subresource);
- a new resource is added to an API. All operations to manage it should be handled;
- a whole new API is added. All resources should be managed as well;


Usage
=====

The API generator is a Python module not integrated into the Krake main code. It is
present in the Krake repository on ``api_generator/``.

The base command for the generator is the following:

.. prompt:: bash $ auto

    $ python -m api_generator <command> <parameters>

The ``<command>`` part sets the type of generator which will be used, e.g. the Krake API
code, or unit tests for the client. The ``<parameters>`` are the specific arguments for
the chosen generator.


.. warning::

    Krake needs to be installed on your local environment to be able to use the
    generator.

.. warning::

    You need to be in the Krake root directory to use the command.

The command above will display the generated result. To store it into a file, simply
redirect the result:

.. prompt:: bash $ auto

    $ python -m api_generator <command> <parameters> > <generated_file>



Templating
==========

The generated content is based on Jinja templates stored in ``api_generator/templates``,
but the path can be overwritten, see :ref:`dev/api-generation:Common arguments`.
Modifying the templates will modify the generated code, and additional templates can be
added for additional operations, unit tests, handlers, etc.


Generated elements
==================

API definitions
---------------

The API definitions describe the different operations which can be executed on a type of
resource in a specific API. For instance, it would express that the resource ``Bar`` of
API ``foo`` can be read or listed, but not created, updated or deleted. Additional
operations can also be added, for example for bindings, hooks, etc.

To create these definitions automatically, the generation is based on classes defined in
the Krake data module. The module inside ``krake.data`` is imported by the generator,
which goes through the module, and filters the classes which will be persistently stored
in the database. These classes are considered as being handled by the Krake API, and the
operations will only be generated for them.

For each resource (the class handled), the following elements are generated:

- a ``Resource`` class;
- the singular and plural word for the resource;
- the scope of the resource (namespaced or not);
- basic CRUD operations, plus ``List`` and ``ListAll`` (from all namespaces);
- subresource classes inside the ``Resource`` class for each subresource of the data
  class (specified by the ``"subresource"`` metadata of a field being set to ``True``.);
- for each subresource, the ``Update`` operation is generated.

For each operation, the generated definition also describes:

- the HTTP method for the operation;
- the URL path for the operation's endpoint;
- the name of the data class to use for the body of the request to the endpoint;
- the name of the data class that will be used for the body of the response of the Krake
  API.


For example:

.. prompt:: bash $ auto

    $ python -m api_generator api_definition krake.data.kubernetes

will generate an API definition file which describes all the resources in the
``kubernetes`` API of Krake. Among many other elements, a ``Status`` subresource is
added for he ``Application`` resource.

Regarding the scope, each resource can be either namespaced or non-namespaced.
To handle non-namespaced resources, no namespaced should be provided for the API
endpoint when calling them. Further, the ``List`` operation can list all of the elements
of the resource, and there is no ``ListAll`` operation to list all resources of all
namespaces (because the instance of the resources are not separated by namespaces).

To specify the scope, use the ``--scopes <krake_class_name>=<scope>`` argument, once for
each resource. For example, for the ``foo`` API, with resource ``Bar`` namespaced and
``Baz`` non-namespaced, the command should be:

.. prompt:: bash $ auto

    $ python -m api_generator api_definition krake.data.foo --scopes Baz=NONE


After the generation, operations or the attributes of the operation can be changed to
restrict or add new operations, change the body of the request or the response, add
other subresources, etc.

The existing definitions are stored in the ``api_generator/apidefs`` directory.


API/client code generation and their unit tests
-----------------------------------------------

The generation for the following elements all follow the same procedure:

- code for the Krake API;
- code for the client of the Krake API;
- the unit tests for the Krake API;
- the unit tests for the client of the Krake API.

The four generators leverage the :ref:`dev/api-generation:API definitions` as input. By
giving the generator the path to a definition, it will be able to import it and get
information from the resources, subresources and their respective operations. This will,
in turn, be leveraged for the generation of the code.

.. prompt:: bash $ auto

    $ python -m api_generator <command> api_generator.apidefs.foo

where the parameter (here ``api_generator.apidefs.foo``) is the module path to the API
definition used as input, and ``<command>`` can be:


``api_client``:

    The generated output will be code to communicate with the API. For each API, a
    client class is created, which has a method for each defined operation. These
    methods take usually a resource as parameter and maybe the name and namespace of a
    resource. It returns usually the body of the response of the Krake API.

``api_server``:

    The generated output will be handlers for the Krake API, to be executed when a
    request is received. For each operation of each resource, a handler is generated to
    process the request and prepare the body of the response sent to the client.

``test_client``:

    The generated output will be unit tests. They verify the behavior of the client
    methods generated by the ``api_client`` command. For each method of the client,
    several unit tests can be added because of the different behaviors it can have.

``test_server``:

    The generated output will be unit tests. They verify the behavior of the handlers
    generated by the ``api_server`` command. For each handlers of the API, several unit
    tests can be added because of the different behaviors it can have.


All these generators share the following common arguments:

- ``--operation``
- ``--resources``

They can be used to limit respectively the operations and/or the resource that will be
handled by the generator for the final output. Can be repeated once for each operation
for which the output will be displayed. If one of the option is used, it will only
display the mentioned operation or resource. Not using one of them will result in all
operations or resources being outputted.


Common arguments
----------------

These arguments are common to some generators:

``--no-black``:

    to disable the usage of black_ on the output of the generator before returning it.

``--templates-dir``

    to overwrite the templates used for the generation of the code or definitions.


.. _black: https://github.com/psf/black
