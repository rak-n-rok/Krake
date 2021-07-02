"""Module comprises Krake metrics functions and abstractions for selecting
the appropriate backend for application.

Each metrics provider client contains methods for asynchronous querying and
evaluating requested metrics.

Abstraction is provided by :class:`Provider`.

.. code:: python

    from krake.data.core import GlobalMetricsProvider

    metrics_provider = GlobalMetricsProvider.deserialize({
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
from aiohttp import ClientError, ClientTimeout

from krake.data.core import GlobalMetric
from yarl import URL


class BaseMetricError(Exception):
    """Base exception class for all errors related to metrics or metrics providers."""


class MetricError(BaseMetricError):
    """Raised when evaluation of metric value fails"""


class MetricsProviderError(BaseMetricError):
    """Raised when the connection to a metric provider fails."""


class QueryResult(NamedTuple):
    metric: GlobalMetric
    weight: float
    value: float


def normalize(metric, value):
    """Normalize metric value into range [0; 1] based on the given borders in
    the specification of the metric.

    Args:
        metric (GlobalMetric): Metric description
        value (float): Metric value

    Raises:
        MetricError: If metric value is out of the specified range

    Returns:
        float: Normalized metric value in range [0; 1]

    """
    if not metric.spec.min <= value <= metric.spec.max:
        raise MetricError(
            f"Invalid metric value for {metric.metadata.name!r}:"
            f" {value!r} out of range"
        )

    return (value - metric.spec.min) / (metric.spec.max - metric.spec.min)


async def fetch_query(session, metric, provider, weight):
    """Fetch asynchronous task for getting the metric value from appropriate
    metrics provider.

    Args:
        session (aiohttp.client.ClientSession): Aiohttp session
        metric (GlobalMetric): Metric definition
        provider (GlobalMetricsProvider): Metrics provider definition for metric
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
    type = None

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
        """Get the Provider class depending on the given metrics provider type.

        Returns:
              Provider: the instantiated Provider client to use.

        """
        provider_type = kwargs["metrics_provider"].spec.type
        return object.__new__(mcls.registry[provider_type])

    async def query(self, metric):
        """Returns the metric value using the metric provider.

        Args:
            metric (GlobalMetric): Metric description.

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

    Args:
        session (aiohttp.ClientSession): Aiohttp session
        metrics_provider (krake.data.core.MetricsProvider): Metrics provider definition,
            to use for getting information for fetching the queries.

    """

    type = "prometheus"

    def __init__(self, session, metrics_provider):
        self.session = session
        self.metrics_provider = metrics_provider

    async def query(self, metric):
        """Querying a metric from a Prometheus server.

        Args:
            metric (GlobalMetric): Metric description

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
            metric_provider_name = self.metrics_provider.metadata.name
            raise MetricsProviderError(
                f"Failed to query Prometheus with provider {metric_provider_name!r}"
            ) from err

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


class Kafka(Provider):
    """Kafka metrics provider client for KSQL. It creates and handles queries to the
    given KSQL database and evaluates requested metric values.
    """

    type = "kafka"

    def __init__(self, session, metrics_provider):
        self.session = session
        self.metrics_provider = metrics_provider

    async def query(self, metric):
        """Sends a KSQL query to a KSQL database, in order to fetch the current value
        of the provided metrics.

        The value is taken from a specific row on a specific table, using a query like
        the following:

        SELECT <value_column> FROM <table>
        WHERE <comparison_column> = '<metric_name>';

        To get the right row, the value of all rows on the column "<comparison_column>"
        is compared with the metric name. The row that matches is then selected, and the
        value on this row at the column "<value_column>" is returned by KSQL. The
        response is then parsed accordingly. All parameters except the metric name are
        defined in the Kafka metric provider. The name is the one of the current metric,
        bound to a cluster.

        Args:
            metric (GlobalMetric): Metric description.

        Returns:
            float: Metric value fetched from the KSQL database.

        Raises:
            MetricError: if the database is unreachable or the response cannot be
            parsed.

        """
        metric_name = metric.spec.provider.metric
        kafka_spec = self.metrics_provider.spec.kafka

        url = URL(kafka_spec.url) / "query"

        query = (
            f"SELECT {kafka_spec.value_column} FROM {kafka_spec.table}"
            f" WHERE {kafka_spec.comparison_column} = '{metric_name}';"
        )
        request = {"ksql": query, "streamsProperties": {}}

        try:
            # The value of 20 is only here to prevent a long timeout of 5 minutes
            # by default with aiohttp.
            # TODO: The mechanism of fetching metrics will be changed with the issue
            #  #326, so this timeout should be modified at this moment. This timeout
            #  allows the integration tests to last not too long.
            wait_time = 20
            timeout = ClientTimeout(total=wait_time)
            async with self.session.post(url, json=request, timeout=timeout) as resp:
                resp.raise_for_status()
                body = await resp.json()
        except (ClientError, asyncio.TimeoutError) as err:
            metric_provider_name = self.metrics_provider.metadata.name
            raise MetricsProviderError(
                f"Failed to query Kafka with provider {metric_provider_name!r}"
            ) from err

        try:
            resp_row = body[1]["row"]
            return float(resp_row["columns"][0])
        except (IndexError, KeyError) as err:
            message = (
                f"The value of the metric {metric_name!r}"
                f" cannot be read from the KSQL response"
            )
            raise MetricError(message) from err


class Static(Provider):
    """Static metrics provider client. It simply returns the value configured
    in the metric's :class:`krake.data.core.StaticSpec`.

    Args:
        session (aiohttp.ClientSession): Aiohttp session
        metrics_provider (krake.data.core.MetricsProvider): Metrics provider definition,
            to use for getting information for fetching the queries.

    """

    type = "static"

    def __init__(self, session, metrics_provider):
        self.metrics_provider = metrics_provider

    async def query(self, metric):
        """Returns the metric defined in the static metrics provider
        specification.

        Args:
            metric (GlobalMetric): Metric description. Ignored by this method

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
