"""Module comprises Krake metrics functions and abstractions for selecting
the appropriate backend for application.
Each metrics provider client contains methods for asynchronous querying and
evaluating requested metrics.
Abstraction is provided by :class:`Provider`.
.. code:: python

    from krake.data.core import MetricsProvider

    metrics_provider = MetricsProvider.deserialize({
        'metadata': {'name': 'prometheus-1'},
        'spec': {
            'type': 'prometheus',
            'config': {'url': 'http://', 'metrics': ['heat']}
        }
    })
    provider = Provider(
        session=session,
        metric=metric,
        metrics_provider=metrics_provider,
    )
    assert isinstance(provider, Prometheus)
"""
from aiohttp import ClientSession

from krake.controller.exceptions import ControllerError
from krake.data.core import MetricProviderType, Metric, MetricsProvider, ReasonCode
from yarl import URL


class MetricValueError(ControllerError):
    """Raised when evaluation of metric value failed
    """

    code = ReasonCode.INVALID_METRIC_VALUE


class MissingMetricsDefinition(ControllerError):
    """Raised in case required metric definition is missing
    """

    code = ReasonCode.MISSING_METRIC_DEFINITION


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
    if not items:
        return {}
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

        provider = Provider(
            session=session, metric=metric, metrics_provider=metrics_provider
        )
        tasks.append(provider.query())

    return tasks


class Provider(object):
    """Base metrics provider client used as an abstract interface
    for selection of appropriate metrics provider client based of metrics
    provider definition.

    Subclassed metrics providers are stored in class variable `_subclasses`.
    Selection is evaluated in :meth:`__new__` based on the :args:`metrics_provider`.

    """

    _provider = None
    _subclasses = {}

    def __init_subclass__(cls, **kwargs):
        """Collect the :class:`Provider` subclasses into to the class
        variable `_subclasses`.

        Args:
            **kwargs: Keyword arguments

        """
        super().__init_subclass__(**kwargs)
        try:
            Provider._subclasses[cls._provider]
        except KeyError:
            Provider._subclasses[cls._provider] = cls
        else:
            raise ValueError(f"Metrics provider: {cls._provider} is already registered")

    def __new__(mcls, *args, **kwargs):
        provider = kwargs["metrics_provider"].spec.type.name
        return object.__new__(mcls._subclasses[provider])

    async def query(self):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Returns:

        """
        raise NotImplementedError


class Prometheus(Provider):
    """Prometheus metrics provider client. It creates and handles queries to the given
    prometheus server and evaluates requested metric values.

    :class:`Prometheus` is a subclass of :class:`Provider`,
    which is used as an abstract interface for its instantiate. Registration of any
    metrics provider into the :class:`Provider` abstraction interface is
    done by class variable `_provider` which contains metric provider type.
`
    """

    _provider = MetricProviderType.prometheus.name

    def __init__(
        self, session: ClientSession, metric: Metric, metrics_provider: MetricsProvider
    ):
        self.session = session
        self.metric = metric
        self.metric_provider = metrics_provider

    def evaluate_metric_value(self, value):
        """Evaluate metric value based on rules stored in metric specification

        Args:
            value (float): Metric value

        Raises:
            MetricValueError: When evaluation of metric value failed

        """
        if not self.metric.spec.min <= value <= self.metric.spec.max:
            raise MetricValueError(f"Metric value {value} evaluation failed")

    def get_metric_value(self, resp):
        """Returns metric value from Prometheus server response, based on metric name

        Args:
            resp (dict): Prometheus server response

        Raises:
            MetricValueError: When Prometheus server response doesn't contain requested
                metric name

        Returns:
            int: Metric value

        """
        for metric_data in resp["data"]["result"]:
            if (
                metric_data
                and metric_data["metric"]["__name__"] == self.metric.metadata.name
            ):
                return float(metric_data["value"][1])

        raise MetricValueError(
            f"Unable to get metric value from provider response {resp}"
        )

    async def query_metric(self):
        """Coroutine for metric request.

        """
        url = URL(self.metric_provider.spec.config.url).with_query(
            {"query": self.metric.metadata.name}
        )
        async with self.session.get(url) as resp:
            return await resp.json()

    async def query(self):
        """Asynchronous callback for evaluation of metric value executed
        when :meth:`query_metric` successfully returns response from metrics provider.

        Returns:
            krake.data.core.Metric: Metric with evaluated value

        """
        metric = self.metric

        resp = await self.query_metric()
        metric_value = self.get_metric_value(resp)
        self.evaluate_metric_value(metric_value)

        metric.spec.value = metric_value
        return metric
