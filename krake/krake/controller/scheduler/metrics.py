"""Module comprises Krake metrics helper functions for selecting the appropriate
    backend for application
"""
from krake.controller.exceptions import ControllerError

from .metrics_provider import MetricsProviderClient


class MissingMetricsDefinition(ControllerError):
    """Raised in case required metric definition is missing
    """


def to_named_deserialize(items, obj):
    """Deserialize each item from list of :param:`items` based on defined object
    type :param:`obj`. Store the result of deserialization as value of dictionary where
    the key is item name. Deserialization is skipped in case of already
    deserialized objects.

    Example:
        .. code:: python

            from krake.data.core import Metric

            metrics = [
                {'metadata': {'name': 'up'},
                    'spec': {
                        'value': 0.5,
                        'provider': {
                                'name': 'zone-1',
                                'metric': 'heat'
                        }
                    }
                }
            ]
            metrics_obj = to_named_deserialize(metrics, Metric)
            assert isinstance(metrics_obj["up"], Metric)

    Args:
        items (list): List of object to deserialize
        obj: Object from `krake.data` with :meth:`deserialize`

    Returns:
        dict: Item name as key and deserialize item as value

    """
    named_deserialize = {}
    for item in items:
        if isinstance(item, obj):
            named_deserialize[item.metadata.name] = item
        else:
            item_obj = obj.deserialize(item)
            named_deserialize[item_obj.metadata.name] = item_obj

    return named_deserialize


def merge_obj(parent, slave, obj):
    """Merge two `dict` into one based of rule: :param:`parent` overwrite
    the :param:`slave`.

    Args:
        parent (dict): Parent dictionary
        slave (dict): Slave dictionary. It can be overwritten by parent
        obj: Object from `krake.data` used for deserialization in
            :func:`to_named_deserialize`

    Returns:
        dict: Merged dictionary

    """
    parent_named = to_named_deserialize(parent, obj)
    slave_named = to_named_deserialize(slave, obj)
    return {**slave_named, **parent_named}


def get_metrics_providers_objs(cluster, metrics_all, metrics_providers_all):
    """Collect metrics and metrics providers definitions for given cluster.

    Args:
        cluster (Cluster): Cluster with metrics definitions
        metrics_all (dict): Bunch of available metrics definitions
        metrics_providers_all (dict): Bunch of available metrics providers definitions

    Raises:
         MissingMetricsDefinition: When required metric definition is missing

    Returns:
        tuple(List[Metric], List[MetricsProvider]): Metrics and metrics providers
            definitions for given cluster

    """
    if not cluster.spec.metrics:
        raise MissingMetricsDefinition(
            f"Missing metrics definitions for cluster {cluster.metadata.name}"
        )

    metrics = []
    metrics_providers = []
    for metric_cluster in cluster.spec.metrics:
        try:
            metric_obj = metrics_all[metric_cluster]
            metrics.append(metric_obj)
        except KeyError:
            raise MissingMetricsDefinition(
                f"Missing metric {metric_cluster} object definition for cluster "
                f"{cluster.metadata.name}"
            )

        try:
            metrics_providers.append(
                metrics_providers_all[metric_obj.spec.provider.name]
            )
        except KeyError:
            raise MissingMetricsDefinition(
                f"Missing metrics provider {metric_obj.spec.provider.name} object "
                f"definition for cluster {cluster.metadata.name}"
            )

    return metrics, metrics_providers


def fetch_query_tasks(session, metrics, metrics_providers):
    """Collect asynchronous tasks for getting the metrics values from appropriate
    metrics providers.

    Args:
        session (aiohttp.client.ClientSession): Aiohttp session
        metrics (List[Metric]): List of metrics
        metrics_providers (List[MetricsProvider]): List of metrics providers
            for metrics

    Returns:
        list: List of asynchronous tasks

    """
    tasks = []
    for metric, metrics_provider in zip(metrics, metrics_providers):

        provider = MetricsProviderClient.setup(
            session=session, metric=metric, metrics_provider=metrics_provider
        )
        tasks.append(provider.query())

    return tasks
