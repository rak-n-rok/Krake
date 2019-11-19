"""Module comprises Krake Kubernetes application controller logic.
"""
from .hooks import register_service, unregister_service
from .kubernetes_application import ApplicationController

__all__ = ["ApplicationController", "register_service", "unregister_service"]
