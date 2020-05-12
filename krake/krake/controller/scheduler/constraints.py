"""This module evaluates if all application constraints match cluster.
Only clusters that fulfills all application constraints could be considered by scheduler
algorithm as a potential clusters for application deployment.

"""
import logging
from typing import NamedTuple, Callable

from krake.data.core import resource_ref

logger = logging.getLogger(__name__)


class AppClusterConstraint(NamedTuple):
    name: str
    values: list
    condition: Callable


def _evaluate(app, cluster, constraints):
    """Evaluate if all given application constraints defined in :args:`constraints`
    match given cluster definition.

    Args:
        app (krake.data.kubernetes.Application): Application that should be
            bound.
        cluster (krake.data.kubernetes.Cluster): Cluster to which the
            application should be bound.
        constraints (List[AppClusterConstraint]): List of AppClusterConstraint objects
            for evaluation

    Returns:
        bool: True if the cluster fulfills all given application constraints

    """
    for constraint in constraints:
        if constraint.values:
            for value in constraint.values:
                if constraint.condition(value, cluster):
                    logger.debug(
                        f"Cluster %s matches {constraint.name} constraint %r",
                        resource_ref(cluster),
                        constraint,
                    )
                else:
                    logger.debug(
                        f"Cluster %s does not match {constraint.name} constraint %r",
                        resource_ref(cluster),
                        constraint,
                    )
                    return False

    logger.debug(
        "Cluster %s fulfills all constraints of application %r",
        resource_ref(cluster),
        resource_ref(app),
    )
    return True


def _condition_custom_resources(constraint, cluster):
    return constraint in cluster.spec.custom_resources


def _condition_label(constraint, cluster):
    return constraint.match(cluster.metadata.labels or {})


def match_cluster_constraints(app, cluster):
    """Evaluate if all application cluster constraints match cluster.

    Args:
        app (krake.data.kubernetes.Application): Application that should be
            bound.
        cluster (krake.data.kubernetes.Cluster): Cluster to which the
            application should be bound.

    Returns:
        bool: True if the cluster fulfills all application cluster constraints

    """
    if not app.spec.constraints or not app.spec.constraints.cluster:
        return True

    constraints = [
        AppClusterConstraint(
            "label", app.spec.constraints.cluster.labels, _condition_label
        ),
        AppClusterConstraint(
            "custom resource",
            app.spec.constraints.cluster.custom_resources,
            _condition_custom_resources,
        ),
    ]

    return _evaluate(app, cluster, constraints)
