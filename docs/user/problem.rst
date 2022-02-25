==========================
HTTP Problem documentation
==========================

The failure reason on the Krake API HTTP layer is stored as RFC7807_ Problem.
It is a way how to define machine-readable and uniform details of errors in an HTTP response.

In case of failure on Krake API HTTP layer, the Krake API responses with well-formatted RFC7807_ Problem
message which could contain the following fields:

``type``
  A URI reference that identifies the problem type. It should point Krake API users to the
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

A authentication through keystone token failed.


invalid-keycloak-token
======================

A authentication through keycloak token failed.


resource-already-exists
=======================

A resource already in database is requested to be created.


.. _RFC7807: https://tools.ietf.org/html/rfc7807
