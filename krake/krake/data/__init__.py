"""Data abstraction module for all REST resources used by the Krake API. This
module provides common data defintions for :mod:`krake.api` and
:mod:`krake.client`.

The core functionality is provided by :mod:`.serializable` providing a Python
API for declarative defintions of data models together with serializing and
deserializing functionality.

Domain-specific models are defined in corresponding submodules, e.g.
Kubernetes-related data models are defined in :mod:`.kubernetes`.
"""
from .serializable import serialize, deserialize  # noqa
