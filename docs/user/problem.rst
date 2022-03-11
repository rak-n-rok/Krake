==========================
HTTP Problem documentation
==========================

The failure reason of the Krake API HTTP layer is stored as an RFC7807_ Problem.
It is a way to define uniform, machine-readable details of errors in an HTTP response.

In case of a failure on the Krake API HTTP layer, the Krake API responds with a well-formatted RFC7807_ Problem
message, which could contain the following fields:

``type``
  A URI reference that identifies the problem type. It should point the Krake API users to the
  concrete part of the Krake documentation where the problem type is explained in detail.
  Defaults to about:blank.
``title``
  A short, human-readable summary of the problem type
``status``
  The HTTP status code
``detail``
  A human-readable explanation of the problem
``instance``
  A URI reference that identifies the specific occurrence of the problem

When RFC7807_ Problem ``type`` is defined, it points Krake API clients to the below
list of better-described HTTP problems.

.. note::
  The RFC7807_ Problem ``type`` URI is generated based
  on ``--docs-problem-base-url`` API configuration parameter (see :ref:`user/configuration:Krake configuration`)
  and the value from the list of defined HTTP Problems, see :class:`krake.api.helpers.HttpProblemTitle`.

not-found-error
===============

A requested resource cannot be found in the database.


transaction-error
=================

A database transaction failed.


update-error
============

A update of resource field.


invalid-keystone-token
======================

An authentication attempt with a keystone token failed.


invalid-keycloak-token
======================

An authentication attempt with a keycloak token failed.


resource-already-exists
=======================

A resource already defined in the database is requested to be created.


.. _RFC7807: https://tools.ietf.org/html/rfc7807
