"""This module evaluates if all application constraints match cluster.
Only clusters that fulfills all application constraints could be considered by scheduler
algorithm as a potential clusters for application deployment.

"""
import logging
from typing import NamedTuple, Callable

from krake.data.core import resource_ref, MetricRef


logger = logging.getLogger(__name__)


class AppClusterConstraint(NamedTuple):
    name: str
    values: list
    condition: Callable


class ClusterCloudConstraint(NamedTuple):
    name: str
    values: list
    condition: Callable


def _evaluate(resource, resource_to_match, constraints, fetched_metrics):
    """Evaluate if all :args:`resource` constraints defined in :args:`constraints`
    match definitions of :args:`resource_to_match`.

    Args:
        resource (krake.data.serializable.ApiObject): Resource that should be
            bound.
        resource_to_match (krake.data.serializable.ApiObject): Resource that acts as
            destination.
        constraints (List[Union[AppClusterConstraint, ClusterCloudConstraint]): List of
            resource constraints for evaluation

    Returns:
        bool: True if the :args:`resource_to_match` fulfills all
            given :args:`resource` constraints

    """
    for constraint in constraints:
        if constraint.values:
            for value in constraint.values:
                if constraint.name == "label" or constraint.name == "custom resource":
                    callable = constraint.condition(value, resource_to_match)
                else:
                    callable = constraint.condition(
                        value, resource_to_match, fetched_metrics
                    )
                if callable:
                    logger.debug(
                        f"Resource %s matches {constraint.name} constraint %r",
                        resource_ref(resource_to_match),
                        constraint,
                    )
                else:
                    logger.debug(
                        f"Resource %s does not match {constraint.name} constraint %r",
                        resource_ref(resource_to_match),
                        constraint,
                    )
                    return False

    logger.debug(
        "Resource %s fulfills all constraints of resource %r",
        resource_ref(resource_to_match),
        resource_ref(resource),
    )
    return True


def _condition_custom_resources(constraint, resource):
    return constraint in resource.spec.custom_resources


def _condition_label(constraint, resource):
    return constraint.match(resource.metadata.labels or {})


def _condition_metric(constraint, resource, fetched_metrics):
    metrics = fetched_metrics[resource.metadata.name]
    refs = dict()
    for m in metrics:
        namespaced = False
        if m.metric.metadata.namespace:
            namespaced = True
        refs[m.metric.metadata.name] = MetricRef(
            name=m.metric.metadata.name,
            weight=(m.weight * m.value),
            namespaced=namespaced,
        )
    return constraint.match(refs or {})


def match_cluster_constraints(app, cluster, fetched_metrics=None):
    """Evaluate if all application cluster constraints match cluster.

    Args:
        app (krake.data.kubernetes.Application): Application that should be
            bound.
        cluster (krake.data.kubernetes.Cluster): Cluster to which the
            application should be bound.
        fetched_metrics(dict): A dict containing the metrics for each cluster

    Returns:
        bool: True if the cluster fulfills all application cluster constraints

    """
    if not app.spec.constraints or not app.spec.constraints.cluster:
        logger.debug(f"{app.metadata.name}: no constraints existing")
        return True

    constraints = [
        AppClusterConstraint(
            "label",
            app.spec.constraints.cluster.labels,
            _condition_label
        ),
        AppClusterConstraint(
            "custom resource",
            app.spec.constraints.cluster.custom_resources,
            _condition_custom_resources,
        ),
        AppClusterConstraint(
            "metric", app.spec.constraints.cluster.metrics, _condition_metric
        ),
    ]

    return _evaluate(app, cluster, constraints, fetched_metrics)


def match_cloud_constraints(cluster, cloud, fetched_metrics=None):
    """Evaluate if all cluster cloud constraints match a cloud.

    Args:
        cluster (krake.data.kubernetes.Cluster): Cluster that should be
            bound.
        cloud (Union[Cloud, GlobalCloud]): Cloud to which the
            Cluster should be bound.
        fetched_metrics(dict): A dict containing the metrics for each cloud.

    Returns:
        bool: True if the cloud fulfills all cluster cloud constraints.

    """
    if not cluster.spec.constraints or not cluster.spec.constraints.cloud:
        return True

    constraints = [
        ClusterCloudConstraint(
            "label", cluster.spec.constraints.cloud.labels, _condition_label
        ),
        ClusterCloudConstraint(
            "metric", cluster.spec.constraints.cloud.metrics, _condition_metric
        ),
    ]

    return _evaluate(cluster, cloud, constraints, fetched_metrics)


def match_project_constraints(cluster, project):
    """Evaluate if all application constraints labels match project labels.

    Args:
        cluster (krake.data.openstack.MagnumCluster): Cluster that is scheduled
        project (krake.data.kubernetes.project): Project to which the
            cluster should be bound.

    Returns:
        bool: True if the project fulfills all project constraints

    """
    if not cluster.spec.constraints:
        logger.debug(f"{cluster.metadata.name}: no project constraints existing")
        return True

    # project constraints
    if cluster.spec.constraints.project:
        # Label constraints for the project
        if cluster.spec.constraints.project.labels:
            for constraint in cluster.spec.constraints.project.labels:
                if constraint.match(project.metadata.labels or {}):
                    logger.debug(
                        "Project %s matches constraint %r",
                        resource_ref(project),
                        constraint,
                    )
                else:
                    logger.debug(
                        "Project %s does not match constraint %r",
                        resource_ref(project),
                        constraint,
                    )
                    return False

    logger.debug("Project %s fulfills constraints of %r", project, cluster)

    return True
