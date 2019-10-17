import asyncio
import pytest

from krake.api.app import create_app
from krake.data.kubernetes import Application, ApplicationState, LabelConstraint
from krake.controller.scheduler import Scheduler, SchedulerWorker
from krake.client import Client
from krake.test_utils import server_endpoint
from factories.core import MetricsProviderFactory, MetricFactory
from factories.kubernetes import ApplicationFactory, ClusterFactory
from . import SimpleWorker


async def test_kubernetes_reception(aiohttp_server, config, db, loop):
    scheduled = ApplicationFactory(status__state=ApplicationState.SCHEDULED)
    updated = ApplicationFactory(status__state=ApplicationState.UPDATED)
    pending = ApplicationFactory(status__state=ApplicationState.PENDING)

    # Only PENDING and UPDATED applications are expected
    worker = SimpleWorker(
        expected={pending.metadata.uid, updated.metadata.uid}, loop=loop
    )
    server = await aiohttp_server(create_app(config))

    async with Scheduler(
        api_endpoint=server_endpoint(server),
        worker_factory=lambda client: worker,
        worker_count=1,
        loop=loop,
    ) as scheduler:

        await db.put(scheduled)
        await db.put(updated)
        await db.put(pending)

        # There could be an error in the scheduler or the worker. Hence, we
        # wait for both.
        await asyncio.wait(
            [scheduler, worker.done], timeout=1, return_when=asyncio.FIRST_COMPLETED
        )

    assert worker.done.done()
    await worker.done  # If there is any exception, retrieve it here


def test_kubernetes_match_cluster_label_constraints():
    cluster = ClusterFactory(metadata__labels={"location": "IT"})
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")]
    )

    assert SchedulerWorker.match_cluster_constraints(app, cluster)


def test_kubernetes_match_empty_cluster_label_constraints():
    cluster = ClusterFactory(metadata__labels=[])
    app1 = ApplicationFactory(spec__constraints=None)
    app2 = ApplicationFactory(spec__constraints__cluster=None)
    app3 = ApplicationFactory(spec__constraints__cluster__labels=None)

    assert SchedulerWorker.match_cluster_constraints(app1, cluster)
    assert SchedulerWorker.match_cluster_constraints(app2, cluster)
    assert SchedulerWorker.match_cluster_constraints(app3, cluster)


def test_kubernetes_not_match_cluster_label_constraints():
    cluster = ClusterFactory()
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")]
    )

    assert not SchedulerWorker.match_cluster_constraints(app, cluster)


@pytest.mark.slow
async def test_kubernetes_rank(prometheus, aiohttp_server, config, db, loop):
    clusters = [
        ClusterFactory(spec__metrics=["heat-demand"]),
        ClusterFactory(spec__metrics=["heat-demand"]),
    ]
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=f"http://{prometheus.host}:{prometheus.port}",
    )
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        ranked_clusters = await worker.rank_kubernetes_clusters(clusters)

    for ranked, cluster in zip(ranked_clusters, clusters):
        assert ranked.rank is not None
        assert ranked.cluster == cluster


async def test_kubernetes_rank_with_metrics_only():
    clusters = [ClusterFactory(spec__metrics=[]), ClusterFactory(spec__metrics=[])]

    with pytest.raises(AssertionError):
        await SchedulerWorker(client=None).rank_kubernetes_clusters(clusters)


async def test_kubernetes_rank_missing_metric(aiohttp_server, config, loop):
    clusters = [
        ClusterFactory(spec__metrics=["non-existent-metric"]),
        ClusterFactory(spec__metrics=["also-not-existing"]),
    ]

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        ranked = await SchedulerWorker(client=client).rank_kubernetes_clusters(clusters)

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
        ranked = await SchedulerWorker(client=client).rank_kubernetes_clusters(clusters)

    assert len(ranked) == 0


@pytest.mark.slow
async def test_kubernetes_prefer_cluster_with_metrics(
    prometheus, aiohttp_server, config, db, loop
):
    cluster_miss = ClusterFactory(spec__metrics=[])
    cluster = ClusterFactory(spec__metrics=["heat-demand"])
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
    app = ApplicationFactory(spec__constraints=None)
    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        selected = await worker.select_kubernetes_cluster(app, (cluster_miss, cluster))

    assert selected == cluster


async def test_kubernetes_select_cluster_without_metric(aiohttp_server, config, loop):
    clusters = (ClusterFactory(spec__metrics=[]), ClusterFactory(spec__metrics=[]))
    app = ApplicationFactory(spec__constraints=None)

    selected = await SchedulerWorker(client=None).select_kubernetes_cluster(
        app, clusters
    )
    assert selected in clusters


@pytest.mark.slow
async def test_kubernetes_scheduling(prometheus, aiohttp_server, config, db, loop):
    cluster = ClusterFactory(metadata__labels={}, spec__metrics=["heat-demand"])
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[], status__state=ApplicationState.PENDING
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
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.cluster.name == cluster.metadata.name
    assert stored.status.state == ApplicationState.SCHEDULED


async def test_kubernetes_scheduling_error_handling(aiohttp_server, config, db, loop):
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)
