"""Module comprises Krake Kubernetes application controller logic.
"""
from .hooks import (
    register_service,
    unregister_service,
    KubernetesObserver,
    merge_status,
)
from .kubernetes import KubernetesController, KubernetesClient

__all__ = [
    "KubernetesController",
    "KubernetesClient",
    "register_service",
    "unregister_service",
    "KubernetesObserver",
    "merge_status",
]
