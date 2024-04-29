Dependency Management
=====================

This page describes how Python dependencies are managed in the Krake
project.

Abstract vs. Concrete Python Requirements
-----------------------------------------

Throughout this document, we distinguish between two types of dependency
specifications:

-  **Abstract requirements** list only direct dependencies with the
   loosest version restriction possible. Transitive dependencies are not
   included (i.e., dependencies of dependencies). They are easy to
   manage manually. However, the decision which packages and versions
   actually get selected is postponed to the time of installation with
   ``pip``.
-  **Concrete requirements** list all dependencies, including transitive
   dependencies, and everything is *pinned* to a specific version. They
   allow us to *reproduce* the same Python environment over and over
   again, which is especially useful in the CI pipelines. Concrete
   dependencies are difficult to maintain manually, therefore we use
   ``pip-compile`` to derive them from abstract requirements.

Dependencies of ``krake``, ``rok`` and ``rak`` Packages
-------------------------------------------------------

The following files in the source tree are related to the dependencies
of the ``krake``, ``rok`` and ``rak`` packages:

::

   krake/
   ├── constraints.txt
   ├── requirements/
   │   ├── requirements-py311-test.txt
   │   ├── requirements-py311.txt
   │   ...
   │   ├── requirements-py38-test.txt
   │   └── requirements-py38.txt
   ├── krake/
   │   └── pyproject.toml
   ├── rak/
   │   └── pyproject.toml
   └── rok/
       └── pyproject.toml

Abstract Requirements (``pyproject.toml``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The abstract dependencies of the ``krake``, ``rok`` and ``rak`` packages
are listed, together with optional extras, in their respective
``pyproject.toml`` package metadata. When installed with pip (for
example as in ``pip install -e ./krake``), pip will take care of
resolving the dependencies and chose the latest possible versions.

Constraints (``constraints.txt``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The constraints file can be used to restrict the version of a transitive
dependency of ``krake`` and ``rok`` *without* making it a direct
dependency.

Concrete Requirements (``requirements/*.txt``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For reproducible testing and installations of the ``krake`` and ``rok``
combination, we have several sets of concrete requirements in the
``requirements/`` directory (two for each Python release that we
currently test in the CI):

-  ``requirements/requirements-pyXY.txt`` without the ``test`` extras
-  ``requirements/requirements-pyXY-test.txt`` with the ``test`` extras

These can be used to exactly recreate a Python environment in a fresh
virtualenv, for example an environment with Python 3.10 and ``test``
extras:

.. code:: shell

   python3.10 -m venv .venv && source .venv/bin/activate
   pip install --upgrade pip setuptools
   pip install --no-deps -r requirements/requirements-py310-test.txt
   pip install --no-deps -e './krake[test]' -e './rok[test]'
   pip check

.. note::

    The ``--no-deps`` switch ensures that no additional, unlisted
    dependencies can slip into the environment. Together with the final
    ``pip check`` this tests if the requirements file is complete.


Regenerating Concrete Requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you have modified the abstract dependencies in
``krake/pyproject.toml`` or ``rok/pyproject.toml``, you should
regenerate the pinned dependencies with

.. code:: shell

   tox run -m requirements

By default and intentionally, the current pinned versions are not
updated (“bumped”). This can be triggered by passing an extra argument:

.. code:: shell

   tox run -m requirements -- --upgrade

.. note::

   The above ``tox`` call requires the respective ``pythonX.Y``
   interpreters to be installed, for example from the `deadsnakes
   PPA`_ for Ubuntu or via pyenv_.

.. note::

   Distinct requirements files per Python release are necessary because
   the transitive dependencies will be different. For example, older
   Python releases often require some backported modules which can be
   incompatible with newer releases.


Dependencies for Tools Used in CI
---------------------------------

The following files in the source tree are related to the dependencies
of the Python tools we use for linting, code coverage and documentation
generation in the CI pipelines:

::

   krake/
   ├── docs/
   │   ├── requirements.in
   │   └── requirements.txt
   └── ci/
       ├── requirements_coverage.in
       ├── requirements_coverage.txt
       ├── requirements_lint.in
       └── requirements_lint.txt

The ``requirements*.in`` files contain the abstract requirements. For
each abstract requirement file there is only one concrete requirements
file (``requirements*.txt``). It is generated for the Python release
provided by the image which was configured for the CI job (we use
``python:3.10`` at the time of writing).

If any of the ``requirements*.in`` files were modified, the concrete
requirements can be regenerated with

.. code:: shell

   tox run -m tool-requirements

To bump the versions, use the additional ``--upgrade`` switch as
follows:

.. code:: shell

   tox run -m tool-requirements -- --upgrade

Current Limitations
-------------------

The end-to-end (e2e) test pipeline does not yet consistently use
concrete requirements.


.. _deadsnakes PPA: https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa
.. _pyenv: https://github.com/pyenv/pyenv
