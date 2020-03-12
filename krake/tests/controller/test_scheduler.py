import pytest
import pytz
import random
from aiohttp import web, ClientSession, ClientConnectorError, ClientResponseError
from copy import deepcopy
from datetime import datetime

from krake.api.app import create_app
from krake.data.core import ResourceRef, MetricRef
from krake.data.constraints import LabelConstraint
from krake.data.kubernetes import Application, ApplicationState
from krake.data.openstack import MagnumCluster, MagnumClusterState
from krake.controller.scheduler import Scheduler, metrics
from krake.controller.scheduler.constraints import match_cluster_constraints

from krake.client import Client
from krake.data.core import resource_ref, ReasonCode
from krake.test_utils import server_endpoint, make_prometheus

from factories.core import MetricsProviderFactory, MetricFactory
from factories.kubernetes import ApplicationFactory, ClusterFactory
from factories.openstack import MagnumClusterFactory, ProjectFactory
from factories import fake


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
    failed = ApplicationFactory(
        status__state=ApplicationState.FAILED, status__is_scheduled=False
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
    await db.put(failed)
    await db.put(deleted)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await scheduler.prepare(client)  # need to be called explicitly
        await scheduler.kubernetes_reflector.list_resource()

    assert scheduled.metadata.uid not in scheduler.queue.dirty
    assert updated.metadata.uid in scheduler.queue.dirty
    assert pending.metadata.uid in scheduler.queue.dirty
    assert failed.metadata.uid not in scheduler.queue.dirty
    assert deleted.metadata.uid not in scheduler.queue.dirty

    assert scheduled.metadata.uid in scheduler.queue.timers
    assert deleted.metadata.uid not in scheduler.queue.timers


async def test_openstack_reception(aiohttp_server, config, db, loop):
    """Test that the reflector present on the Scheduler actually put the right
    received Applications into the work queue.
    """
    pending = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)
    scheduled = MagnumClusterFactory(
        status__state=MagnumClusterState.PENDING,
        status__project=ResourceRef(
            api="openstack", kind="Project", namespace="testing", name="test-project"
        ),
    )
    running = MagnumClusterFactory(status__state=MagnumClusterState.RUNNING)
    deleted = MagnumClusterFactory(
        metadata__deleted=datetime.now(), status__state=MagnumClusterState.RUNNING
    )

    assert pending.status.project is None
    assert scheduled.status.project is not None

    server = await aiohttp_server(create_app(config))

    await db.put(pending)
    await db.put(scheduled)
    await db.put(running)
    await db.put(deleted)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.openstack_reflector.list_resource()

    assert pending.metadata.uid in scheduler.magnum_queue.dirty
    assert scheduled.metadata.uid not in scheduler.magnum_queue.dirty
    assert running.metadata.uid not in scheduler.magnum_queue.dirty
    assert deleted.metadata.uid not in scheduler.magnum_queue.dirty


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


def test_kubernetes_match_cluster_label_constraints():
    cluster = ClusterFactory(metadata__labels={"location": "IT"})
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__custom_resources=[],
    )
    assert match_cluster_constraints(app, cluster)


def test_kubernetes_not_match_cluster_label_constraints():
    cluster = ClusterFactory()
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__custom_resources=[],
    )

    assert not match_cluster_constraints(app, cluster)


def test_kubernetes_match_cluster_custom_resources_constraints():
    cluster = ClusterFactory(spec__custom_resources=["crontabs.stable.example.com"])
    app = ApplicationFactory(
        spec__constraints__cluster__custom_resources=["crontabs.stable.example.com"],
        spec__constraints__cluster__labels=[],
    )

    assert match_cluster_constraints(app, cluster)


def test_kubernetes_not_match_cluster_custom_resources_constraints():
    cluster = ClusterFactory()
    app = ApplicationFactory(
        spec__constraints__cluster__custom_resources=["crontabs.stable.example.com"],
        spec__constraints__cluster__labels=[],
    )

    assert not match_cluster_constraints(app, cluster)


def test_kubernetes_match_empty_cluster_constraints():
    cluster = ClusterFactory()
    app1 = ApplicationFactory(spec__constraints=None)
    app2 = ApplicationFactory(spec__constraints__cluster=None)
    app3 = ApplicationFactory(
        spec__constraints__cluster__labels=None,
        spec__constraints__cluster__custom_resources=None,
    )

    assert match_cluster_constraints(app1, cluster)
    assert match_cluster_constraints(app2, cluster)
    assert match_cluster_constraints(app3, cluster)


async def test_kubernetes_rank(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"test_metric_1": ["0.42"]}))

    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(spec__metrics=[MetricRef(name="test-metric-1", weight=1.0)]),
        ClusterFactory(spec__metrics=[MetricRef(name="test-metric-2", weight=1.0)]),
    ]
    metrics = [
        MetricFactory(
            metadata__name="test-metric-1",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_1",
        ),
        MetricFactory(
            metadata__name="test-metric-2",
            spec__provider__name="test-static",
            spec__provider__metric="test_metric_2",
        ),
    ]
    prometheus_provider = MetricsProviderFactory(
        metadata__name="test-prometheus",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    static_provider = MetricsProviderFactory(
        metadata__name="test-static",
        spec__type="static",
        spec__static__metrics={"test_metric_2": 0.5},
    )

    for metric in metrics:
        await db.put(metric)

    await db.put(prometheus_provider)
    await db.put(static_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked_clusters = await scheduler.rank_kubernetes_clusters(app, clusters)

    for ranked, cluster in zip(ranked_clusters, clusters):
        assert ranked.rank is not None
        assert ranked.cluster == cluster


async def test_kubernetes_rank_sticky(aiohttp_server, config, db, loop):
    cluster_A = ClusterFactory(
        metadata__name="A", spec__metrics=[MetricRef(name="metric-1", weight=1.0)]
    )
    cluster_B = ClusterFactory(
        metadata__name="B", spec__metrics=[MetricRef(name="metric-1", weight=1.0)]
    )

    scheduled_app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=resource_ref(cluster_A),
    )
    pending_app = ApplicationFactory(status__state=ApplicationState.PENDING)

    static_provider = MetricsProviderFactory(
        metadata__name="static-provider",
        spec__type="static",
        spec__static__metrics={"my_metric": 0.75},
    )
    metric = MetricFactory(
        metadata__name="metric-1",
        spec__provider__name="static-provider",
        spec__provider__metric="my_metric",
    )

    await db.put(metric)
    await db.put(static_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)

        ranked = await scheduler.rank_kubernetes_clusters(
            pending_app, [cluster_A, cluster_B]
        )
        assert ranked[0].rank == 0.75
        assert ranked[1].rank == 0.75

        # Rank clusters where application is already scheduled to one of the
        # clusters, hence a stickiness metric should be added to the rank of
        # cluster "A".
        ranked = await scheduler.rank_kubernetes_clusters(
            scheduled_app, [cluster_A, cluster_B]
        )

        assert ranked[0].rank == pytest.approx(0.75 / 1.1 + 0.1 / 1.1)
        assert ranked[1].rank == 0.75
        assert ranked[0].rank > ranked[1].rank

        assert ranked[0].cluster == cluster_A
        assert ranked[1].cluster == cluster_B


async def test_kubernetes_rank_with_metrics_only():
    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [ClusterFactory(spec__metrics=[]), ClusterFactory(spec__metrics=[])]

    with pytest.raises(AssertionError):
        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        await scheduler.rank_kubernetes_clusters(app, clusters)


async def test_kubernetes_rank_missing_metric(aiohttp_server, config, loop):
    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(spec__metrics=[MetricRef(name="non-existent-metric", weight=1)]),
        ClusterFactory(spec__metrics=[MetricRef(name="also-not-existing", weight=1)]),
    ]

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked = await scheduler.rank_kubernetes_clusters(app, clusters)

    assert len(ranked) == 0


async def test_kubernetes_rank_missing_metrics_provider(
    aiohttp_server, config, db, loop
):
    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [ClusterFactory(spec__metrics=[MetricRef(name="my-metric", weight=1)])]
    metric = MetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
        spec__provider__name="non-existent-provider",
        spec__provider__metric="non-existent-metric",
    )
    await db.put(metric)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked = await scheduler.rank_kubernetes_clusters(app, clusters)

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

    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [ClusterFactory(spec__metrics=[MetricRef(name="my-metric", weight=1)])]
    metric = MetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
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
        ranked = await scheduler.rank_kubernetes_clusters(app, clusters)

    assert len(ranked) == 0


async def test_kubernetes_prefer_cluster_with_metrics(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": ["0.4"]}))

    cluster_miss = ClusterFactory(spec__metrics=[])
    cluster = ClusterFactory(spec__metrics=[MetricRef(name="heat-demand", weight=1)])
    metric = MetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="my_metric",
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
        spec__constraints=None,
    )
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


async def test_kubernetes_select_cluster_without_metric():
    clusters = (ClusterFactory(spec__metrics=[]), ClusterFactory(spec__metrics=[]))
    app = ApplicationFactory(spec__constraints=None)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    selected = await scheduler.select_kubernetes_cluster(app, clusters)
    assert selected in clusters


async def test_kubernetes_select_cluster_not_deleted():
    # As the finally selected cluster is chosen randomly, perform the test several times
    # to ensure that the cluster has really been chosen the right way, not by chance.
    for _ in range(10):
        index = random.randint(0, 9)
        clusters = [
            ClusterFactory(metadata__deleted=datetime.now(), spec__metrics=[])
            for _ in range(10)
        ]
        clusters[index].metadata.deleted = None

        app = ApplicationFactory(spec__constraints=None)

        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        selected = await scheduler.select_kubernetes_cluster(app, clusters)

        assert selected == clusters[index]


async def test_kubernetes_select_cluster_with_constraints_without_metric():
    # Because the selection of clusters is done randomly between the matching clusters,
    # if an error was present, the right cluster could have been randomly picked,
    # and the test would pass even if it should not.
    # Thus many cluster that should not match are created, which reduces the chances
    # that the expected cluster is chosen, even in case of failures.
    countries = ["IT"] + fake.words(99)
    clusters = [
        ClusterFactory(spec__metrics=[], metadata__labels={"location": country})
        for country in countries
    ]

    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__custom_resources=[],
    )

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    selected = await scheduler.select_kubernetes_cluster(app, clusters)
    assert selected == clusters[0]


async def test_kubernetes_select_cluster_sticky_without_metric():
    cluster_A = ClusterFactory(spec__metrics=[])
    cluster_B = ClusterFactory(spec__metrics=[])
    app = ApplicationFactory(
        spec__constraints=None, status__scheduled_to=resource_ref(cluster_A)
    )

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    selected = await scheduler.select_kubernetes_cluster(app, (cluster_A, cluster_B))
    assert selected == cluster_A


async def test_kubernetes_scheduling(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"heat_demand_zone_1": ["0.25"]}))

    cluster = ClusterFactory(spec__metrics=[MetricRef(name="heat-demand", weight=1)])
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric = MetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
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
        await scheduler.kubernetes_application_received(app)

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
        await scheduler.handle_kubernetes_applications(run_once=True)

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.reason.code == ReasonCode.NO_SUITABLE_RESOURCE


async def test_kubernetes_migration(aiohttp_server, config, db, loop):
    utc = pytz.UTC

    prometheus = await aiohttp_server(
        make_prometheus(
            {"heat_demand_1": ("0.5", "0.25"), "heat_demand_2": ("0.25", "0.5")}
        )
    )

    cluster1 = ClusterFactory(spec__metrics=[MetricRef(name="heat-demand-1", weight=1)])
    cluster2 = ClusterFactory(spec__metrics=[MetricRef(name="heat-demand-2", weight=1)])
    app = ApplicationFactory(
        metadata__modified=utc.localize(datetime.now()),
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = MetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = MetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
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
        await scheduler.kubernetes_application_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING
        assert stored1.metadata.modified <= utc.localize(stored1.status.scheduled)

        # Schedule a second time the scheduled resource
        await scheduler.kubernetes_application_received(stored1)

        stored2 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored2.status.scheduled_to == resource_ref(cluster2)
        assert stored2.status.state == ApplicationState.PENDING
        assert stored2.status.scheduled > stored1.status.scheduled
        assert stored2.metadata.modified <= utc.localize(stored2.status.scheduled)


async def test_kubernetes_application_update(aiohttp_server, config, db, loop):
    # Schedule the application, then handle the application again (could be in the case
    # of an update of the Application). As the metrics did not change, the cluster
    # scheduled should be the same, but the scheduled timestamp should be updated to
    # allow the KubernetesController to handle the Application afterwards.
    utc = pytz.UTC

    prometheus = await aiohttp_server(
        make_prometheus(
            {"heat_demand_1": ("0.5", "0.5"), "heat_demand_2": ("0.25", "0.25")}
        )
    )

    cluster1 = ClusterFactory(spec__metrics=[MetricRef(name="heat-demand-1", weight=1)])
    cluster2 = ClusterFactory(spec__metrics=[MetricRef(name="heat-demand-2", weight=1)])
    app = ApplicationFactory(
        metadata__modified=utc.localize(datetime.now()),
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = MetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = MetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
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
        await scheduler.kubernetes_application_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING
        assert stored1.metadata.modified <= utc.localize(stored1.status.scheduled)

        # Schedule a second time the scheduled resource
        updated_app = deepcopy(stored1)
        await scheduler.kubernetes_application_received(updated_app)

        stored2 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored2.status.scheduled_to == resource_ref(cluster1)
        assert stored2.status.state == ApplicationState.PENDING
        # Even if the scheduled cluster did not change, the timestamp should be updated
        assert stored2.status.scheduled > stored1.status.scheduled
        assert stored2.metadata.modified <= utc.localize(stored2.status.scheduled)


def test_openstack_match_project_label_constraints():
    project = ProjectFactory(metadata__labels={"location": "IT"})
    cluster = MagnumClusterFactory(
        spec__constraints__project__labels=[LabelConstraint.parse("location is IT")]
    )
    assert Scheduler.match_project_constraints(cluster, project)


def test_openstack_match_empty_project_label_constraints():
    project = ProjectFactory(metadata__labels=[])
    cluster1 = MagnumClusterFactory(spec__constraints=None)
    cluster2 = MagnumClusterFactory(spec__constraints__project=None)
    cluster3 = MagnumClusterFactory(spec__constraints__project__labels=None)

    assert Scheduler.match_project_constraints(cluster1, project)
    assert Scheduler.match_project_constraints(cluster2, project)
    assert Scheduler.match_project_constraints(cluster3, project)


def test_openstack_not_match_project_label_constraints():
    project = ProjectFactory()
    cluster = MagnumClusterFactory(
        spec__constraints__project__labels=[LabelConstraint.parse("location is IT")]
    )

    assert not Scheduler.match_project_constraints(cluster, project)


async def test_openstack_rank(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"test_metric_1": ["0.42"]}))

    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [
        ProjectFactory(spec__metrics=[MetricRef(name="test-metric-1", weight=1.0)]),
        ProjectFactory(spec__metrics=[MetricRef(name="test-metric-2", weight=1.0)]),
    ]
    metrics = [
        MetricFactory(
            metadata__name="test-metric-1",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_1",
        ),
        MetricFactory(
            metadata__name="test-metric-2",
            spec__provider__name="test-static",
            spec__provider__metric="test_metric_2",
        ),
    ]
    prometheus_provider = MetricsProviderFactory(
        metadata__name="test-prometheus",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    static_provider = MetricsProviderFactory(
        metadata__name="test-static",
        spec__type="static",
        spec__static__metrics={"test_metric_2": 0.5},
    )

    for metric in metrics:
        await db.put(metric)

    await db.put(prometheus_provider)
    await db.put(static_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked_projects = await scheduler.rank_openstack_projects(cluster, projects)

    for ranked, project in zip(ranked_projects, projects):
        assert ranked.rank is not None
        assert ranked.project == project


async def test_openstack_rank_with_metrics_only():
    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [ProjectFactory(spec__metrics=[]), ProjectFactory(spec__metrics=[])]

    with pytest.raises(AssertionError):
        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        await scheduler.rank_openstack_projects(cluster, projects)


async def test_openstack_rank_missing_metric(aiohttp_server, config, loop):
    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [
        ProjectFactory(spec__metrics=[MetricRef(name="non-existent-metric", weight=1)]),
        ProjectFactory(spec__metrics=[MetricRef(name="also-not-existing", weight=1)]),
    ]

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked = await scheduler.rank_openstack_projects(cluster, projects)

    assert len(ranked) == 0


async def test_openstack_rank_missing_metrics_provider(
    aiohttp_server, config, db, loop
):
    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [ProjectFactory(spec__metrics=[MetricRef(name="my-metric", weight=1)])]
    metric = MetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
        spec__provider__name="non-existent-provider",
        spec__provider__metric="non-existent-metric",
    )
    await db.put(metric)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        ranked = await scheduler.rank_openstack_projects(cluster, projects)

    assert len(ranked) == 0


async def test_openstack_rank_failing_metrics_provider(
    aiohttp_server, config, db, loop
):
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [ProjectFactory(spec__metrics=[MetricRef(name="my-metric", weight=1)])]
    metric = MetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
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
        ranked = await scheduler.rank_openstack_projects(cluster, projects)

    assert len(ranked) == 0


async def test_prefer_projects_with_metrics(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": ["0.4"]}))

    project_miss = ProjectFactory(spec__metrics=[])
    project = ProjectFactory(spec__metrics=[MetricRef(name="heat-demand", weight=1)])
    metric = MetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="my_metric",
    )
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    cluster = MagnumClusterFactory(
        status__state=MagnumClusterState.PENDING,
        status__is_scheduled=False,
        spec__constraints=None,
    )
    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.select_openstack_project(
            cluster, (project_miss, project)
        )

    assert selected == project


async def test_select_project_without_metric():
    projects = (ProjectFactory(spec__metrics=[]), ProjectFactory(spec__metrics=[]))
    cluster = MagnumClusterFactory(spec__constraints=None)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    selected = await scheduler.select_openstack_project(cluster, projects)
    assert selected in projects


async def test_select_project_not_deleted():
    # As the finally selected project is chosen randomly, perform the test several times
    # to ensure that the project has really been chosen the right way, not by chance.
    for _ in range(10):
        index = random.randint(0, 9)
        projects = [
            ProjectFactory(metadata__deleted=datetime.now(), spec__metrics=[])
            for _ in range(10)
        ]
        projects[index].metadata.deleted = None

        cluster = MagnumClusterFactory(spec__constraints=None)

        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        selected = await scheduler.select_openstack_project(cluster, projects)

        assert selected == projects[index]


async def test_select_project_with_constraints_without_metric():
    # Because the selection of projects is done randomly between the matching projects,
    # if an error was present, the right project could have been randomly picked,
    # and the test would pass even if it should not.
    # Thus many project that should not match are created, which reduces the chances
    # that the expected project is chosen, even in case of failures.
    countries = ["IT"] + fake.words(99)
    projects = [
        ProjectFactory(spec__metrics=[], metadata__labels={"location": country})
        for country in countries
    ]

    cluster = MagnumClusterFactory(
        spec__constraints__project__labels=[LabelConstraint.parse("location is IT")]
    )

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    selected = await scheduler.select_openstack_project(cluster, projects)
    assert selected == projects[0]


async def test_openstack_scheduling(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"heat_demand_zone_1": ["0.25"]}))

    project = ProjectFactory(spec__metrics=[MetricRef(name="heat-demand", weight=1)])
    cluster = MagnumClusterFactory(
        spec__constraints__project__labels=[],
        status__state=MagnumClusterState.PENDING,
        status__is_scheduled=False,
    )
    metric = MetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
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
    await db.put(project)
    await db.put(cluster)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.schedule_magnum_cluster(cluster)

        stored = await db.get(
            MagnumCluster,
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
        )
        assert stored.status.project == resource_ref(project)
        assert resource_ref(project) in stored.metadata.owners
        assert stored.status.template == project.spec.template


async def test_openstack_scheduling_error(aiohttp_server, config, db, loop):
    cluster = MagnumClusterFactory(
        status__state=MagnumClusterState.RUNNING, status__is_scheduled=False
    )

    await db.put(cluster)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.magnum_queue.put(cluster.metadata.uid, cluster)
        await scheduler.handle_magnum_clusters(run_once=True)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.reason.code == ReasonCode.NO_SUITABLE_RESOURCE
