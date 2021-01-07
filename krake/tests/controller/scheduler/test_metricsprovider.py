import pytest
from aiohttp import web, ClientSession, ClientConnectorError, ClientResponseError

from krake.controller.scheduler import metrics
from krake.test_utils import server_endpoint, make_prometheus, make_kafka

from tests.factories.core import MetricsProviderFactory, MetricFactory


@pytest.mark.slow
async def test_prometheus_provider_against_prometheus(prometheus, loop):
    metric = MetricFactory(
        spec__provider__name="my-provider",
        spec__provider__metric=prometheus.exporter.metric,
    )
    metrics_provider = MetricsProviderFactory(
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

    metric = MetricFactory(
        spec__provider__name="my-provider", spec__provider__metric="my-metric"
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        value = await provider.query(metric)
        assert value == 0.42


async def test_prometheus_provider_unavailable(aiohttp_server, loop):
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    metric = MetricFactory()
    metrics_provider = MetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        with pytest.raises(
            metrics.MetricError, match=r"Failed to query Prometheus"
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

    metric = MetricFactory()
    metrics_provider = MetricsProviderFactory(
        spec__type="prometheus", spec__prometheus__url=url
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Prometheus)

        with pytest.raises(
            metrics.MetricError, match=r"Failed to query Prometheus"
        ) as err:
            await provider.query(metric)

        assert isinstance(err.value.__cause__, ClientConnectorError)


async def test_static_provider(aiohttp_server):
    metrics_provider = MetricsProviderFactory(
        spec__type="static", spec__static__metrics={"my_metric": 0.42}
    )
    metric = MetricFactory(
        spec__provider__name=metrics_provider.metadata.name,
        spec__provider__metric="my_metric",
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Static)

        value = await provider.query(metric)
        assert value == 0.42


@pytest.mark.slow
async def test_kafka_provider_against_kafka(ksql, loop):
    """Test that the Kafka Provider works against an actual KSQL database.
    """
    heat_demand_1_metric = ksql.kafka_table.metrics[0]
    metric = MetricFactory(
        spec__provider__name="my-provider",
        spec__provider__metric=heat_demand_1_metric.name,
    )

    metrics_provider = MetricsProviderFactory(
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
    """Test the KSQL mock database.
    """
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
    """Test the Kafka provider against the KSQL mock database.
    """
    columns = ["id", "value"]
    rows = [["first_id", [0.42, 1.0]]]
    kafka = await aiohttp_server(make_kafka("my_table", columns, rows))

    metric = MetricFactory(
        spec__provider__name="my-provider", spec__provider__metric="first_id"
    )
    metrics_provider = MetricsProviderFactory(
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


async def test_kafka_provider_unavailable(aiohttp_server, loop):
    routes = web.RouteTableDef()

    @routes.post("/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    kafka_app = web.Application()
    kafka_app.add_routes(routes)

    kafka = await aiohttp_server(kafka_app)

    metric = MetricFactory()
    metrics_provider = MetricsProviderFactory(
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

        with pytest.raises(metrics.MetricError, match=r"Failed to query Kafka") as err:
            await provider.query(metric)

        assert isinstance(err.value.__cause__, ClientResponseError)


async def test_kafka_provider_connection_error(aiohttp_server, loop):
    # Spawn a KSQL mock database, fetch its HTTP address and close it again.
    # This should raise an "aiohttp.ClientConnectorError" in the provider when
    # it tries to connect to this endpoint.
    kafka = await aiohttp_server(web.Application())
    url = server_endpoint(kafka)
    await kafka.close()

    metric = MetricFactory()
    metrics_provider = MetricsProviderFactory(
        spec__type="kafka",
        spec__kafka__comparison_column="id",
        spec__kafka__value_column="value",
        spec__kafka__table="my_table",
        spec__kafka__url=url,
    )

    async with ClientSession() as session:
        provider = metrics.Provider(metrics_provider=metrics_provider, session=session)
        assert isinstance(provider, metrics.Kafka)

        with pytest.raises(metrics.MetricError, match=r"Failed to query Kafka") as err:
            await provider.query(metric)

        assert isinstance(err.value.__cause__, ClientConnectorError)
