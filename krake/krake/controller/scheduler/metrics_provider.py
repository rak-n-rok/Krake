"""Module comprises abstraction interface for accessing various metrics provider
clients. Each metrics provider client contains methods for asynchronous querying and
evaluating requested metrics.
Abstraction is provided by :class:`MetricsProviderClient`.
.. code:: python

    from krake.data.core import MetricsProvider

    metrics_provider = MetricsProvider.deserialize({
        'metadata': {'name': 'prometheus-1'},
        'spec': {
            'type': 'prometheus',
            'config': {'url': 'http://', 'metrics': ['heat']}
        }
    })
    provider = MetricsProviderClient.setup(
        session=session,
        metric=metric,
        metrics_provider=metrics_provider,
    )
    assert isinstance(provider, PrometheusMetricsProvider)
"""
from aiohttp import ClientSession

from krake.controller.exceptions import ControllerError
from krake.data.core import MetricProviderType, Metric, MetricsProvider
from yarl import URL


class MetricValueError(ControllerError):
    """Raised when evaluation of metric value failed
    """


class MetricsProviderClient(object):
    """Base metrics provider client used as an abstract interface
    for selection of appropriate metrics provider client based of metrics
    provider definition.

    Subclassed metrics providers are stored in class variable `_subclasses`.
    Selection is evaluated in :meth:`setup` based on the :args:`metrics_provider`.

    """

    _provider = None
    _subclasses = {}

    def __init_subclass__(cls, **kwargs):
        """Collect the :class:`MetricsProviderClient` subclasses into to the class
        variable `_subclasses`.

        Args:
            **kwargs: Keyword arguments

        """
        super().__init_subclass__(**kwargs)
        try:
            MetricsProviderClient._subclasses[cls._provider]
        except KeyError:
            MetricsProviderClient._subclasses[cls._provider] = cls
        else:
            raise ValueError(f"Metrics provider: {cls._provider} is already registered")

    @classmethod
    def setup(cls, **kwargs):
        """Instantiate :class:`MetricsProviderClient` subclass based on defined
        metrics provider.

        Args:
            **kwargs: Keyword arguments for the :class:`MetricsProviderClient` subclass

        Returns:
            :class:`MetricsProviderClient` subclass based on defined metrics provider

        """
        provider = kwargs["metrics_provider"].spec.type.name
        return cls._subclasses[provider](**kwargs)

    async def query(self):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Returns:

        """
        raise NotImplementedError


class PrometheusMetricsProvider(MetricsProviderClient):
    """Prometheus metrics provider client. It creates and handles queries to the given
    prometheus server and evaluates requested metric values.

    :class:`PrometheusMetricsProvider` is a subclass of :class:`MetricsProviderClient`,
    which is used as an abstract interface for its instantiate. Registration of any
    metrics provider into the :class:`MetricsProviderClient` abstraction interface is
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
            if metric_data["metric"]["__name__"] == self.metric.metadata.name:
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
