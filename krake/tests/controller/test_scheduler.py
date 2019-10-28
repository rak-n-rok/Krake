import pytest
from datetime import datetime
from aiohttp import web, ClientSession, ClientConnectorError, ClientResponseError

from krake.api.app import create_app
from krake.data.kubernetes import Application, ApplicationState, LabelConstraint
from krake.controller.scheduler import Scheduler, metrics

from krake.client import Client
from krake.data.core import resource_ref, ReasonCode
from krake.test_utils import server_endpoint, make_prometheus
from factories.core import MetricsProviderFactory, MetricFactory
from factories.kubernetes import ApplicationFactory, ClusterFactory


async def test_kubernetes_reception(aiohttp_server, config, db, loop):
    # Test that the Reflector present on the Scheduler actually put the
    # right received Applications on the WorkQueue.
    scheduled = ApplicationFactory(
        status__state=ApplicationState.PENDING, status__is_scheduled=True
    )
    updated = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__is_scheduled=False
    )
    pending = ApplicationFactory(
        status__state=ApplicationState.PENDING, status__is_scheduled=False
    )
    deleted = ApplicationFactory(
        metadata__deleted=datetime.now(),
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=False,
    )

    assert updated.metadata.modified > updated.status.scheduled

    server = await aiohttp_server(create_app(config))

    await db.put(scheduled)
    await db.put(updated)
    await db.put(pending)
    await db.put(deleted)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await scheduler.prepare(client)  # need to be called explicitly
        await scheduler.reflector.list_resource()

    assert scheduled.metadata.uid not in scheduler.queue.dirty
    assert updated.metadata.uid in scheduler.queue.dirty
    assert pending.metadata.uid in scheduler.queue.dirty
    assert deleted.metadata.uid not in scheduler.queue.dirty

    assert scheduled.metadata.uid in scheduler.queue.timers
    assert deleted.metadata.uid not in scheduler.queue.timers


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


def test_kubernetes_match_cluster_label_constraints():
    cluster = ClusterFactory(metadata__labels={"location": "IT"})
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")]
    )

    assert Scheduler.match_cluster_constraints(app, cluster)


def test_kubernetes_match_empty_cluster_label_constraints():
    cluster = ClusterFactory(metadata__labels=[])
    app1 = ApplicationFactory(spec__constraints=None)
    app2 = ApplicationFactory(spec__constraints__cluster=None)
    app3 = ApplicationFactory(spec__constraints__cluster__labels=None)

    assert Scheduler.match_cluster_constraints(app1, cluster)
    assert Scheduler.match_cluster_constraints(app2, cluster)
    assert Scheduler.match_cluster_constraints(app3, cluster)


def test_kubernetes_not_match_cluster_label_constraints():
    cluster = ClusterFactory()
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")]
    )

    assert not Scheduler.match_cluster_constraints(app, cluster)


async def test_kubernetes_rank(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(
        make_prometheus({"test_metric_1": ["0.42"], "test_metric_2": ["0.5"]})
    )

    clusters = [
        ClusterFactory(spec__metrics=["test-metric-1"]),
        ClusterFactory(spec__metrics=["test-metric-2"]),
    ]
    metrics = [
        MetricFactory(
            metadata__name="test-metric-1",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_1",
        ),
        MetricFactory(
            metadata__name="test-metric-2",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_2",
        ),
    ]
    metrics_provider = MetricsProviderFactory(
        metadata__name="test-prometheus",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    for metric in metrics:
        await db.put(metric)

    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked_clusters = await scheduler.rank_kubernetes_clusters(clusters)

    for ranked, cluster in zip(ranked_clusters, clusters):
        assert ranked.rank is not None
        assert ranked.cluster == cluster


async def test_kubernetes_rank_with_metrics_only():
    clusters = [ClusterFactory(spec__metrics=[]), ClusterFactory(spec__metrics=[])]

    with pytest.raises(AssertionError):
        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        # need to be called explicitly
        await scheduler.rank_kubernetes_clusters(clusters)


async def test_kubernetes_rank_missing_metric(aiohttp_server, config, loop):
    clusters = [
        ClusterFactory(spec__metrics=["non-existent-metric"]),
        ClusterFactory(spec__metrics=["also-not-existing"]),
    ]

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked = await scheduler.rank_kubernetes_clusters(clusters)

    assert len(ranked) == 0


async def test_kubernetes_rank_missing_metrics_provider(
    aiohttp_server, config, db, loop
):
    clusters = [ClusterFactory(spec__metrics=["my-metric"])]
    metric = MetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
        spec__weight=1,
        spec__provider__name="non-existent-provider",
        spec__provider__metric="non-existent-metric",
    )
    await db.put(metric)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked = await scheduler.rank_kubernetes_clusters(clusters)

    assert len(ranked) == 0


async def test_kubernetes_rank_failing_metrics_provider(
    aiohttp_server, config, db, loop
):
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    clusters = [ClusterFactory(spec__metrics=["my-metric"])]
    metric = MetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
        spec__weight=1,
        spec__provider__name="my-provider",
        spec__provider__metric="my-metric",
    )
    provider = MetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    await db.put(metric)
    await db.put(provider)

    api = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(api), worker_count=0)
        await scheduler.prepare(client)
        ranked = await scheduler.rank_kubernetes_clusters(clusters)

    assert len(ranked) == 0


async def test_kubernetes_prefer_cluster_with_metrics(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": ["0.4"]}))

    cluster_miss = ClusterFactory(spec__metrics=[])
    cluster = ClusterFactory(spec__metrics=["heat-demand"])
    metric = MetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__weight=0.9,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="my_metric",
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    app = ApplicationFactory(spec__constraints=None)
    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.select_kubernetes_cluster(
            app, (cluster_miss, cluster)
        )

    assert selected == cluster


async def test_kubernetes_select_cluster_without_metric(aiohttp_server, config, loop):
    clusters = (ClusterFactory(spec__metrics=[]), ClusterFactory(spec__metrics=[]))
    app = ApplicationFactory(spec__constraints=None)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    selected = await scheduler.select_kubernetes_cluster(app, clusters)
    assert selected in clusters


async def test_kubernetes_scheduling(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"heat_demand_zone_1": ["0.25"]}))

    cluster = ClusterFactory(spec__metrics=["heat-demand"])
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric = MetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__weight=0.9,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat_demand_zone_1",
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=f"http://{prometheus.host}:{prometheus.port}",
    )
    await db.put(metric)
    await db.put(metrics_provider)
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.resource_received(app)

        stored = await db.get(Application, namespace="testing", name=app.metadata.name)

        assert stored.status.scheduled_to == resource_ref(cluster)
        assert stored.status.scheduled

        assert app.metadata.uid in scheduler.queue.timers, "Application is rescheduled"


async def test_kubernetes_scheduling_error(aiohttp_server, config, db, loop):
    app = ApplicationFactory(
        status__state=ApplicationState.RUNNING, status__is_scheduled=False
    )

    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.queue.put(app.metadata.uid, app)
        await scheduler.handle_resource(run_once=True)

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.reason.code == ReasonCode.NO_SUITABLE_RESOURCE


async def test_kubernetes_migration(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(
        make_prometheus(
            {"heat_demand_1": ("0.25", "0.5"), "heat_demand_2": ("0.5", "0.25")}
        )
    )

    cluster1 = ClusterFactory(spec__metrics=["heat-demand-1"])
    cluster2 = ClusterFactory(spec__metrics=["heat-demand-2"])
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = MetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__weight=1.0,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = MetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__weight=1.0,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus",
        spec__type="prometheus",
        spec__prometheus__url=f"http://{prometheus.host}:{prometheus.port}",
    )
    await db.put(metric1)
    await db.put(metric2)
    await db.put(metrics_provider)
    await db.put(cluster1)
    await db.put(cluster2)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.resource_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING

        # Schedule a second time the scheduled resource
        await scheduler.resource_received(stored1)

        stored2 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored2.status.scheduled_to == resource_ref(cluster2)
        assert stored2.status.state == ApplicationState.PENDING
        assert stored2.status.scheduled > stored1.status.scheduled
