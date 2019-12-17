"""Module comprises Krake Kubernetes application controller logic.
"""
from .hooks import (
    register_service,
    unregister_service,
    KubernetesObserver,
    merge_status,
)
from .kubernetes_application import KubernetesController

__all__ = [
    "KubernetesController",
    "register_service",
    "unregister_service",
    "KubernetesObserver",
    "merge_status",
]
