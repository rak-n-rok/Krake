"""Module comprises Krake metrics functions and abstractions for selecting
the appropriate backend for application.

Each metrics provider client contains methods for asynchronous querying and
evaluating requested metrics.

Abstraction is provided by :class:`Provider`.

.. code:: python

    from krake.data.core import MetricsProvider

    metrics_provider = MetricsProvider.deserialize({
        "metadata": {
            "name": "prometheus-1"
        },
        "spec": {
            "type": "prometheus",
            "prometheus": {
                "url": "http://",
            }
        }
    })
    provider = Provider(
        session=session,
        metric=metric,
        metrics_provider=metrics_provider,
    )
    assert isinstance(provider, Prometheus)

"""
import asyncio
from typing import NamedTuple
from aiohttp import ClientSession, ClientError, ClientTimeout

from krake.data.core import MetricsProvider, Metric
from yarl import URL


class MetricError(Exception):
    """Raised when evaluation of metric value fails"""


class QueryResult(NamedTuple):
    metric: Metric
    weight: float
    value: float


def normalize(metric, value):
    """Normalize metric value into range [0; 1] based on the given borders in
    the specification of the metric.

    Args:
        metric (Metric): Metric description
        value (float): Metric value

    Raises:
        MetricError: If metric value is out of the specified range

    Returns:
        float: Normalized metric value in range [0; 1]

    """
    if not metric.spec.min <= value <= metric.spec.max:
        raise MetricError(f"Invalid metric value {value!r}")

    return (value - metric.spec.min) / (metric.spec.max - metric.spec.min)


async def fetch_query(session, metric, provider, weight):
    """Fetch asynchronous task for getting the metric value from appropriate
    metrics provider.

    Args:
        session (aiohttp.client.ClientSession): Aiohttp session
        metric (Metric): Metric definition
        provider (MetricsProvider): Metrics provider definition for metric
        weight (float): Weight of the metric

    Raises:
        MetricError: If the value of the metric cannot be fetched or is invalid

    Returns:
        QueryResult: Tuple of metric, its fetched value and its weight.

    """
    provider = Provider(session=session, metrics_provider=provider)
    value = await provider.query(metric)
    return QueryResult(metric=metric, value=normalize(metric, value), weight=weight)


class Provider(object):
    """Base metrics provider client used as an abstract interface
    for selection of appropriate metrics provider client based of metrics
    provider definition.

    Subclassed metrics providers are stored in class variable :attr:`registry`.
    Selection is evaluated in :meth:`__new__` based on the :args:`metrics_provider`.

    Attributes:
        registry (Dict[str, type]): Subclass registry mapping the name of provider
            types to their respective provider implementation.
        type (str): Name of the provider type that this subclass implements. The
            name should have a matching provider type in
            :class:`krake.data.core.MetricsProviderSpec`.
    """

    registry = {}

    def __init_subclass__(cls, **kwargs):
        """Collect the :class:`Provider` subclasses into :attr:`registry`.

        Args:
            **kwargs: Keyword arguments

        """
        super().__init_subclass__(**kwargs)
        if cls.type in cls.registry:
            raise ValueError(f"Metrics provider: {cls.type} is already registered")

        cls.registry[cls.type] = cls

    def __new__(mcls, *args, **kwargs):
        provider_type = kwargs["metrics_provider"].spec.type
        return object.__new__(mcls.registry[provider_type])

    async def query(self, metric):
        """Returns the metric value using the metric provider.

        Args:
            metric (Metric): Metric description.

        Returns:
            Any: Metric value returned by the metrics provider.

        Raises:
            MetricError: If the requested metric name cannot be found in the
                specification.

        """
        raise NotImplementedError()


class Prometheus(Provider):
    """Prometheus metrics provider client. It creates and handles queries to the given
    prometheus server and evaluates requested metric values.
    """

    type = "prometheus"

    def __init__(self, session: ClientSession, metrics_provider: MetricsProvider):
        self.session = session
        self.metrics_provider = metrics_provider

    async def query(self, metric):
        """Querying a metric from a Prometheus server.

        Args:
            metric (Metric): Metric description

        Returns:
            float: Metric value fetched from Prometheus

        Raises:
            MetricError: If the request to Prometheus fails, the response does
                not contain the requested metric name or the metric cannot be
                converted into a float.

        """
        metric_name = metric.spec.provider.metric

        url = (
            URL(self.metrics_provider.spec.prometheus.url) / "api/v1/query"
        ).with_query({"query": metric_name})

        try:
            # The value of 20 is only here to prevent a long timeout of 5 minutes
            # by default with aiohttp.
            # TODO: The mechanism of fetching metrics will be changed with the issue
            #  #326, so this timeout should be modified at this moment. This timeout
            #  allows the integration tests to last not too long.
            wait_time = 20
            timeout = ClientTimeout(total=wait_time)
            async with self.session.get(url, timeout=timeout) as resp:
                resp.raise_for_status()
                body = await resp.json()
        except (ClientError, asyncio.TimeoutError) as err:
            raise MetricError("Failed to query Prometheus") from err

        # @see https://prometheus.io/docs/prometheus/latest/querying/api/
        for result in body["data"]["result"]:
            if result and result["metric"]["__name__"] == metric_name:
                try:
                    return float(result["value"][1])
                except (TypeError, ValueError) as err:
                    raise MetricError(
                        f"Invalid value for metric {metric_name!r}"
                    ) from err

        raise MetricError(f"Metric {metric_name!r} not in Prometheus response")


class Static(Provider):
    """Static metrics provider client. It simply returns the value configured
    in the metric's :class:`krake.data.core.StaticSpec`.
    """

    type = "static"

    def __init__(self, session, metrics_provider):
        self.metrics_provider = metrics_provider

    async def query(self, metric):
        """Returns the metric defined in the static metrics provider
        specification.

        Args:
            metric (Metric): Metric description. Ignored by this method

        Returns:
            float: Metric value specified in the static metrics provider
            specification.

        Raises:
            MetricError: If the requested metric name cannot be found in the
                specification.

        """
        name = metric.spec.provider.metric

        try:
            return self.metrics_provider.spec.static.metrics[name]
        except KeyError as err:
            raise MetricError(f"Metric {name!r} not defined") from err
