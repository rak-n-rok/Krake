import asyncio

import pytest

from krake.api.app import create_app
from krake.data.core import ReasonCode, MetricProviderType
from krake.data.kubernetes import Application, ApplicationState
from krake.controller import Worker
from krake.controller.scheduler.__main__ import Scheduler, SchedulerWorker
from krake.client import Client
from krake.test_utils import server_endpoint
from tests.factories.core import MetricsProviderFactory
from tests.factories.kubernetes import (
    ApplicationFactory,
    AnnotationFactory,
    ClusterFactory,
)
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
        worker_factory=lambda client, config_defaults: worker,
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


async def test_kubernetes_match_constraints(aiohttp_server, config, db, loop):
    annotation_it = AnnotationFactory(name="location", value="IT")
    annotation_de = AnnotationFactory(name="location", value="DE")
    cluster = ClusterFactory(spec__annotations=[annotation_it, annotation_de])
    app = ApplicationFactory(spec__constraints__annotations=[annotation_it])

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        assert worker.match_constraints(app, cluster)


async def test_kubernetes_match_constraints_empty(aiohttp_server, config, db, loop):
    cluster = ClusterFactory(spec__annotations=[])
    app = ApplicationFactory(spec__constraints__annotations=[])

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        assert worker.match_constraints(app, cluster)


async def test_kubernetes_match_constraints_negative(aiohttp_server, config, db, loop):
    annotation_it = AnnotationFactory(name="location", value="IT")
    cluster = ClusterFactory()
    app = ApplicationFactory(spec__constraints__annotations=[annotation_it])

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        assert not worker.match_constraints(app, cluster)


@pytest.mark.require_module("prometheus_client")
@pytest.mark.slow
async def test_kubernetes_rank(prometheus, aiohttp_server, config, db, loop):
    clusters = [
        ClusterFactory(spec__metrics=["heat_demand_zone_1"]),
        ClusterFactory(spec__metrics=["heat_demand_zone_1"]),
    ]
    prometheus_host, prometheus_port = prometheus
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type=MetricProviderType.prometheus,
        spec__config={
            "url": f"http://{prometheus_host}:{prometheus_port}/api/v1/query",
            "metrics": ["heat-demand"],
        },
    )
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client, config_defaults=config)
        ranked_clusters = await worker.rank_kubernetes_clusters(clusters)

    for ranked, cluster in zip(ranked_clusters, clusters):
        assert ranked.rank is not None
        assert ranked.cluster == cluster


@pytest.mark.require_module("prometheus_client")
@pytest.mark.slow
async def test_kubernetes_rank_missing_metric_definition(
    prometheus, aiohttp_server, config, db, loop
):
    cluster_miss = ClusterFactory()
    cluster = ClusterFactory(spec__metrics=["heat_demand_zone_1"])
    prometheus_host, prometheus_port = prometheus
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type=MetricProviderType.prometheus,
        spec__config={
            "url": f"http://{prometheus_host}:{prometheus_port}/api/v1/query",
            "metrics": ["heat-demand"],
        },
    )
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client, config_defaults=config)
        ranked_clusters = await worker.rank_kubernetes_clusters([cluster, cluster_miss])

    assert len(ranked_clusters) == 1
    assert ranked_clusters[0].rank is not None
    assert ranked_clusters[0].cluster == cluster


@pytest.mark.require_module("prometheus_client")
@pytest.mark.slow
async def test_kubernetes_scheduler(prometheus, aiohttp_server, config, db, loop):
    cluster = ClusterFactory(spec__annotations=[], spec__metrics=["heat_demand_zone_1"])
    app = ApplicationFactory(
        spec__constraints__annotations=[], status__state=ApplicationState.PENDING
    )
    prometheus_host, prometheus_port = prometheus
    metrics_provider = MetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type=MetricProviderType.prometheus,
        spec__config={
            "url": f"http://{prometheus_host}:{prometheus_port}/api/v1/query",
            "metrics": ["heat-demand"],
        },
    )
    await db.put(metrics_provider)
    await db.put(cluster)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client, config_defaults=config)
        await worker.resource_received(app)

    stored, _ = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.cluster.name == cluster.metadata.name
    assert stored.status.state == ApplicationState.SCHEDULED


async def test_kubernetes_scheduling_error_handling(aiohttp_server, config, db, loop):
    app = ApplicationFactory(status__state=ApplicationState.PENDING)

    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        worker = SchedulerWorker(client=client)
        await worker.resource_received(app)
