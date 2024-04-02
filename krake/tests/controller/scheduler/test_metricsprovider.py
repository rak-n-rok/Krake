import pytest
import unittest.mock as mock
import influxdb_client

from aiohttp import web, ClientSession, ClientConnectorError, ClientResponseError

from krake.controller.scheduler import metrics

from krake.controller.scheduler.metrics import MetricError, fetch_query
from krake.controller.scheduler.metrics import MetricsProviderError
from krake.controller.scheduler.metrics import Influx

from krake.test_utils import server_endpoint, make_prometheus, make_kafka

from tests.factories.core import GlobalMetricsProviderFactory, GlobalMetricFactory


@pytest.mark.slow
async def test_prometheus_provider_against_prometheus(prometheus, loop):
    metric = GlobalMetricFactory(
        spec__provider__name="my-provider",
        spec__provider__metric=prometheus.exporter.metric,
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        value = await provider.query(metric)
        assert 0 <= value <= 1.0


async def test_prometheus_mock(aiohttp_client):
    client = await aiohttp_client(make_prometheus({"my-metric": ["0.42", "1.0"]}))

    resp = await client.get("/api/v1/query?query=my-metric")
    body = await resp.json()
    assert body["status"] == "success"
    assert body["data"]["resultType"] == "vector"
    assert len(body["data"]["result"]) == 1
    result = body["data"]["result"][0]
    assert "metric" in result
    assert result["metric"]["__name__"] == "my-metric"
    assert "value" in result
    assert result["value"][1] == "0.42"

    resp = await client.get("/api/v1/query?query=my-metric")
    body = await resp.json()
    assert body["data"]["result"][0]["value"][1] == "1.0"

    resp = await client.get("/api/v1/query?query=my-metric")
    body = await resp.json()
    assert len(body["data"]["result"]) == 0


async def test_prometheus_mock_update(aiohttp_client):
    client = await aiohttp_client(make_prometheus({}))

    resp = await client.post("/-/update", json={"metrics": {"my-metric": ["0.42"]}})
    assert resp.status == 200

    resp = await client.get("/api/v1/query?query=my-metric")
    body = await resp.json()
    assert len(body["data"]["result"]) == 1
    assert body["data"]["result"][0]["value"][1] == "0.42"

    resp = await client.get("/api/v1/query?query=my-metric")
    body = await resp.json()
    assert len(body["data"]["result"]) == 0


async def test_prometheus_mock_update_validation(aiohttp_client):
    client = await aiohttp_client(make_prometheus({}))

    resp = await client.post("/-/update", data=b"invalid JSON")
    assert resp.status == 400

    resp = await client.post("/-/update", json=[])
    assert resp.status == 400

    resp = await client.post("/-/update", json={})
    assert resp.status == 400

    resp = await client.post("/-/update", json={"metrics": []})
    assert resp.status == 400

    resp = await client.post("/-/update", json={"metrics": {"my-metric": "text"}})
    assert resp.status == 400

    resp = await client.post("/-/update", json={"metrics": {"my-metric": ["1.0"]}})
    assert resp.status == 200


async def test_prometheus_mock_cycle_update(aiohttp_client):
    client = await aiohttp_client(make_prometheus({}))

    resp = await client.post(
        "/-/update", json={"metrics": {"my-metric": ["0.42", "1.0"]}, "cycle": True}
    )
    assert resp.status == 200

    for _ in range(2):
        resp = await client.get("/api/v1/query?query=my-metric")
        body = await resp.json()
        assert len(body["data"]["result"]) == 1
        assert body["data"]["result"][0]["value"][1] == "0.42"

        resp = await client.get("/api/v1/query?query=my-metric")
        body = await resp.json()
        assert len(body["data"]["result"]) == 1
        assert body["data"]["result"][0]["value"][1] == "1.0"


async def test_prometheus_provider(aiohttp_server, loop):
    prometheus = await aiohttp_server(make_prometheus({"my-metric": ["0.42"]}))

    metric = GlobalMetricFactory(
        spec__provider__name="my-provider", spec__provider__metric="my-metric"
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        value = await provider.query(metric)
        assert value == 0.42


async def test_prometheus_provider_metric_unavailable(aiohttp_server, loop):
    """Test the resilience of the Prometheus provider when the name of a metric taken
    from a Metric resource is not found.
    """
    prometheus = await aiohttp_server(make_prometheus({"my-metric": ["0.42"]}))

    metric = GlobalMetricFactory(
        spec__provider__name="my-provider", spec__provider__metric="other-metric"
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        with pytest.raises(
            MetricError, match="Metric 'other-metric' not in Prometheus response"
        ):
            await provider.query(metric)


async def test_prometheus_provider_invalid_metric(aiohttp_server, loop):
    """Test the resilience of the Prometheus provider when a metric value is not a
    integer or a float.
    """
    prometheus = await aiohttp_server(make_prometheus({"my-metric": ["not_a_float"]}))

    metric = GlobalMetricFactory(
        spec__provider__name="my-provider", spec__provider__metric="my-metric"
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        with pytest.raises(MetricError, match="Invalid value for metric 'my-metric'"):
            await provider.query(metric)


async def test_prometheus_provider_unavailable(aiohttp_server, loop):
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(_):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    metric = GlobalMetricFactory()
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        with pytest.raises(
            metrics.MetricsProviderError, match=r"Failed to query Prometheus"
        ) as err:
            await provider.query(metric)

        assert isinstance(err.value.__cause__, ClientResponseError)


async def test_prometheus_provider_connection_error(aiohttp_server, loop):
    # Spawn Prometheus mock server, fetch its HTTP address and close it again.
    # This should raise an "aiohttp.ClientConnectorError" in the provider when
    # it tries to connect to this endpoint.
    prometheus = await aiohttp_server(web.Application())
    url = server_endpoint(prometheus)
    await prometheus.close()

    metric = GlobalMetricFactory()
    metrics_provider = GlobalMetricsProviderFactory(
        spec__type="prometheus", spec__prometheus__url=url
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        with pytest.raises(
            metrics.MetricsProviderError, match=r"Failed to query Prometheus"
        ) as err:
            await provider.query(metric)

        assert isinstance(err.value.__cause__, ClientConnectorError)


async def test_static_provider(aiohttp_server):
    metrics_provider = GlobalMetricsProviderFactory(
        spec__type="static", spec__static__metrics={"my_metric": 0.42}
    )
    metric = GlobalMetricFactory(
        spec__provider__name=metrics_provider.metadata.name,
        spec__provider__metric="my_metric",
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Static)

        value = await provider.query(metric)
        assert value == 0.42


async def test_static_provider_metric_unavailable(aiohttp_server):
    """Test the resilience of the Static provider when the name of a metric taken from a
    Metric resource is not found.
    """
    metrics_provider = GlobalMetricsProviderFactory(
        spec__type="static", spec__static__metrics={"my_metric": 0.42}
    )
    metric = GlobalMetricFactory(
        spec__provider__name=metrics_provider.metadata.name,
        spec__provider__metric="other-metric",
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Static)

        with pytest.raises(MetricError, match="Metric 'other-metric' not defined"):
            await provider.query(metric)


@pytest.mark.slow
async def test_kafka_provider_against_kafka(ksql, loop):
    """Test that the Kafka Provider works against an actual KSQL database."""
    heat_demand_1_metric = ksql.kafka_table.metrics[0]
    metric = GlobalMetricFactory(
        spec__provider__name="my-provider",
        spec__provider__metric=heat_demand_1_metric.name,
    )

    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="kafka",
        spec__kafka__url=server_endpoint(ksql),
        spec__kafka__comparison_column=ksql.kafka_table.comparison_column,
        spec__kafka__value_column=ksql.kafka_table.value_column,
        spec__kafka__table=ksql.kafka_table.table,
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Kafka)

        value = await provider.query(metric)
        assert value == heat_demand_1_metric.value


async def test_kafka_mock(aiohttp_client):
    """Test the KSQL mock database."""
    columns = ["id", "value"]
    rows = [["first_id", [0.42, 1.0]]]
    client = await aiohttp_client(make_kafka("my_table", columns, rows))

    query = "SELECT value FROM my_table where id = 'first_id';"
    request = {"ksql": query, "streamsProperties": {}}
    resp = await client.post("/query", json=request)
    body = await resp.json()

    assert len(body) == 2
    assert "header" in body[0]
    assert body[0]["header"]["queryId"] == "query_0"
    assert body[0]["header"]["schema"] == "`VALUE` STRING"

    assert "row" in body[1]
    assert body[1]["row"]["columns"][0] == 0.42

    resp = await client.post("/query", json=request)
    body = await resp.json()
    assert body[1]["row"]["columns"][0] == 1.0

    resp = await client.post("/query", json=request)
    body = await resp.json()
    assert len(body) == 1
    assert "header" in body[0]

    query = "SELECT wrong_column FROM my_table where id = 'first_id';"
    request = {"ksql": query, "streamsProperties": {}}
    resp = await client.post("/query", json=request)
    assert resp.status == 400


async def test_kafka_provider(aiohttp_server, loop):
    """Test the Kafka provider against the KSQL mock database."""
    columns = ["id", "value"]
    rows = [["first_id", [0.42, 1.0]]]
    kafka = await aiohttp_server(make_kafka("my_table", columns, rows))

    metric = GlobalMetricFactory(
        spec__provider__name="my-provider", spec__provider__metric="first_id"
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="kafka",
        spec__kafka__comparison_column="id",
        spec__kafka__value_column="value",
        spec__kafka__table="my_table",
        spec__kafka__url=server_endpoint(kafka),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Kafka)

        value = await provider.query(metric)
        assert value == 0.42

        value = await provider.query(metric)
        assert value == 1.0


async def test_kafka_provider_metric_unavailable(aiohttp_server, loop):
    """Test the resilience of the Kafka provider when the name of a metric taken from a
    Metric resource is not found.
    """
    columns = ["id", "value"]
    rows = [["first_id", [0.42, 1.0]]]
    kafka = await aiohttp_server(make_kafka("my_table", columns, rows))

    metric = GlobalMetricFactory(
        spec__provider__name="my-provider", spec__provider__metric="wrong_id"
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="kafka",
        spec__kafka__comparison_column="id",
        spec__kafka__value_column="value",
        spec__kafka__table="my_table",
        spec__kafka__url=server_endpoint(kafka),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Kafka)

        with pytest.raises(
            MetricError, match="The value of the metric 'wrong_id' cannot be read"
        ):
            await provider.query(metric)


async def test_kafka_provider_unavailable(aiohttp_server, loop):
    routes = web.RouteTableDef()

    @routes.post("/query")
    async def _(_):
        raise web.HTTPServiceUnavailable()

    kafka_app = web.Application()
    kafka_app.add_routes(routes)

    kafka = await aiohttp_server(kafka_app)

    metric = GlobalMetricFactory()
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="kafka",
        spec__kafka__comparison_column="id",
        spec__kafka__value_column="value",
        spec__kafka__table="my_table",
        spec__kafka__url=server_endpoint(kafka),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Kafka)

        with pytest.raises(
            metrics.MetricsProviderError, match=r"Failed to query Kafka"
        ) as err:
            await provider.query(metric)

        assert isinstance(err.value.__cause__, ClientResponseError)


async def test_kafka_provider_connection_error(aiohttp_server, loop):
    # Spawn a KSQL mock database, fetch its HTTP address and close it again.
    # This should raise an "aiohttp.ClientConnectorError" in the provider when
    # it tries to connect to this endpoint.
    kafka = await aiohttp_server(web.Application())
    url = server_endpoint(kafka)
    await kafka.close()

    metric = GlobalMetricFactory()
    metrics_provider = GlobalMetricsProviderFactory(
        spec__type="kafka",
        spec__kafka__comparison_column="id",
        spec__kafka__value_column="value",
        spec__kafka__table="my_table",
        spec__kafka__url=url,
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Kafka)

        with pytest.raises(
            metrics.MetricsProviderError, match=r"Failed to query Kafka"
        ) as err:
            await provider.query(metric)

        assert isinstance(err.value.__cause__, ClientConnectorError)


async def test_fetch_query():
    """Test the output of the fetch_query function in normal conditions."""
    metrics_provider = GlobalMetricsProviderFactory(
        spec__type="static", spec__static__metrics={"my_metric": 0.42}
    )
    metric = GlobalMetricFactory(
        spec__provider__name=metrics_provider.metadata.name,
        spec__provider__metric="my_metric",
    )

    async with ClientSession() as session:
        query_result = await fetch_query(session, metric, metrics_provider, 10)

    assert query_result.metric == metric
    assert query_result.value == 0.42
    assert query_result.weight == 10


async def test_fetch_query_out_of_range():
    """Test the behavior of the fetch_query function when a metric value is out of
    range: should raise an exception.
    """
    metrics_provider = GlobalMetricsProviderFactory(
        spec__type="static", spec__static__metrics={"my_metric": 2}  # higher than max
    )
    # Default max is 1
    metric = GlobalMetricFactory(
        spec__provider__name=metrics_provider.metadata.name,
        spec__provider__metric="my_metric",
    )

    async with ClientSession() as session:
        with pytest.raises(
            MetricError,
            match=f"Invalid metric value for {metric.metadata.name!r}: 2 out of range",
        ):
            await fetch_query(session, metric, metrics_provider, 10)


async def test_influx_query():
    # Create a mock metric object
    mock_metric = mock.MagicMock()
    mock_metric.spec.provider.metric = 'metric_name'

    # Set the necessary attributes for the metrics provider
    mock_metrics_provider = mock.MagicMock()
    mock_metrics_provider.spec.influx.url = 'http://localhost:8086'
    mock_metrics_provider.spec.influx.token = 'your_token'
    mock_metrics_provider.spec.influx.org = 'your_org'
    mock_metrics_provider.spec.influx.bucket = 'your_bucket'
    mock_metrics_provider.spec.type = 'influx'

    class MockInfluxDBClient:
        def __init__(self, *args, **kwargs):
            pass

        def query_api(self):
            return self

        def query(self, query):
            # Mock the query result here
            mock_table = mock.MagicMock()
            mock_record = mock.MagicMock()
            mock_record.values = {'_value': '10'}
            mock_table.records = [mock_record]
            return [mock_table]

    # Create an instance of the Influx class with the custom mock class
    with mock.patch('krake.controller.scheduler.metrics.InfluxDBClient',
                    new=MockInfluxDBClient):
        influx = Influx(mock.MagicMock(), metrics_provider=mock_metrics_provider)

        # Call the query method
        result = await influx.query(mock_metric)

        # Assertions
        assert result == 10.0


async def test_influx_query_metrics_provider_error():
    # Create a mock metric object
    mock_metric = mock.MagicMock()
    mock_metric.spec.provider.metric = 'metric_name'

    # Set the necessary attributes for the metrics provider
    mock_metrics_provider = mock.MagicMock()
    mock_metrics_provider.spec.influx.url = 'http://localhost:8086'
    mock_metrics_provider.spec.influx.token = 'your_token'
    mock_metrics_provider.spec.influx.org = 'your_org'
    mock_metrics_provider.spec.influx.bucket = 'your_bucket'
    mock_metrics_provider.spec.type = 'influx'

    class MockInfluxDBClientMetricsProviderError:
        def __init__(self, *args, **kwargs):
            pass

        def query_api(self):
            return self

        def query(self, query):
            # Raise an exception to simulate an error
            raise influxdb_client.Error("Failed to query InfluxDB")

    # Create an instance of the Influx class with the custom mock class
    with mock.patch('krake.controller.scheduler.metrics.InfluxDBClient',
                    new=MockInfluxDBClientMetricsProviderError):
        influx = Influx(mock.MagicMock(), metrics_provider=mock_metrics_provider)

        # Assert that the MetricsProviderError exception is raised
        with pytest.raises(MetricsProviderError):
            await influx.query(mock_metric)


async def test_query_metric_not_found():
    # Create a mock metric object
    mock_metric = mock.MagicMock()
    mock_metric.spec.provider.metric = "mock_metric"

    mock_metrics_provider = mock.MagicMock()
    mock_metrics_provider.spec.influx.url = 'http://localhost:8086'
    mock_metrics_provider.spec.influx.token = 'your_token'
    mock_metrics_provider.spec.influx.org = 'your_org'
    mock_metrics_provider.spec.influx.bucket = 'your_bucket'
    mock_metrics_provider.spec.type = 'influx'

    # Create a custom mock class that returns an empty result
    class MockInfluxDBClientMetricError:
        def __init__(self, *args, **kwargs):
            pass

        def query_api(self):
            return self

        def query(self, query):
            # Return an empty result to simulate no records found
            return []

    # Create an instance of the Influx class with the custom mock class
    with mock.patch("krake.controller.scheduler.metrics.InfluxDBClient",
                    new=MockInfluxDBClientMetricError):
        influx = Influx(mock.MagicMock(), metrics_provider=mock_metrics_provider)

        # Assert that the MetricError exception is raised
        with pytest.raises(MetricError):
            await influx.query(mock_metric)

