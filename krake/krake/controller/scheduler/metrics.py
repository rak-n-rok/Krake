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
from aiohttp import ClientSession

from krake.controller.exceptions import ControllerError
from krake.data.core import MetricsProvider, ReasonCode
from yarl import URL


class MetricValueError(ControllerError):
    """Raised when evaluation of metric value failed
    """

    code = ReasonCode.INVALID_METRIC_VALUE


def validate(metric, value):
    """Validate metric value based on rules stored in metric specification

    Args:
        metric (Metric): Metric description
        value (float): Metric value

    Raises:
        MetricValueError: When evaluation of metric value failed

    """
    if not metric.spec.min <= value <= metric.spec.max:
        raise MetricValueError(f"Invalid metric value {value!r}")


async def fetch_query(session, metric, provider):
    """Fetch asynchronous task for getting the metric value from appropriate
    metrics provider.

    Args:
        session (aiohttp.client.ClientSession): Aiohttp session
        metric (Metric): Metric definition
        provider (MetricsProvider): Metrics provider definition for metric

    Raises:
        MetricValueError: If the value of the metric is invalid

    Returns:
        Tuple[Metric, float]: Tuple of metric and its fetched value

    """
    provider = Provider(session=session, metrics_provider=provider)
    value = await provider.query(metric)
    validate(metric, value)
    return metric, value


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

    async def query(self):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.
        """
        raise NotImplementedError


class Prometheus(Provider):
    """Prometheus metrics provider client. It creates and handles queries to the given
    prometheus server and evaluates requested metric values.
    """

    type = "prometheus"

    def __init__(self, session: ClientSession, metrics_provider: MetricsProvider):
        self.session = session
        self.metric_provider = metrics_provider

    async def query(self, metric):
        """Querying a metric from a Prometheus server.

        Args:
            metric (Metric): Metric description

        Returns:
            float: Metric value fetched from Prometheus

        Raises:
            MetricValueError: When Prometheus server response doesn't contain requested
                metric name or the metric cannot be converted into a float

        """
        metric_name = metric.spec.provider.metric

        url = (
            URL(self.metric_provider.spec.prometheus.url) / "api/v1/query"
        ).with_query({"query": metric_name})

        async with self.session.get(url) as resp:
            body = await resp.json()

        # @see https://prometheus.io/docs/prometheus/latest/querying/api/
        for result in body["data"]["result"]:
            if result and result["metric"]["__name__"] == metric_name:
                try:
                    return float(result["value"][1])
                except (TypeError, ValueError) as e:
                    raise MetricValueError(
                        f"Invalid value for metric {metric_name!r}"
                    ) from e

        raise MetricValueError(f"Metric {metric_name!r} not in Prometheus response")
