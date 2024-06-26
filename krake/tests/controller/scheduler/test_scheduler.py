import asyncio
import multiprocessing

import sys
import pytest
import random
import time
from asyncio.subprocess import PIPE, STDOUT
from aiohttp import web
from copy import deepcopy
from datetime import datetime, timezone, timedelta

from krake.api.app import create_app
from krake.client import Client
from krake.client.kubernetes import KubernetesApi
from krake.controller.scheduler import Scheduler
from krake.controller.scheduler.metrics import QueryResult
from krake.controller.scheduler.__main__ import main
from krake.controller.scheduler.constraints import (
    match_application_constraints,
    match_project_constraints,
    match_cluster_constraints,
)
from krake.controller.scheduler.scheduler import NoProjectFound, NoClusterFound
from krake.data.constraints import LabelConstraint, MetricConstraint
from krake.data.core import ResourceRef, MetricRef
from krake.data.core import resource_ref, ReasonCode
from krake.data.infrastructure import CloudState
from krake.data.kubernetes import Application, ApplicationState, Cluster, ClusterState
from krake.data.openstack import (
    MagnumCluster,
    MagnumClusterState,
    ProjectState,
    Project,
)
from krake.test_utils import server_endpoint, make_prometheus, with_timeout

from tests.factories import fake
from tests.factories.core import (
    GlobalMetricsProviderFactory,
    MetricsProviderFactory,
    GlobalMetricFactory,
    MetricFactory,
)
from tests.factories.infrastructure import CloudFactory, GlobalCloudFactory
from tests.factories.kubernetes import ApplicationFactory, ClusterFactory
from tests.factories.openstack import MagnumClusterFactory, ProjectFactory


TOSCA_CLUSTER_MINIMAL = {
    "tosca_definitions_version": "tosca_simple_yaml_1_0",
    "topology_template": {"outputs": {"kubeconfig": {"value": "test"}}},
}


@with_timeout(3)
async def test_main_help(loop):
    """Verify that the help for the Krake Scheduler is displayed, and contains the
    elements added by the argparse formatters (default value and expected types of the
    parameters).
    """
    command = "python -m krake.controller.scheduler -h"
    # The loop parameter is mandatory otherwise the test fails if started with others.
    process = await asyncio.create_subprocess_exec(
        *command.split(" "), stdout=PIPE, stderr=STDOUT
    )
    stdout, _ = await process.communicate()
    output = stdout.decode()

    to_check = [
        "Krake scheduler",
        "usage:",
        "default:",  # Present if the default value of the arguments are displayed
        "str",  # Present if the type of the arguments are displayed
        "int",
    ]

    # Because python3.10 argparse version changed 'optional arguments:' to 'options:'
    if sys.version_info < (3, 10):
        to_check.append("optional arguments:")
    else:
        to_check.append("options:")

    for expression in to_check:
        assert expression in output


@pytest.mark.slow
def test_main(scheduler_config, log_to_file_config):
    """Test the main function of the Scheduler, and verify that it starts, display the
    right output and stops without issue.
    """
    log_config, file_path = log_to_file_config()

    scheduler_config.api_endpoint = "http://my-krake-api:1234"
    scheduler_config.log = log_config

    def wrapper(configuration):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        main(configuration)

    # Start the process and let it time to initialize
    process = multiprocessing.Process(target=wrapper, args=(scheduler_config,))
    process.start()
    time.sleep(2)

    # Stop and wait for the process to finish
    process.terminate()
    process.join()

    assert not process.is_alive()
    assert process.exitcode == 0

    # Verify the output of the process
    with open(file_path, "r") as f:
        output = f.read()

    assert "Controller started" in output
    assert "Received signal, exiting..." in output
    assert "Controller stopped" in output

    # Verify that all "ERROR" lines in the output are only errors that logs the lack of
    # connectivity to the API.
    attempted_connectivity = False
    for line in output.split("\n"):
        if "ERROR" in output:
            message = (
                f"In line {line!r}, an error occurred which was different from the"
                f" error from connecting to the API."
            )
            assert "Cannot connect to host my-krake-api:1234" in output, message
            attempted_connectivity = True

    assert attempted_connectivity


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
        metadata__deleted=datetime.now(timezone.utc),
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=False,
    )

    assert updated.metadata.modified > updated.status.kube_controller_triggered
    assert updated.metadata.modified > updated.status.scheduled
    assert updated.status.kube_controller_triggered >= updated.status.scheduled

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
        await scheduler.kubernetes_application_reflector.list_resource()

    assert scheduled.metadata.uid not in scheduler.queue.dirty
    assert updated.metadata.uid in scheduler.queue.dirty
    assert pending.metadata.uid in scheduler.queue.dirty
    assert failed.metadata.uid not in scheduler.queue.dirty
    assert deleted.metadata.uid not in scheduler.queue.dirty

    assert scheduled.metadata.uid in scheduler.queue.timers
    assert deleted.metadata.uid not in scheduler.queue.timers


async def test_kubernetes_reception_no_migration(aiohttp_server, config, db, loop):
    # Test that the Reflector present on the Scheduler actually put the
    # received Applications correctly on the WorkQueue, also with migration disabled.
    scheduled = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        spec__constraints__migration=False,
    )
    updated = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=False,
        spec__constraints__migration=False,
    )
    pending = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
        spec__constraints__migration=False,
    )
    failed = ApplicationFactory(
        status__state=ApplicationState.FAILED,
        status__is_scheduled=False,
        spec__constraints__migration=False,
    )
    deleted = ApplicationFactory(
        metadata__deleted=datetime.now(timezone.utc),
        status__state=ApplicationState.RUNNING,
        status__is_scheduled=False,
        spec__constraints__migration=False,
    )

    assert updated.metadata.modified > updated.status.kube_controller_triggered
    assert updated.metadata.modified > updated.status.scheduled
    assert updated.status.kube_controller_triggered >= updated.status.scheduled

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
        await scheduler.kubernetes_application_reflector.list_resource()

    assert scheduled.metadata.uid not in scheduler.queue.dirty
    assert updated.metadata.uid in scheduler.queue.dirty
    assert pending.metadata.uid in scheduler.queue.dirty
    assert failed.metadata.uid not in scheduler.queue.dirty
    assert deleted.metadata.uid not in scheduler.queue.dirty

    assert scheduled.metadata.uid not in scheduler.queue.timers
    assert updated.metadata.uid not in scheduler.queue.timers
    assert pending.metadata.uid not in scheduler.queue.timers
    assert failed.metadata.uid not in scheduler.queue.timers
    assert deleted.metadata.uid not in scheduler.queue.timers


async def test_kubernetes_cluster_reception(aiohttp_server, config, db, loop):
    # Test that the Reflector present on the Scheduler actually put the
    # right received Cluster on the WorkQueue.
    # The following should not be put to the WorkQueue
    scheduled = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=ResourceRef(
            api="infrastructure",
            kind="Cloud",
            name=fake.word(),
            namespace="testing",
        ),
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    registered = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=None,
        # cluster factory adds spec.kubeconfig
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    failed = ClusterFactory(
        status__state=ClusterState.FAILED,
        status__scheduled_to=None,
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    deleted = ClusterFactory(
        status__state=ClusterState.PENDING,
        metadata__deleted=datetime.now(timezone.utc),
        status__scheduled_to=None,
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    # The following should be put to the WorkQueue
    pending = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=None,
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )
    updated = ClusterFactory(
        status__state=ClusterState.ONLINE,
        status__scheduled_to=None,
        spec__kubeconfig={},
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )

    server = await aiohttp_server(create_app(config))

    await db.put(scheduled)
    await db.put(registered)
    await db.put(failed)
    await db.put(deleted)
    await db.put(pending)
    await db.put(updated)

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await scheduler.prepare(client)  # need to be called explicitly
        await scheduler.kubernetes_cluster_reflector.list_resource()

    assert scheduled.metadata.uid not in scheduler.cluster_queue.dirty
    assert registered.metadata.uid not in scheduler.cluster_queue.dirty
    assert failed.metadata.uid not in scheduler.cluster_queue.dirty
    assert deleted.metadata.uid not in scheduler.cluster_queue.dirty
    assert pending.metadata.uid in scheduler.cluster_queue.dirty
    assert updated.metadata.uid in scheduler.cluster_queue.dirty


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
        metadata__deleted=datetime.now(timezone.utc),
        status__state=MagnumClusterState.RUNNING,
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


def test_kubernetes_match_cluster_label_constraints():
    cluster = ClusterFactory(
        metadata__labels={"location": "IT"}, status__state=ClusterState.ONLINE
    )
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
    )
    assert match_application_constraints(app, cluster)


def test_kubernetes_not_match_cluster_label_constraints():
    cluster = ClusterFactory(status__state=ClusterState.ONLINE)
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
    )

    assert not match_application_constraints(app, cluster)


def test_kubernetes_match_cluster_custom_resources_constraints():
    cluster = ClusterFactory(
        spec__custom_resources=["crontabs.stable.example.com"],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        spec__constraints__cluster__custom_resources=["crontabs.stable.example.com"],
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
    )

    assert match_application_constraints(app, cluster)


def test_kubernetes_not_match_cluster_custom_resources_constraints():
    cluster = ClusterFactory(status__state=ClusterState.ONLINE)
    app = ApplicationFactory(
        spec__constraints__cluster__custom_resources=["crontabs.stable.example.com"],
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
    )

    assert not match_application_constraints(app, cluster)


def test_kubernetes_match_cluster_metric_constraints():
    cluster = ClusterFactory(
        spec__metrics=[MetricRef(name="load", weight=6.0, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        spec__constraints__cluster__metrics=[MetricConstraint.parse("load > 5")],
        spec__constraints__cluster__custom_resources=[],
        spec__constraints__cluster__labels=[],
    )
    fetched_metrics = {
        cluster.metadata.name: [
            QueryResult(
                metric=MetricFactory(
                    metadata__name="load",
                    metadata__namespace="system:admin",
                ),
                weight=1.0,
                value=6.0,
            )
        ]
    }

    assert match_application_constraints(app, cluster, fetched_metrics=fetched_metrics)


def test_kubernetes_not_match_cluster_metrics_constraints():
    cluster = ClusterFactory(
        spec__metrics=[MetricRef(name="load", weight=5.0, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        spec__constraints__cluster__metrics=[MetricConstraint.parse("load > 5")],
        spec__constraints__cluster__custom_resources=[],
        spec__constraints__cluster__labels=[],
    )
    fetched_metrics = {
        cluster.metadata.name: [
            QueryResult(
                metric=MetricFactory(
                    metadata__name="load",
                    metadata__namespace="system:admin",
                ),
                weight=1.0,
                value=5.0,
            )
        ]
    }
    assert not match_application_constraints(
        app, cluster, fetched_metrics=fetched_metrics
    )


def test_kubernetes_match_empty_cluster_constraints():
    cluster = ClusterFactory(status__state=ClusterState.ONLINE)
    app1 = ApplicationFactory(spec__constraints=None)
    app2 = ApplicationFactory(spec__constraints__cluster=None)
    app3 = ApplicationFactory(
        spec__constraints__cluster__labels=None,
        spec__constraints__cluster__custom_resources=None,
        spec__constraints__cluster__metrics=None,
    )

    assert match_application_constraints(app1, cluster)
    assert match_application_constraints(app2, cluster)
    assert match_application_constraints(app3, cluster)


async def test_kubernetes_score(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"test_metric_1": ["0.42"]}))
    global_prometheus = await aiohttp_server(
        make_prometheus({"test_metric_1": ["0.42"]})
    )

    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="test-metric-1", weight=1.0, namespaced=False)
            ],
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="test-metric-2", weight=1.0, namespaced=False)
            ],
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="test-metric-1", weight=1.0, namespaced=True)
            ],
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="test-metric-2", weight=1.0, namespaced=True)
            ],
            status__state=ClusterState.ONLINE,
        ),
    ]
    metrics = [
        GlobalMetricFactory(
            metadata__name="test-metric-1",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_1",
        ),
        GlobalMetricFactory(
            metadata__name="test-metric-2",
            spec__provider__name="test-static",
            spec__provider__metric="test_metric_2",
        ),
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
    providers = [
        MetricsProviderFactory(
            metadata__name="test-prometheus",
            spec__type="prometheus",
            spec__prometheus__url=server_endpoint(prometheus),
        ),
        MetricsProviderFactory(
            metadata__name="test-static",
            spec__type="static",
            spec__static__metrics={"test_metric_2": 0.5},
        ),
        GlobalMetricsProviderFactory(
            metadata__name="test-prometheus",
            spec__type="prometheus",
            spec__prometheus__url=server_endpoint(global_prometheus),
        ),
        GlobalMetricsProviderFactory(
            metadata__name="test-static",
            spec__type="static",
            spec__static__metrics={"test_metric_2": 0.5},
        ),
    ]

    for metric in metrics:
        await db.put(metric)

    for provider in providers:
        await db.put(provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        clusters_scores = (
            await scheduler.kubernetes_application.rank_kubernetes_clusters(
                app, clusters
            )
        )

    for ranked, cluster in zip(clusters_scores, clusters):
        assert ranked.score is not None
        assert ranked.cluster == cluster


async def test_kubernetes_score_sticky(aiohttp_server, config, db, loop):
    cluster_a = ClusterFactory(
        metadata__name="a",
        spec__metrics=[MetricRef(name="metric-1", weight=1.0, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster_b = ClusterFactory(
        metadata__name="b",
        spec__metrics=[MetricRef(name="metric-1", weight=1.0, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )

    scheduled_app = ApplicationFactory(
        status__state=ApplicationState.RUNNING,
        status__scheduled_to=resource_ref(cluster_a),
    )
    pending_app = ApplicationFactory(status__state=ApplicationState.PENDING)

    static_provider = GlobalMetricsProviderFactory(
        metadata__name="static-provider",
        spec__type="static",
        spec__static__metrics={"my_metric": 0.75},
    )
    metric = GlobalMetricFactory(
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

        ranked = await scheduler.kubernetes_application.rank_kubernetes_clusters(
            pending_app, [cluster_a, cluster_b]
        )
        assert ranked[0].score == 0.75
        assert ranked[1].score == 0.75

        # Compute the score of the clusters where application is already scheduled to
        # one of the clusters, hence a stickiness metric should be added to the score of
        # cluster "A".
        ranked = await scheduler.kubernetes_application.rank_kubernetes_clusters(
            scheduled_app, [cluster_a, cluster_b]
        )

        assert ranked[0].score == pytest.approx(0.75 / 1.1 + 0.1 / 1.1)
        assert ranked[1].score == 0.75
        assert ranked[0].score > ranked[1].score

        assert ranked[0].cluster == cluster_a
        assert ranked[1].cluster == cluster_b


async def test_kubernetes_score_with_metrics_only(aiohttp_server, config, loop):
    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(spec__metrics=[], status__state=ClusterState.ONLINE),
        ClusterFactory(spec__metrics=[], status__state=ClusterState.ONLINE),
    ]

    with pytest.raises(ValueError):
        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        server = await aiohttp_server(create_app(config))

        async with Client(url=server_endpoint(server), loop=loop) as client:
            await scheduler.prepare(client)
            await scheduler.kubernetes_application.rank_kubernetes_clusters(
                app, clusters
            )


async def test_kubernetes_score_with_inherited_metrics(
    aiohttp_server, config, db, loop
):

    cloud = CloudFactory(
        metadata__name="test",
        metadata__namespace="testing",
        spec__openstack__metrics=[
            MetricRef(name="metric-1", weight=1.0, namespaced=False)
        ],
    )
    gcloud = GlobalCloudFactory(
        metadata__name="test",
        spec__openstack__metrics=[
            MetricRef(name="metric-1", weight=1.0, namespaced=False)
        ],
    )

    clusters = [
        ClusterFactory(
            spec__metrics=[],
            spec__inherit_metrics=True,
            status__scheduled_to=ResourceRef(
                api="infrastructure",
                kind="Cloud",
                name=cloud.metadata.name,
                namespace=cloud.metadata.namespace,
            ),
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[],
            spec__inherit_metrics=True,
            status__scheduled_to=ResourceRef(
                api="infrastructure",
                kind="GlobalCloud",
                name=gcloud.metadata.name,
            ),
            status__state=ClusterState.ONLINE,
        ),
    ]

    app = ApplicationFactory(status__is_scheduled=False)

    static_provider = GlobalMetricsProviderFactory(
        metadata__name="static-provider",
        spec__type="static",
        spec__static__metrics={"my_metric": 0.75},
    )
    metric = GlobalMetricFactory(
        metadata__name="metric-1",
        spec__provider__name="static-provider",
        spec__provider__metric="my_metric",
    )

    await db.put(cloud)
    await db.put(gcloud)
    await db.put(metric)
    await db.put(static_provider)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        await scheduler.kubernetes_application.rank_kubernetes_clusters(app, clusters)


async def test_kubernetes_score_missing_metric(aiohttp_server, db, config, loop):
    """Test the error handling of the Scheduler in the case of fetching a metric
    referenced in a Cluster but not present in the database.
    """
    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="non-existent-metric", weight=1, namespaced=False)
            ],
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="non-existent-metric", weight=1, namespaced=True)
            ],
            status__state=ClusterState.ONLINE,
        ),
    ]
    for cluster in clusters:
        await db.put(cluster)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_application.rank_kubernetes_clusters(
            app, clusters
        )

    assert len(scored) == 0

    for cluster in clusters:
        stored_cluster = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        assert stored_cluster.status.state == ClusterState.FAILING_METRICS
        assert len(stored_cluster.status.metrics_reasons) == 1

        single_metric_reason = stored_cluster.status.metrics_reasons[
            "non-existent-metric"
        ]
        assert single_metric_reason.code == ReasonCode.UNKNOWN_METRIC


async def test_kubernetes_score_missing_metrics_provider(
    aiohttp_server, config, db, loop
):
    """Test the error handling of the Scheduler in the case of fetching a metric
    provider referenced in a metric referenced by a Cluster but the provider is not
    present in the database.
    """
    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(
            spec__metrics=[MetricRef(name="my-metric", weight=1, namespaced=False)],
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[MetricRef(name="my-metric", weight=1, namespaced=True)],
            status__state=ClusterState.ONLINE,
        ),
    ]
    for cluster in clusters:
        await db.put(cluster)

    metrics = [
        GlobalMetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="non-existent-metric",
        ),
        MetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="non-existent-metric",
        ),
    ]
    for metric in metrics:
        await db.put(metric)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_application.rank_kubernetes_clusters(
            app, clusters
        )

    assert len(scored) == 0

    for cluster in clusters:
        stored_cluster = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        assert stored_cluster.status.state == ClusterState.FAILING_METRICS
        assert len(stored_cluster.status.metrics_reasons) == 1
        assert (
            stored_cluster.status.metrics_reasons["my-metric"].code
            == ReasonCode.UNKNOWN_METRICS_PROVIDER
        )


async def test_kubernetes_score_multiple_failing_metric(
    aiohttp_server, db, config, loop
):
    """Test the error handling of the Scheduler in the case of several errors related to
    metrics referenced in two different Clusters. The issues are the following:

    1st cluster:
    - 1st metric: defined metric provider not present in the database
    - 2nd metric: not present in the database

    2nd cluster:
    - 1st metric: defined metric provider returns errors.
    - 2nd metric: not present in the database.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="non-existent-metric", weight=1, namespaced=False),
                MetricRef(name="existent-metric", weight=1, namespaced=False),
            ],
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[
                MetricRef(name="also-existent", weight=1, namespaced=False),
                MetricRef(name="again-non-existent", weight=1, namespaced=False),
            ],
            status__state=ClusterState.ONLINE,
        ),
    ]
    for cluster in clusters:
        await db.put(cluster)

    metrics = [
        GlobalMetricFactory(
            metadata__name="existent-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
        GlobalMetricFactory(
            metadata__name="also-existent",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="my-other-metric",
        ),
    ]
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    for metric in metrics:
        await db.put(metric)
    await db.put(provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_application.rank_kubernetes_clusters(
            app, clusters
        )

    assert len(scored) == 0

    # 1st cluster:
    # - 1st metric: defined metric provider not present in the database
    # - 2nd metric: not present in the database
    first_cluster = await db.get(
        Cluster,
        namespace=clusters[0].metadata.namespace,
        name=clusters[0].metadata.name,
    )
    assert first_cluster.status.state == ClusterState.FAILING_METRICS
    assert len(first_cluster.status.metrics_reasons) == 2

    assert (
        first_cluster.status.metrics_reasons["existent-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )
    assert (
        first_cluster.status.metrics_reasons["non-existent-metric"].code
        == ReasonCode.UNKNOWN_METRIC
    )

    # 2nd cluster:
    # - 1st metric: defined metric provider returns errors.
    # - 2nd metric: not present in the database
    second_cluster = await db.get(
        Cluster,
        namespace=clusters[1].metadata.namespace,
        name=clusters[1].metadata.name,
    )
    assert second_cluster.status.state == ClusterState.FAILING_METRICS
    assert len(second_cluster.status.metrics_reasons) == 2

    assert (
        second_cluster.status.metrics_reasons["also-existent"].code
        == ReasonCode.UNKNOWN_METRICS_PROVIDER
    )
    assert (
        second_cluster.status.metrics_reasons["again-non-existent"].code
        == ReasonCode.UNKNOWN_METRIC
    )


async def test_kubernetes_score_failing_metrics_provider(
    aiohttp_server, config, db, loop
):
    """Test the error handling of the Scheduler in the case of fetching the value of a
    metric (referenced by a Cluster) from its provider, but the connection has an issue.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(
            spec__metrics=[MetricRef(name="my-metric", weight=1, namespaced=True)],
            status__state=ClusterState.ONLINE,
        )
    ]
    await db.put(clusters[0])
    metrics = [
        MetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        )
    ]
    provider = MetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    for metric in metrics:
        await db.put(metric)
    await db.put(provider)

    api = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(api), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_application.rank_kubernetes_clusters(
            app, clusters
        )

    assert len(scored) == 0

    cluster = clusters[0]
    stored_cluster = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored_cluster.status.state == ClusterState.FAILING_METRICS
    assert len(stored_cluster.status.metrics_reasons) == 1
    assert (
        stored_cluster.status.metrics_reasons["my-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )


async def test_kubernetes_score_failing_globalmetrics_provider(
    aiohttp_server, config, db, loop
):
    """Test the error handling of the Scheduler in the case of fetching the value of a
    metric (referenced by a Cluster) from its provider, but the connection has an issue.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    app = ApplicationFactory(status__is_scheduled=False)
    clusters = [
        ClusterFactory(
            spec__metrics=[MetricRef(name="my-metric", weight=1, namespaced=False)],
            status__state=ClusterState.ONLINE,
        )
    ]
    await db.put(clusters[0])
    metrics = [
        GlobalMetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        )
    ]
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    for metric in metrics:
        await db.put(metric)
    await db.put(provider)

    api = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(api), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_application.rank_kubernetes_clusters(
            app, clusters
        )

    assert len(scored) == 0

    cluster = clusters[0]
    stored_cluster = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored_cluster.status.state == ClusterState.FAILING_METRICS
    assert len(stored_cluster.status.metrics_reasons) == 1
    assert (
        stored_cluster.status.metrics_reasons["my-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )


async def test_kubernetes_prefer_cluster_with_global_metrics(
    aiohttp_server, config, db, loop
):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": 2 * ["0.4"]}))

    cluster_miss = ClusterFactory(spec__metrics=[], status__state=ClusterState.ONLINE)
    cluster = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="my_metric",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, (cluster_miss, cluster), []
        )

    assert cluster == selected


@pytest.mark.skip(reason="The test wants to create/use a real K8s resource.")
async def test_kubernetes_prefer_cluster_with_namespaced_metrics(
    aiohttp_server, config, db, loop
):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": ["0.4"]}))

    cluster_miss = ClusterFactory(spec__metrics=[], status__state=ClusterState.ONLINE)
    cluster = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=True)],
        status__state=ClusterState.ONLINE,
    )
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
        selected = await scheduler.kubernetes_application.select_kubernetes_cluster(
            app, (cluster_miss, cluster)
        )

    assert selected == cluster


async def test_kubernetes_select_cluster_without_metric(aiohttp_server, config, loop):
    clusters = (
        ClusterFactory(spec__metrics=[]),
        ClusterFactory(spec__metrics=[], status__state=ClusterState.ONLINE),
    )
    app = ApplicationFactory(spec__constraints=None)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, clusters, []
        )
        assert selected in clusters


async def test_kubernetes_select_cluster_with_inherited_metrics(
    aiohttp_server, config, db, loop
):

    prometheus = await aiohttp_server(make_prometheus({"load": ["1"]}))

    cloud = CloudFactory(
        metadata__name="test",
        metadata__namespace="testing",
        metadata__labels={},
        spec__openstack__metrics=[MetricRef(name="load", weight=6.0, namespaced=False)],
    )
    cluster = ClusterFactory(
        spec__inherit_metrics=True,
        spec__metrics=[],
        status__scheduled_to=ResourceRef(
            api="infrastructure",
            kind="Cloud",
            name=cloud.metadata.name,
            namespace=cloud.metadata.namespace,
        ),
        status__state=ClusterState.ONLINE,
    )

    app = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[MetricConstraint.parse("load > 5")],
        spec__constraints__cluster__custom_resources=[],
    )

    metric = GlobalMetricFactory(
        metadata__name="load",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-test",
        spec__provider__metric="load",
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus-test",
        spec__type="prometheus",
        spec__prometheus__url=f"http://{prometheus.host}:{prometheus.port}",
    )

    await db.put(metric)
    await db.put(metrics_provider)
    await db.put(cloud)
    await db.put(cluster)
    await db.put(app)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, [cluster], []
        )
        assert cluster == selected


async def test_kubernetes_select_cluster_not_deleted(aiohttp_server, config, loop):
    # As the finally selected cluster is chosen randomly, perform the test several times
    # to ensure that the cluster has really been chosen the right way, not by chance.
    for _ in range(10):
        index = random.randint(0, 9)
        clusters = [
            ClusterFactory(
                metadata__deleted=datetime.now(timezone.utc),
                spec__metrics=[],
                status__state=ClusterState.ONLINE,
            )
            for _ in range(10)
        ]
        clusters[index].metadata.deleted = None

        app = ApplicationFactory(spec__constraints=None)

        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        server = await aiohttp_server(create_app(config))

        async with Client(url=server_endpoint(server), loop=loop) as client:
            await scheduler.prepare(client)
            selected = (
                await scheduler.kubernetes_application.select_scheduling_location(
                    app, clusters, []
                )
            )

            assert clusters[index] == selected


async def test_kubernetes_select_cluster_online(aiohttp_server, config, loop):
    # As the finally selected cluster is chosen randomly, perform the test several times
    # to ensure that the cluster has really been chosen the right way, not by chance.
    for _ in range(10):
        index = random.randint(0, 9)
        clusters = [
            ClusterFactory(spec__metrics=[], status__state=ClusterState.OFFLINE)
            for _ in range(10)
        ]

        clusters[index].status.state = ClusterState.ONLINE

        app = ApplicationFactory(spec__constraints=None)

        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        server = await aiohttp_server(create_app(config))

        async with Client(url=server_endpoint(server), loop=loop) as client:
            await scheduler.prepare(client)
            selected = (
                await scheduler.kubernetes_application.select_scheduling_location(
                    app, clusters, []
                )
            )

            assert clusters[index] == selected


async def test_kubernetes_select_cluster_with_constraints_without_metric(
    aiohttp_server, config, loop
):
    # Because the selection of clusters is done randomly between the matching clusters,
    # if an error was present, the right cluster could have been randomly picked,
    # and the test would pass even if it should not.
    # Thus, many cluster that should not match are created, which reduces the chances
    # that the expected cluster is chosen, even in case of failures.
    countries = ["IT"] + fake.words(99)
    clusters = [
        ClusterFactory(
            spec__metrics=[],
            metadata__labels={"location": country},
            status__state=ClusterState.ONLINE,
        )
        for country in countries
    ]

    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
    )

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, clusters, []
        )
        assert clusters[0] == selected


async def test_kubernetes_select_cluster_with_inherited_labels_from_cloud(
    aiohttp_server, config, db, loop
):
    cloud = CloudFactory(
        metadata__name="test",
        metadata__namespace="testing",
        metadata__labels={"location": "IT"},
    )
    cluster = ClusterFactory(
        metadata__inherit_labels=True,
        spec__metrics=[],
        status__scheduled_to=ResourceRef(
            api="infrastructure",
            kind="Cloud",
            name=cloud.metadata.name,
            namespace=cloud.metadata.namespace,
        ),
        status__state=ClusterState.ONLINE,
    )

    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
    )

    await db.put(cloud)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, [cluster], []
        )
        assert cluster == selected


async def test_kubernetes_select_cluster_with_inherited_labels_from_global_cloud(
    aiohttp_server, config, db, loop
):
    cloud = GlobalCloudFactory(
        metadata__name="test",
        metadata__namespace="testing",
        metadata__labels={"location": "IT"},
    )
    cluster = ClusterFactory(
        metadata__inherit_labels=True,
        spec__metrics=[],
        status__scheduled_to=ResourceRef(
            api="infrastructure",
            kind="GlobalCloud",
            name=cloud.metadata.name,
        ),
        status__state=ClusterState.ONLINE,
    )

    app = ApplicationFactory(
        spec__constraints__cluster__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
    )

    await db.put(cloud)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, [cluster], []
        )
        assert cluster == selected


async def test_kubernetes_select_cluster_sticky_without_metric(
    aiohttp_server, config, loop
):
    cluster_a = ClusterFactory(spec__metrics=[], status__state=ClusterState.ONLINE)
    cluster_b = ClusterFactory(spec__metrics=[], status__state=ClusterState.ONLINE)
    app = ApplicationFactory(
        spec__constraints=None,
        status__scheduled_to=resource_ref(cluster_a),
        status__is_scheduled=True,
        status__state=ApplicationState.RUNNING,
    )

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, (cluster_a, cluster_b), []
        )
        assert cluster_a == selected


async def test_kubernetes_select_no_cluster_all_unreachable_metric(
    aiohttp_server, config, db, loop
):
    """Test: the scheduler picks no cluster if all metrics providers are unreachable
    as this will set the clusters to ClusterState.FAILING_METRICS"""
    clusters = [
        ClusterFactory(
            spec__metrics=[MetricRef(name="unreachable", weight=1, namespaced=False)],
            status__state=ClusterState.ONLINE,
        ),
        ClusterFactory(
            spec__metrics=[MetricRef(name="unreachable", weight=0.1, namespaced=True)],
            status__state=ClusterState.ONLINE,
        ),
    ]
    for cluster in clusters:
        await db.put(cluster)

    metrics = [
        GlobalMetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
        MetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
    ]
    providers = [
        GlobalMetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
        MetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
    ]

    for metric in metrics:
        await db.put(metric)
    for provider in providers:
        await db.put(provider)

    random.shuffle(clusters)

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
        spec__constraints=None,
    )
    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        with pytest.raises(NoClusterFound):
            await scheduler.kubernetes_application.select_scheduling_location(
                app, clusters, []
            )

    for cluster in clusters:
        assert cluster.status.state == ClusterState.FAILING_METRICS


async def test_kubernetes_select_cluster_some_unreachable_metric(
    aiohttp_server, config, db, loop
):
    """Test: the scheduler picks cluster from those with metrics from
    reachable providers"""
    prometheus = await aiohttp_server(make_prometheus({"heat-demand": ["0.4"] * 2}))

    cluster_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    cluster_w_unreachable = ClusterFactory(
        spec__metrics=[MetricRef(name="unreachable", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster_w_metric = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    await db.put(cluster_w_metric)
    await db.put(cluster_wo_metric)
    await db.put(cluster_w_unreachable)

    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat-demand",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, [cluster_wo_metric, cluster_w_unreachable, cluster_w_metric], []
        )

    assert cluster_w_metric == selected


async def test_kubernetes_select_cluster_sticky_all_unreachable_metric(
    aiohttp_server, config, db, loop
):
    """Test which stickiness has the highest priority,
    if no metrics provider is reachable"""
    cluster_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    current_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    cluster1_w_metric = ClusterFactory(
        spec__metrics=[MetricRef(name="unreachable", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster2_w_metric = ClusterFactory(
        spec__metrics=[MetricRef(name="unreachable", weight=1, namespaced=True)],
        status__state=ClusterState.ONLINE,
    )
    clusters = [
        cluster_wo_metric,
        current_wo_metric,
        cluster1_w_metric,
        cluster2_w_metric,
    ]
    random.shuffle(clusters)
    for cluster in clusters:
        await db.put(cluster)

    metrics = [
        GlobalMetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
        MetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
    ]
    providers = [
        GlobalMetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
        MetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
    ]
    for metric in metrics:
        await db.put(metric)
    for provider in providers:
        await db.put(provider)

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(current_wo_metric),
        spec__constraints=None,
    )
    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, clusters, []
        )

    assert current_wo_metric == selected


async def test_kubernetes_select_cluster_sticky_others_with_metric(
    aiohttp_server, config, db, loop
):
    """Test that metric has higher priority than stickiness"""
    prometheus = await aiohttp_server(
        make_prometheus({"heat-demand": 4 * ["0.4"], "some-metric": 4 * ["1.0"]})
    )

    current_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    cluster_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    cluster_w_metric1 = ClusterFactory(
        spec__metrics=[
            MetricRef(name="heat-demand", weight=0.9, namespaced=False),
            MetricRef(name="some-metric", weight=1, namespaced=False),
        ],
        status__state=ClusterState.ONLINE,
    )
    cluster_w_metric2 = ClusterFactory(
        spec__metrics=[
            MetricRef(name="heat-demand", weight=0.5, namespaced=False),
            MetricRef(name="some-metric", weight=1, namespaced=False),
        ],
        status__state=ClusterState.ONLINE,
    )
    clusters = [
        current_wo_metric,
        cluster_wo_metric,
        cluster_w_metric1,
        cluster_w_metric2,
    ]
    random.shuffle(clusters)

    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat-demand",
    )
    some_metric = GlobalMetricFactory(
        metadata__name="some-metric",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="some-metric",
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(current_wo_metric),
        spec__constraints=None,
    )
    await db.put(metric)
    await db.put(some_metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, clusters, []
        )

    assert cluster_w_metric2 == selected


async def test_kubernetes_select_cluster_sticky_reachable_metric(
    aiohttp_server, config, db, loop
):
    """Test that stickiness is taken into account when metrics are used"""
    prometheus = await aiohttp_server(make_prometheus({"heat-demand": 4 * ["0.4"]}))

    cluster_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    current_w_metric = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=0.99, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster_w_metric = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )

    clusters = [cluster_wo_metric, current_w_metric, cluster_w_metric]
    random.shuffle(clusters)

    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat-demand",
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(current_w_metric),
        spec__constraints=None,
    )
    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, clusters, []
        )

    assert current_w_metric == selected


async def test_kubernetes_select_no_cluster_sticky_to_all_unreachable_metric(
    aiohttp_server, config, db, loop
):
    """Test that also clusters with unreachable metrics providers are considered"""
    cluster_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    current_w_unreachable = ClusterFactory(
        spec__metrics=[MetricRef(name="unreachable", weight=0.99, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster_w_unreachable = ClusterFactory(
        spec__metrics=[MetricRef(name="unreachable", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    clusters = [cluster_wo_metric, current_w_unreachable, cluster_w_unreachable]
    for cluster in clusters:
        await db.put(cluster)
    random.shuffle(clusters)

    metric = GlobalMetricFactory(
        metadata__name="unreachable",
        spec__min=0,
        spec__max=1,
        spec__provider__name="my-provider",
        spec__provider__metric="my-metric",
    )
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url="http://dummyurl",
    )

    await db.put(metric)
    await db.put(provider)

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(current_w_unreachable),
        spec__constraints=None,
    )

    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, clusters, []
        )

    assert cluster_wo_metric == selected


async def test_kubernetes_select_cluster_sticky_unreachable_metric(
    aiohttp_server, config, db, loop
):
    """Test metrics have higher priority than stickiness also if current cluster
    has unreachable metrics."""
    prometheus = await aiohttp_server(make_prometheus({"heat-demand": 2 * ["0.4"]}))

    cluster_wo_metric = ClusterFactory(
        spec__metrics=[], status__state=ClusterState.ONLINE
    )
    current_w_unreachable = ClusterFactory(
        spec__metrics=[MetricRef(name="unreachable", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster_w_metric = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    clusters = [cluster_wo_metric, current_w_unreachable, cluster_w_metric]
    random.shuffle(clusters)
    for cluster in clusters:
        await db.put(cluster)

    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat-demand",
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    app = ApplicationFactory(
        status__state=ApplicationState.PENDING,
        status__is_scheduled=True,
        status__scheduled_to=resource_ref(current_w_unreachable),
        spec__constraints=None,
    )
    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_application.select_scheduling_location(
            app, clusters, []
        )

    assert cluster_w_metric == selected


async def test_kubernetes_scheduling(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"heat_demand_zone_1": ["0.25"]}))

    cluster = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat_demand_zone_1",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored = await db.get(Application, namespace="testing", name=app.metadata.name)

        assert stored.status.scheduled_to == resource_ref(cluster)
        assert stored.status.kube_controller_triggered
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
        await scheduler.kubernetes_application.handle_kubernetes_applications(
            run_once=True
        )

    stored = await db.get(Application, namespace="testing", name=app.metadata.name)
    assert stored.status.reason.code == ReasonCode.NO_SUITABLE_RESOURCE


async def test_kubernetes_migration(aiohttp_server, config, db, loop):
    """Test that the app is migrated due to metrics changes if the time passed
    since the last schedule was long enough."""
    prometheus = await aiohttp_server(
        make_prometheus(
            {
                "heat_demand_1": ("0.5", "0.5", "0.25", "0.25", "0.25", "0.25"),
                "heat_demand_2": ("0.25", "0.25", "0.5", "0.5", "0.5", "0.5"),
            }
        )
    )

    cluster1 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-1", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster2 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-2", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )

    app = ApplicationFactory(
        metadata__modified=datetime.now(timezone.utc),
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = GlobalMetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = GlobalMetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        # The reschedule_after time should be kept small to shorten the runtime
        # of the test. If it is too short however the test will fail,
        # since second_try_elapsed will become greater than reschedule_after.
        reschedule_after = timedelta(seconds=1)
        scheduler = Scheduler(
            server_endpoint(server),
            worker_count=0,
            reschedule_after=reschedule_after.seconds,
        )
        await scheduler.prepare(client)
        await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING
        assert stored1.metadata.modified <= stored1.status.kube_controller_triggered
        assert stored1.metadata.modified <= stored1.status.scheduled

        # Schedule a second time the scheduled resource
        await scheduler.kubernetes_application.kubernetes_application_received(stored1)
        second_try_time = datetime.now().astimezone()

        # Since not much time has passed the application should not have migrated
        # although the metrics changed. This is to avoid migrating the application
        # everytime the metrics change.
        # In test_kubernetes_migration_w_update the same test is performed but with
        # an update, and there the second_try does cause a migration.

        stored_second_try = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        second_try_elapsed = second_try_time - stored1.status.scheduled
        assert second_try_elapsed < reschedule_after
        assert stored_second_try.status.scheduled_to == resource_ref(cluster1)
        assert stored_second_try.status.state == ApplicationState.PENDING
        assert stored_second_try.status.scheduled == stored1.status.scheduled

        # Pause until scheduler.reschedule_after seconds has passed after the
        # first migration before receiving the application again.
        # This time it should be rescheduled,
        # since it was long enough ago that it was scheduled the first time.
        pause = reschedule_after - second_try_elapsed
        time.sleep(pause.total_seconds())

        # Schedule the application a third time
        await scheduler.kubernetes_application.kubernetes_application_received(
            stored_second_try
        )

        stored2 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored2.status.scheduled_to == resource_ref(cluster2)
        assert stored2.status.state == ApplicationState.PENDING
        assert (
            stored2.status.kube_controller_triggered
            > stored1.status.kube_controller_triggered
        )
        assert stored2.metadata.modified <= stored2.status.kube_controller_triggered
        assert stored2.status.scheduled > stored1.status.scheduled
        time_between_migrations = stored2.status.scheduled - stored1.status.scheduled
        assert time_between_migrations >= reschedule_after
        assert stored2.metadata.modified <= stored2.status.scheduled


# FIXME: krake#405: Skip until we figured out how to differentiate between an
# update by user and an update by the kubernetes controller. Update by user
# should cause a migration if the metrics changed, whereas an update by the
# kubernetes controller only should cause a migration of the app was not
# 'recently' scheduled.
@pytest.mark.skip(
    reason="The functionality that is tested here has not yet been implemented, "
    "since we cannot differentiate between update by user (which should (?) "
    "cause reevaluation of scheduling decision) and update by kube controller "
    "after scheduling decision was made (krake#405)."
)
async def test_kubernetes_migration_w_update(aiohttp_server, config, db, loop):
    """Test that the app is migrated due to an update even if the time passed
    since the last schedule was shorter than the rescheduling interval."""
    prometheus = await aiohttp_server(
        make_prometheus(
            {"heat_demand_1": ("0.5", "0.25"), "heat_demand_2": ("0.25", "0.5")}
        )
    )

    cluster1 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-1", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster2 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-2", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        metadata__modified=datetime.now(timezone.utc),
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = GlobalMetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = GlobalMetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        # The reschedule_after time should be kept small to shorten the runtime
        # of the test. If it is too short however the test will fail,
        # since second_try_elapsed will become greater than reschedule_after.
        reschedule_after = timedelta(seconds=5)
        scheduler = Scheduler(
            server_endpoint(server),
            worker_count=0,
            reschedule_after=reschedule_after.seconds,
        )
        await scheduler.prepare(client)
        await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING
        assert stored1.metadata.modified <= stored1.status.kube_controller_triggered
        assert stored1.metadata.modified <= stored1.status.scheduled

        # Schedule a second time the scheduled resource WITH update
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            name=stored1.metadata.name,
            namespace=stored1.metadata.namespace,
            body=stored1,
        )
        assert stored1.metadata.modified < received.metadata.modified

        update_app = deepcopy(received)
        await scheduler.kubernetes_application.kubernetes_application_received(
            update_app
        )
        second_try_time = datetime.now().astimezone()

        # Although not much time has passed since the last scheduling,
        # the application should have migrated
        # due to metrics change since the app was updated.
        # In test_kubernetes_migration the same test is performed but without
        # the update, and there the second_try does not cause a migration.

        stored_second_try = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        second_try_elapsed = second_try_time - stored1.status.scheduled
        assert second_try_elapsed < reschedule_after
        assert stored_second_try.status.scheduled_to == resource_ref(cluster2)
        assert stored_second_try.status.state == ApplicationState.PENDING
        assert stored_second_try.status.scheduled > stored1.status.scheduled


async def test_kubernetes_no_migration(aiohttp_server, config, db, loop):
    """
    Test that an app with migration constraint false does not get
    rescheduled due to cluster constraints.
    """
    prometheus = await aiohttp_server(
        make_prometheus(
            {
                "heat_demand_1": ("0.5", "0.5", "0.25"),
                "heat_demand_2": ("0.25", "0.25", "0.5"),
            }
        )
    )

    cluster1 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-1", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster2 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-2", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        metadata__modified=datetime.now(timezone.utc),
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        spec__constraints__migration=False,
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = GlobalMetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = GlobalMetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING
        assert stored1.metadata.modified <= stored1.status.kube_controller_triggered
        assert stored1.metadata.modified <= stored1.status.scheduled

        # Schedule the scheduled resource a second time
        await scheduler.kubernetes_application.kubernetes_application_received(stored1)

        stored2 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored2.status.scheduled_to == resource_ref(cluster1)
        assert stored2.status.state == ApplicationState.PENDING
        assert (
            stored2.status.kube_controller_triggered
            == stored1.status.kube_controller_triggered
        )
        assert stored2.metadata.modified <= stored2.status.kube_controller_triggered
        assert stored2.status.scheduled == stored1.status.scheduled
        assert stored2.metadata.modified <= stored2.status.scheduled


@pytest.mark.skip(reason="The metrics are failing.")
async def test_kubernetes_application_update(aiohttp_server, config, db, loop):
    # Schedule the application, then handle the application again after it has been
    # updated. As the metrics did not change, the cluster scheduled should be the same,
    # but the scheduled timestamp should be updated to allow the KubernetesController to
    # handle the Application afterwards.

    prometheus = await aiohttp_server(
        make_prometheus(
            {"heat_demand_1": ("0.5", "0.5"), "heat_demand_2": ("0.25", "0.25")}
        )
    )

    cluster1 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-1", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster2 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-2", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        metadata__modified=datetime.now(timezone.utc),
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = GlobalMetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = GlobalMetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING
        assert stored1.metadata.modified <= stored1.status.kube_controller_triggered
        assert stored1.metadata.modified <= stored1.status.scheduled

        # Actual update:
        stored1.metadata.labels["foo"] = "bar"
        kubernetes_api = KubernetesApi(client)
        received = await kubernetes_api.update_application(
            name=stored1.metadata.name,
            namespace=stored1.metadata.namespace,
            body=stored1,
        )
        assert stored1.metadata.modified < received.metadata.modified

        # Schedule a second time the scheduled resource
        updated_app = deepcopy(received)
        await scheduler.kubernetes_application.kubernetes_application_received(
            updated_app
        )

        stored2 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored2.status.scheduled_to == resource_ref(cluster1)
        assert stored2.status.state == ApplicationState.PENDING
        # As the scheduling decision was the same, the timestamp should not change.
        assert stored2.status.scheduled == stored1.status.scheduled
        assert stored2.metadata.modified >= stored2.status.scheduled

        # Even if the scheduled cluster did not change, the timestamp should be updated,
        # as the Application was updated.
        assert (
            stored2.status.kube_controller_triggered
            > stored1.status.kube_controller_triggered
        )
        assert stored2.metadata.modified <= stored2.status.kube_controller_triggered


@pytest.mark.skip(reason="The metrics are failing.")
async def test_kubernetes_application_reschedule_no_update(
    aiohttp_server, config, db, loop
):
    # Schedule the application, then handle the application again because of
    # rescheduling. As the metrics did not change, the cluster scheduled should be the
    # same. Because of this and also because the Application did not change, the
    # scheduled timestamp should not be updated.

    prometheus = await aiohttp_server(
        make_prometheus(
            {"heat_demand_1": ("0.5", "0.5"), "heat_demand_2": ("0.25", "0.25")}
        )
    )

    cluster1 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-1", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    cluster2 = ClusterFactory(
        spec__metrics=[MetricRef(name="heat-demand-2", weight=1, namespaced=False)],
        status__state=ClusterState.ONLINE,
    )
    app = ApplicationFactory(
        metadata__modified=datetime.now(timezone.utc),
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )
    metric1 = GlobalMetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )
    metric2 = GlobalMetricFactory(
        metadata__name="heat-demand-2",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_2",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored1 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored1.status.scheduled_to == resource_ref(cluster1)
        assert stored1.status.state == ApplicationState.PENDING
        assert stored1.metadata.modified <= stored1.status.kube_controller_triggered
        assert stored1.metadata.modified <= stored1.status.scheduled

        # Schedule a second time the scheduled resource
        updated_app = deepcopy(stored1)
        await scheduler.kubernetes_application.kubernetes_application_received(
            updated_app
        )

        stored2 = await db.get(
            Application, namespace=app.metadata.namespace, name=app.metadata.name
        )
        assert stored2.status.scheduled_to == resource_ref(cluster1)
        assert stored2.status.state == ApplicationState.PENDING
        # As the scheduled cluster did not change and the Application was not updated,
        # the timestamps should not be updated.
        assert (
            stored2.status.kube_controller_triggered
            == stored1.status.kube_controller_triggered
        )
        assert stored2.metadata.modified <= stored2.status.kube_controller_triggered
        assert stored2.status.scheduled == stored1.status.scheduled
        assert stored2.metadata.modified <= stored2.status.scheduled


def test_openstack_match_project_label_constraints():
    project = ProjectFactory(metadata__labels={"location": "IT"})
    cluster = MagnumClusterFactory(
        spec__constraints__project__labels=[LabelConstraint.parse("location is IT")]
    )
    assert match_project_constraints(cluster, project)


def test_openstack_match_empty_project_label_constraints():
    project = ProjectFactory(metadata__labels=[])
    cluster1 = MagnumClusterFactory(spec__constraints=None)
    cluster2 = MagnumClusterFactory(spec__constraints__project=None)
    cluster3 = MagnumClusterFactory(spec__constraints__project__labels=None)

    assert match_project_constraints(cluster1, project)
    assert match_project_constraints(cluster2, project)
    assert match_project_constraints(cluster3, project)


def test_openstack_not_match_project_label_constraints():
    project = ProjectFactory()
    cluster = MagnumClusterFactory(
        spec__constraints__project__labels=[LabelConstraint.parse("location is IT")]
    )

    assert not match_project_constraints(cluster, project)


async def test_openstack_score(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"test_metric_1": ["0.42"]}))

    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [
        ProjectFactory(
            spec__metrics=[
                MetricRef(name="test-metric-1", weight=1.0, namespaced=False)
            ]
        ),
        ProjectFactory(
            spec__metrics=[
                MetricRef(name="test-metric-2", weight=1.0, namespaced=False)
            ]
        ),
    ]
    metrics = [
        GlobalMetricFactory(
            metadata__name="test-metric-1",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_1",
        ),
        GlobalMetricFactory(
            metadata__name="test-metric-2",
            spec__provider__name="test-static",
            spec__provider__metric="test_metric_2",
        ),
    ]
    prometheus_provider = GlobalMetricsProviderFactory(
        metadata__name="test-prometheus",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    static_provider = GlobalMetricsProviderFactory(
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
        projects_scores = await scheduler.openstack.rank_openstack_projects(
            cluster, projects
        )

    for ranked, project in zip(projects_scores, projects):
        assert ranked.score is not None
        assert ranked.project == project


async def test_openstack_score_with_metrics_only(aiohttp_server, config, loop):
    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [ProjectFactory(spec__metrics=[]), ProjectFactory(spec__metrics=[])]

    with pytest.raises(ValueError):
        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        server = await aiohttp_server(create_app(config))

        async with Client(url=server_endpoint(server), loop=loop) as client:
            await scheduler.prepare(client)
            await scheduler.openstack.rank_openstack_projects(cluster, projects)


async def test_openstack_score_missing_metric(aiohttp_server, db, config, loop):
    """Test the error handling of the Scheduler in the case of fetching a metric
    referenced in a Project but not present in the database.
    """
    cluster = MagnumClusterFactory(status__is_scheduled=False)
    project = ProjectFactory(
        spec__metrics=[
            MetricRef(name="non-existent-metric", weight=1, namespaced=False)
        ]
    )
    await db.put(project)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.openstack.rank_openstack_projects(cluster, [project])

    assert len(scored) == 0

    stored_project = await db.get(
        Project, namespace=project.metadata.namespace, name=project.metadata.name
    )
    assert stored_project.status.state == ProjectState.FAILING_METRICS
    assert len(stored_project.status.metrics_reasons) == 1

    single_metric_reason = stored_project.status.metrics_reasons["non-existent-metric"]
    assert single_metric_reason.code == ReasonCode.UNKNOWN_METRIC


async def test_openstack_score_multiple_failing_metric(
    aiohttp_server, db, config, loop
):
    """Test the error handling of the Scheduler in the case of several errors related to
    metrics referenced in two different Projects. The issues are the following:

    1st Project:test_select_no_matching_project
    - 1st metric: defined metric provider not present in the database
    - 2nd metric: not present in the database

    2nd Project:
    - 1st metric: defined metric provider returns errors.
    - 2nd metric: not present in the database.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [
        ProjectFactory(
            spec__metrics=[
                MetricRef(name="non-existent-metric", weight=1, namespaced=False),
                MetricRef(name="existent-metric", weight=1, namespaced=False),
            ]
        ),
        ProjectFactory(
            spec__metrics=[
                MetricRef(name="also-existent", weight=1, namespaced=False),
                MetricRef(name="again-non-existent", weight=1, namespaced=False),
            ]
        ),
    ]
    for project in projects:
        await db.put(project)

    metrics = [
        GlobalMetricFactory(
            metadata__name="existent-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
        GlobalMetricFactory(
            metadata__name="also-existent",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="my-other-metric",
        ),
    ]
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    for metric in metrics:
        await db.put(metric)
    await db.put(provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.openstack.rank_openstack_projects(cluster, projects)

    assert len(scored) == 0

    # 1st project:
    # - 1st metric: defined metric provider not present in the database
    # - 2nd metric: not present in the database
    first_project = await db.get(
        Project,
        namespace=projects[0].metadata.namespace,
        name=projects[0].metadata.name,
    )
    assert first_project.status.state == ProjectState.FAILING_METRICS
    assert len(first_project.status.metrics_reasons) == 2

    assert (
        first_project.status.metrics_reasons["existent-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )
    assert (
        first_project.status.metrics_reasons["non-existent-metric"].code
        == ReasonCode.UNKNOWN_METRIC
    )

    # 2nd project:
    # - 1st metric: defined metric provider returns errors.
    # - 2nd metric: not present in the database
    second_project = await db.get(
        Project,
        namespace=projects[1].metadata.namespace,
        name=projects[1].metadata.name,
    )
    assert second_project.status.state == ProjectState.FAILING_METRICS
    assert len(second_project.status.metrics_reasons) == 2

    assert (
        second_project.status.metrics_reasons["also-existent"].code
        == ReasonCode.UNKNOWN_METRICS_PROVIDER
    )
    assert (
        second_project.status.metrics_reasons["again-non-existent"].code
        == ReasonCode.UNKNOWN_METRIC
    )


async def test_openstack_score_missing_metrics_provider(
    aiohttp_server, config, db, loop
):
    """Test the error handling of the Scheduler in the case of fetching a metric
    provider referenced in a metric referenced by a Project but the provider is not
    present in the database.
    """
    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [
        ProjectFactory(
            spec__metrics=[MetricRef(name="my-metric", weight=1, namespaced=False)]
        )
    ]
    for project in projects:
        await db.put(project)
    metric = GlobalMetricFactory(
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
        scored = await scheduler.openstack.rank_openstack_projects(cluster, projects)

    assert len(scored) == 0

    project = projects[0]
    stored_project = await db.get(
        Project, namespace=project.metadata.namespace, name=project.metadata.name
    )
    assert stored_project.status.state == ProjectState.FAILING_METRICS
    assert len(stored_project.status.metrics_reasons) == 1
    assert (
        stored_project.status.metrics_reasons["my-metric"].code
        == ReasonCode.UNKNOWN_METRICS_PROVIDER
    )


async def test_openstack_score_failing_metrics_provider(
    aiohttp_server, config, db, loop
):
    """Test the error handling of the Scheduler in the case of fetching the value of a
    metric (referenced by a Cluster) from its provider, but the connection has an issue.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    cluster = MagnumClusterFactory(status__is_scheduled=False)
    projects = [
        ProjectFactory(
            spec__metrics=[MetricRef(name="my-metric", weight=1, namespaced=False)]
        )
    ]
    for project in projects:
        await db.put(project)
    metric = GlobalMetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
        spec__provider__name="my-provider",
        spec__provider__metric="my-metric",
    )
    provider = GlobalMetricsProviderFactory(
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
        scored = await scheduler.openstack.rank_openstack_projects(cluster, projects)

    assert len(scored) == 0

    project = projects[0]
    stored_project = await db.get(
        Project, namespace=project.metadata.namespace, name=project.metadata.name
    )
    assert stored_project.status.state == ProjectState.FAILING_METRICS
    assert len(stored_project.status.metrics_reasons) == 1
    assert (
        stored_project.status.metrics_reasons["my-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )


async def test_prefer_projects_with_metrics(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": ["0.4"]}))

    project_miss = ProjectFactory(spec__metrics=[])
    project = ProjectFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=False)]
    )
    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="my_metric",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        selected = await scheduler.openstack.select_openstack_project(
            cluster, (project_miss, project)
        )

    assert selected == project


async def test_select_project_without_metric(aiohttp_server, config, loop):
    projects = (ProjectFactory(spec__metrics=[]), ProjectFactory(spec__metrics=[]))
    cluster = MagnumClusterFactory(spec__constraints=None)

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.openstack.select_openstack_project(cluster, projects)
        assert selected in projects


async def test_select_project_not_deleted(aiohttp_server, config, loop):
    # As the finally selected project is chosen randomly, perform the test several times
    # to ensure that the project has really been chosen the right way, not by chance.
    for _ in range(10):
        index = random.randint(0, 9)
        projects = [
            ProjectFactory(
                metadata__deleted=datetime.now(timezone.utc), spec__metrics=[]
            )
            for _ in range(10)
        ]
        projects[index].metadata.deleted = None

        cluster = MagnumClusterFactory(spec__constraints=None)

        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        server = await aiohttp_server(create_app(config))

        async with Client(url=server_endpoint(server), loop=loop) as client:
            await scheduler.prepare(client)
            selected = await scheduler.openstack.select_openstack_project(
                cluster, projects
            )

            assert selected == projects[index]


@pytest.mark.skip(reason="Keyword missing in the serializable.py.")
async def test_select_no_matching_project(aiohttp_server, config, db, loop):
    """Ensure that an exception is raised if not matching Project is found for a
    MagnumCluster.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    cluster = MagnumClusterFactory(status__is_scheduled=False, spec__constraints=None)
    project = ProjectFactory(spec__metrics=[MetricRef(name="my-metric", weight=1)])
    metric = GlobalMetricFactory(
        metadata__name="my-metric",
        spec__min=0,
        spec__max=1,
        spec__provider__name="my-provider",
        spec__provider__metric="my-metric",
    )
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    await db.put(metric)
    await db.put(provider)
    await db.put(project)

    api = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(api), worker_count=0)
        await scheduler.prepare(client)

        with pytest.raises(NoProjectFound, match="No OpenStack project available"):
            await scheduler.openstack.select_openstack_project(cluster, [project])


async def test_select_project_with_constraints_without_metric(
    aiohttp_server, config, loop
):
    # Because the selection of projects is done randomly between the matching projects,
    # if an error was present, the right project could have been randomly picked,
    # and the test would pass even if it should not.
    # Thus, many project that should not match are created, which reduces the chances
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
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.openstack.select_openstack_project(cluster, projects)
        assert selected == projects[0]


async def test_openstack_scheduling(aiohttp_server, config, db, loop):
    prometheus = await aiohttp_server(make_prometheus({"heat_demand_zone_1": ["0.25"]}))

    project = ProjectFactory(
        spec__metrics=[MetricRef(name="heat-demand", weight=1, namespaced=False)]
    )
    cluster = MagnumClusterFactory(
        spec__constraints__project__labels=[],
        status__state=MagnumClusterState.PENDING,
        status__is_scheduled=False,
    )
    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat_demand_zone_1",
    )
    metrics_provider = GlobalMetricsProviderFactory(
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
        await scheduler.openstack.schedule_magnum_cluster(cluster)

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
        await scheduler.openstack.handle_magnum_clusters(run_once=True)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.reason.code == ReasonCode.NO_SUITABLE_RESOURCE


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
def test_cluster_match_cloud_label_constraints(cloud_type, cloud_resource):
    cloud = cloud_resource(
        spec__type=cloud_type,
        metadata__labels={"location": "IT"},
    )
    cluster = ClusterFactory(
        spec__constraints__cloud__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cloud__metrics=[],
    )
    assert match_cluster_constraints(cluster, cloud)


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
def test_cluster_not_match_cloud_label_constraints(cloud_type, cloud_resource):
    cloud = cloud_resource(spec__type=cloud_type)
    cluster = ClusterFactory(
        spec__constraints__cloud__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cloud__metrics=[],
    )
    assert not match_cluster_constraints(cluster, cloud)


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
def test_cluster_match_cloud_metric_constraints(cloud_type, cloud_resource):
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="load", weight=6.0, namespaced=False)
            ],
        }
    )

    cluster = ClusterFactory(
        spec__constraints__cloud__metrics=[MetricConstraint.parse("load > 5")],
        spec__constraints__cloud__labels=[],
    )
    fetched_metrics = {
        cloud.metadata.name: [
            QueryResult(
                metric=MetricFactory(
                    metadata__name="load",
                    metadata__namespace="system:admin",
                ),
                weight=1.0,
                value=6.0,
            )
        ]
    }
    assert match_cluster_constraints(cluster, cloud, fetched_metrics)


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
def test_cluster_not_match_cloud_metrics_constraints(cloud_type, cloud_resource):
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="load", weight=5.0, namespaced=False)
            ],
        }
    )

    cluster = ClusterFactory(
        spec__constraints__cloud__metrics=[MetricConstraint.parse("load > 5")],
        spec__constraints__cloud__labels=[],
    )
    fetched_metrics = {
        cloud.metadata.name: [
            QueryResult(
                metric=MetricFactory(
                    metadata__name="load",
                    metadata__namespace="system:admin",
                ),
                weight=1.0,
                value=5.0,
            )
        ]
    }
    assert not match_cluster_constraints(cluster, cloud, fetched_metrics)


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
def test_cluster_match_empty_cloud_constraints(cloud_type, cloud_resource):
    cloud = cloud_resource(
        spec__type=cloud_type,
    )
    cluster1 = ClusterFactory(spec__constraints=None)
    cluster2 = ClusterFactory(spec__constraints__cloud=None)
    cluster3 = ClusterFactory(
        spec__constraints__cloud__labels=None,
        spec__constraints__cloud__metrics=None,
    )

    assert match_cluster_constraints(cluster1, cloud)
    assert match_cluster_constraints(cluster2, cloud)
    assert match_cluster_constraints(cluster3, cloud)


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
    ],
)
async def test_cloud_score(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    prometheus = await aiohttp_server(make_prometheus({"test_metric_1": ["0.42"]}))
    global_prometheus = await aiohttp_server(
        make_prometheus({"test_metric_1": ["0.42"]})
    )

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="test-metric-1", weight=1.0, namespaced=False),
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="test-metric-2", weight=1.0, namespaced=False),
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="test-metric-1", weight=1.0, namespaced=True),
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="test-metric-2", weight=1.0, namespaced=True),
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    metrics = [
        GlobalMetricFactory(
            metadata__name="test-metric-1",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_1",
        ),
        GlobalMetricFactory(
            metadata__name="test-metric-2",
            spec__provider__name="test-static",
            spec__provider__metric="test_metric_2",
        ),
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
    providers = [
        MetricsProviderFactory(
            metadata__name="test-prometheus",
            spec__type="prometheus",
            spec__prometheus__url=server_endpoint(prometheus),
        ),
        MetricsProviderFactory(
            metadata__name="test-static",
            spec__type="static",
            spec__static__metrics={"test_metric_2": 0.5},
        ),
        GlobalMetricsProviderFactory(
            metadata__name="test-prometheus",
            spec__type="prometheus",
            spec__prometheus__url=server_endpoint(global_prometheus),
        ),
        GlobalMetricsProviderFactory(
            metadata__name="test-static",
            spec__type="static",
            spec__static__metrics={"test_metric_2": 0.5},
        ),
    ]

    for metric in metrics:
        await db.put(metric)

    for provider in providers:
        await db.put(provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        clouds_scores = await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)

    for ranked, cloud in zip(clouds_scores, clouds):
        assert ranked.score is not None
        assert ranked.cloud == cloud


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_global_cloud_score(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test global cloud score.

    A non-namespaced `GlobalCloud` resource cannot reference the namespaced
    `Metric` resource, see #499 for details
    """
    prometheus = await aiohttp_server(make_prometheus({"test_metric_1": ["0.42"]}))
    global_prometheus = await aiohttp_server(
        make_prometheus({"test_metric_1": ["0.42"]})
    )

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="test-metric-1", weight=1.0, namespaced=False),
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="test-metric-2", weight=1.0, namespaced=False),
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    metrics = [
        GlobalMetricFactory(
            metadata__name="test-metric-1",
            spec__provider__name="test-prometheus",
            spec__provider__metric="test_metric_1",
        ),
        GlobalMetricFactory(
            metadata__name="test-metric-2",
            spec__provider__name="test-static",
            spec__provider__metric="test_metric_2",
        ),
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
    providers = [
        MetricsProviderFactory(
            metadata__name="test-prometheus",
            spec__type="prometheus",
            spec__prometheus__url=server_endpoint(prometheus),
        ),
        MetricsProviderFactory(
            metadata__name="test-static",
            spec__type="static",
            spec__static__metrics={"test_metric_2": 0.5},
        ),
        GlobalMetricsProviderFactory(
            metadata__name="test-prometheus",
            spec__type="prometheus",
            spec__prometheus__url=server_endpoint(global_prometheus),
        ),
        GlobalMetricsProviderFactory(
            metadata__name="test-static",
            spec__type="static",
            spec__static__metrics={"test_metric_2": 0.5},
        ),
    ]

    for metric in metrics:
        await db.put(metric)

    for provider in providers:
        await db.put(provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        clouds_scores = await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)

    for ranked, cloud in zip(clouds_scores, clouds):
        assert ranked.score is not None
        assert ranked.cloud == cloud


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cloud_score_empty_metrics(
    aiohttp_server, config, loop, cloud_type, cloud_resource
):
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{"spec__type": cloud_type, f"spec__{cloud_type}__metrics": []}
        ),
        cloud_resource(
            **{"spec__type": cloud_type, f"spec__{cloud_type}__metrics": []}
        ),
    ]
    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        with pytest.raises(
            ValueError, match="List of metric references is None or empty"
        ):
            await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
    ],
)
async def test_cloud_score_missing_metric(
    aiohttp_server, db, config, loop, cloud_type, cloud_resource
):
    """Test the error handling of the Scheduler in the case of fetching a metric
    referenced in a Cloud but not present in the database.
    """
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="non-existent-metric", weight=1, namespaced=False)
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="non-existent-metric", weight=1, namespaced=True)
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)

    assert len(scored) == 0

    for cloud in clouds:
        if cloud_resource == GlobalCloudFactory:
            stored_cloud = await db.get(cloud_resource(), name=cloud.metadata.name)
        else:
            stored_cloud = await db.get(
                cloud_resource(),
                namespace=cloud.metadata.namespace,
                name=cloud.metadata.name,
            )
        assert stored_cloud.status.state == CloudState.FAILING_METRICS
        assert len(stored_cloud.status.metrics_reasons) == 1

        single_metric_reason = stored_cloud.status.metrics_reasons[
            "non-existent-metric"
        ]
        assert single_metric_reason.code == ReasonCode.UNKNOWN_METRIC


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_global_cloud_score_missing_metric(
    aiohttp_server, db, config, loop, cloud_type, cloud_resource
):
    """Test the error handling of the Scheduler in the case of fetching a metric
    referenced in a GlobalCloud but not present in the database.

    A non-namespaced `GlobalCloud` resource cannot reference the namespaced
    `Metric` resource, see #499 for details
    """
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="non-existent-metric", weight=1, namespaced=False)
                ],
            }
        )
    ]
    for cloud in clouds:
        await db.put(cloud)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)

    assert len(scored) == 0

    for cloud in clouds:
        if cloud_resource == GlobalCloudFactory:
            stored_cloud = await db.get(cloud_resource(), name=cloud.metadata.name)
        else:
            stored_cloud = await db.get(
                cloud_resource(),
                namespace=cloud.metadata.namespace,
                name=cloud.metadata.name,
            )
        assert stored_cloud.status.state == CloudState.FAILING_METRICS
        assert len(stored_cloud.status.metrics_reasons) == 1

        single_metric_reason = stored_cloud.status.metrics_reasons[
            "non-existent-metric"
        ]
        assert single_metric_reason.code == ReasonCode.UNKNOWN_METRIC


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
    ],
)
async def test_cloud_score_missing_metrics_provider(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test the error handling of the Scheduler in the case of fetching a metric
    provider referenced in a metric referenced by a Cloud but the provider is not
    present in the database.
    """
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="my-metric", weight=1, namespaced=False)
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="my-metric", weight=1, namespaced=True)
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    metrics = [
        GlobalMetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="non-existent-metric",
        ),
        MetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="non-existent-metric",
        ),
    ]
    for metric in metrics:
        await db.put(metric)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)

    assert len(scored) == 0

    for cloud in clouds:
        if cloud_resource == GlobalCloudFactory:
            stored_cloud = await db.get(cloud_resource(), name=cloud.metadata.name)
        else:
            stored_cloud = await db.get(
                cloud_resource(),
                namespace=cloud.metadata.namespace,
                name=cloud.metadata.name,
            )
        assert stored_cloud.status.state == CloudState.FAILING_METRICS
        assert len(stored_cloud.status.metrics_reasons) == 1
        assert (
            stored_cloud.status.metrics_reasons["my-metric"].code
            == ReasonCode.UNKNOWN_METRICS_PROVIDER
        )


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_global_cloud_score_missing_metrics_provider(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test the error handling of the Scheduler in the case of fetching a metric
    provider referenced in a metric referenced by a GlobalCloud but the provider
    is not present in the database.

    A non-namespaced `GlobalCloud` resource cannot reference the namespaced
    `Metric` resource, see #499 for details
    """
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="my-metric", weight=1, namespaced=False)
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    metrics = [
        GlobalMetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="non-existent-metric",
        ),
    ]
    for metric in metrics:
        await db.put(metric)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)

    assert len(scored) == 0

    for cloud in clouds:
        if cloud_resource == GlobalCloudFactory:
            stored_cloud = await db.get(cloud_resource(), name=cloud.metadata.name)
        else:
            stored_cloud = await db.get(
                cloud_resource(),
                namespace=cloud.metadata.namespace,
                name=cloud.metadata.name,
            )
        assert stored_cloud.status.state == CloudState.FAILING_METRICS
        assert len(stored_cloud.status.metrics_reasons) == 1
        assert (
            stored_cloud.status.metrics_reasons["my-metric"].code
            == ReasonCode.UNKNOWN_METRICS_PROVIDER
        )


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cloud_score_multiple_failing_metric(
    aiohttp_server, db, config, loop, cloud_type, cloud_resource
):
    """Test the error handling of the Scheduler in the case of several errors related to
    metrics referenced in two different clouds. The issues are the following:

    1st cloud:
    - 1st metric: defined metric provider not present in the database
    - 2nd metric: not present in the database

    2nd cloud:
    - 1st metric: defined metric provider returns errors.
    - 2nd metric: not present in the database.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="non-existent-metric", weight=1, namespaced=False),
                    MetricRef(name="existent-metric", weight=1, namespaced=False),
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="also-existent", weight=1, namespaced=False),
                    MetricRef(name="again-non-existent", weight=1, namespaced=False),
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    metrics = [
        GlobalMetricFactory(
            metadata__name="existent-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
        GlobalMetricFactory(
            metadata__name="also-existent",
            spec__min=0,
            spec__max=1,
            spec__provider__name="non-existent-provider",
            spec__provider__metric="my-other-metric",
        ),
    ]
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    for metric in metrics:
        await db.put(metric)
    await db.put(provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_cluster.rank_clouds(cluster, clouds)

    assert len(scored) == 0

    # 1st cloud:
    # - 1st metric: defined metric provider not present in the database
    # - 2nd metric: not present in the database
    first_cloud = (
        await db.get(
            cloud_resource(),
            name=clouds[0].metadata.name,
        )
        if cloud_resource == GlobalCloudFactory
        else await db.get(
            cloud_resource(),
            namespace=clouds[0].metadata.namespace,
            name=clouds[0].metadata.name,
        )
    )

    assert first_cloud.status.state == CloudState.FAILING_METRICS
    assert len(first_cloud.status.metrics_reasons) == 2

    assert (
        first_cloud.status.metrics_reasons["existent-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )
    assert (
        first_cloud.status.metrics_reasons["non-existent-metric"].code
        == ReasonCode.UNKNOWN_METRIC
    )

    # 2nd cloud:
    # - 1st metric: defined metric provider returns errors.
    # - 2nd metric: not present in the database
    second_cloud = (
        await db.get(
            cloud_resource(),
            name=clouds[1].metadata.name,
        )
        if cloud_resource == GlobalCloudFactory
        else await db.get(
            cloud_resource(),
            namespace=clouds[1].metadata.namespace,
            name=clouds[1].metadata.name,
        )
    )
    assert second_cloud.status.state == CloudState.FAILING_METRICS
    assert len(second_cloud.status.metrics_reasons) == 2

    assert (
        second_cloud.status.metrics_reasons["also-existent"].code
        == ReasonCode.UNKNOWN_METRICS_PROVIDER
    )
    assert (
        second_cloud.status.metrics_reasons["again-non-existent"].code
        == ReasonCode.UNKNOWN_METRIC
    )


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cloud_score_failing_metrics_provider(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test the error handling of the Scheduler in the case of fetching the value of a
    metric (referenced by a cloud) from its provider, but the connection has an issue.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="my-metric", weight=1, namespaced=False),
            ],
        }
    )
    await db.put(cloud)
    metrics = [
        GlobalMetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        )
    ]
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    for metric in metrics:
        await db.put(metric)
    await db.put(provider)

    api = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(api), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_cluster.rank_clouds(cluster, [cloud])

    assert len(scored) == 0

    stored_cloud = (
        await db.get(
            cloud_resource(),
            name=cloud.metadata.name,
        )
        if cloud_resource == GlobalCloudFactory
        else await db.get(
            cloud_resource(),
            namespace=cloud.metadata.namespace,
            name=cloud.metadata.name,
        )
    )

    assert stored_cloud.status.state == CloudState.FAILING_METRICS
    assert len(stored_cloud.status.metrics_reasons) == 1
    assert (
        stored_cloud.status.metrics_reasons["my-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cloud_score_failing_globalmetrics_provider(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test the error handling of the Scheduler in the case of fetching the value of a
    metric (referenced by a cloud) from its provider, but the connection has an issue.
    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        raise web.HTTPServiceUnavailable()

    prometheus_app = web.Application()
    prometheus_app.add_routes(routes)

    prometheus = await aiohttp_server(prometheus_app)

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="my-metric", weight=1, namespaced=False),
            ],
        }
    )
    await db.put(cloud)
    metrics = [
        GlobalMetricFactory(
            metadata__name="my-metric",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        )
    ]
    provider = GlobalMetricsProviderFactory(
        metadata__name="my-provider",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    for metric in metrics:
        await db.put(metric)
    await db.put(provider)

    api = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(api), worker_count=0)
        await scheduler.prepare(client)
        scored = await scheduler.kubernetes_cluster.rank_clouds(cluster, [cloud])

    assert len(scored) == 0

    stored_cloud = (
        await db.get(
            cloud_resource(),
            name=cloud.metadata.name,
        )
        if cloud_resource == GlobalCloudFactory
        else await db.get(
            cloud_resource(),
            namespace=cloud.metadata.namespace,
            name=cloud.metadata.name,
        )
    )
    assert stored_cloud.status.state == CloudState.FAILING_METRICS
    assert len(stored_cloud.status.metrics_reasons) == 1
    assert (
        stored_cloud.status.metrics_reasons["my-metric"].code
        == ReasonCode.UNREACHABLE_METRICS_PROVIDER
    )


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_prefer_cloud_with_global_metrics(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": 2 * ["0.4"]}))

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints=None,
    )
    cloud_miss = cloud_resource(
        **{"spec__type": cloud_type, f"spec__{cloud_type}__metrics": []}
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="my_metric", weight=1, namespaced=False),
            ],
        }
    )
    await db.put(cloud_miss)
    await db.put(cloud)

    metric = GlobalMetricFactory(
        metadata__name="my_metric",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="my_metric",
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_cluster.select_cloud(
            cluster, [cloud_miss, cloud]
        )

    assert selected == cloud


@pytest.mark.skip(reason="FIXME: The test wants further investigation.")
@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_prefer_cloud_with_namespaced_metrics(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    prometheus = await aiohttp_server(make_prometheus({"my_metric": ["0.4"]}))

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints=None,
    )
    cloud_miss = cloud_resource(
        **{"spec__type": cloud_type, f"spec__{cloud_type}__metrics": []}
    )
    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="my_metric", weight=1, namespaced=True),
            ],
        }
    )

    metric = MetricFactory(
        metadata__name="my_metric",
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

    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_cluster.select_cloud(
            cluster, [cloud_miss, cloud]
        )

    assert selected == cloud


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_select_cloud_without_metric(
    aiohttp_server, config, loop, cloud_type, cloud_resource
):
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints=None,
    )
    clouds = [
        cloud_resource(
            **{"spec__type": cloud_type, f"spec__{cloud_type}__metrics": []}
        ),
        cloud_resource(
            **{"spec__type": cloud_type, f"spec__{cloud_type}__metrics": []}
        ),
    ]

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_cluster.select_cloud(cluster, clouds)
        assert selected in clouds


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_select_cloud_not_deleted(
    aiohttp_server, config, loop, cloud_type, cloud_resource
):
    # As the finally selected cloud is chosen randomly, perform the test several times
    # to ensure that the cloud has really been chosen the right way, not by chance.
    for _ in range(10):
        index = random.randint(0, 9)
        clouds = [
            cloud_resource(
                **{
                    "spec__type": cloud_type,
                    "metadata__deleted": datetime.now(timezone.utc),
                    f"spec__{cloud_type}__metrics": [],
                }
            )
            for _ in range(10)
        ]
        clouds[index].metadata.deleted = None

        cluster = ClusterFactory(
            status__state=ClusterState.PENDING,
            spec__constraints=None,
        )

        scheduler = Scheduler("http://localhost:8080", worker_count=0)
        server = await aiohttp_server(create_app(config))

        async with Client(url=server_endpoint(server), loop=loop) as client:
            await scheduler.prepare(client)
            selected = await scheduler.kubernetes_cluster.select_cloud(cluster, clouds)

            assert selected == clouds[index]


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_select_cloud_with_constraints_without_metric(
    aiohttp_server, config, loop, cloud_type, cloud_resource
):
    # Because the selection of cloud is done randomly between the matching clouds,
    # if an error was present, the right cloud could have been randomly picked,
    # and the test would pass even if it should not.
    # Thus, many cloud that should not match are created, which reduces the chances
    # that the expected cloud is chosen, even in case of failures.
    countries = ["IT"] + fake.words(99)
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [],
                "metadata__labels": {"location": country},
            }
        )
        for country in countries
    ]
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints__cloud__labels=[LabelConstraint.parse("location is IT")],
        spec__constraints__cloud__metrics=[],
    )

    scheduler = Scheduler("http://localhost:8080", worker_count=0)
    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_cluster.select_cloud(cluster, clouds)
        assert selected == clouds[0]


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
    ],
)
async def test_cluster_select_cloud_all_unreachable_metric(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test: the scheduler picks a cloud even if all metrics providers
    are unreachable"""
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="unreachable", weight=1, namespaced=False)
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="unreachable", weight=0.1, namespaced=True)
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    metrics = [
        GlobalMetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
        MetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
    ]
    providers = [
        GlobalMetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
        MetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
    ]

    for metric in metrics:
        await db.put(metric)
    for provider in providers:
        await db.put(provider)

    random.shuffle(clouds)

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints=None,
    )
    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_cluster.select_cloud(cluster, clouds)

    assert selected in clouds


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_select_global_cloud_all_unreachable_metric(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test: the scheduler picks a cloud even if all metrics providers are unreachable.

    A non-namespaced `GlobalCloud` resource cannot reference the namespaced
    `Metric` resource, see #499 for details
    """
    clouds = [
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="unreachable", weight=1, namespaced=False)
                ],
            }
        ),
        cloud_resource(
            **{
                "spec__type": cloud_type,
                f"spec__{cloud_type}__metrics": [
                    MetricRef(name="unreachable-1", weight=0.1, namespaced=False)
                ],
            }
        ),
    ]
    for cloud in clouds:
        await db.put(cloud)

    metrics = [
        GlobalMetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
        MetricFactory(
            metadata__name="unreachable",
            spec__min=0,
            spec__max=1,
            spec__provider__name="my-provider",
            spec__provider__metric="my-metric",
        ),
    ]
    providers = [
        GlobalMetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
        MetricsProviderFactory(
            metadata__name="my-provider",
            spec__type="prometheus",
            spec__prometheus__url="http://dummyurl",
        ),
    ]

    for metric in metrics:
        await db.put(metric)
    for provider in providers:
        await db.put(provider)

    random.shuffle(clouds)

    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints=None,
    )
    server = await aiohttp_server(create_app(config))
    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_cluster.select_cloud(cluster, clouds)

    assert selected in clouds


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_select_cloud_some_unreachable_metric(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    """Test: the scheduler picks cloud from those with metrics from
    reachable providers"""
    prometheus = await aiohttp_server(make_prometheus({"heat-demand": ["0.4"] * 2}))
    cloud_metric = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="heat-demand", weight=1, namespaced=False),
            ],
        }
    )
    cloud_unreachable = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="unreachable", weight=1, namespaced=False),
            ],
        }
    )
    cloud_no_metric = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [],
        }
    )

    await db.put(cloud_metric)
    await db.put(cloud_unreachable)
    await db.put(cloud_no_metric)

    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat-demand",
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints=None,
    )
    await db.put(metric)
    await db.put(metrics_provider)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        selected = await scheduler.kubernetes_cluster.select_cloud(
            cluster, [cloud_unreachable, cloud_no_metric, cloud_metric]
        )

    assert selected == cloud_metric


@pytest.mark.parametrize(
    "cloud_type,cloud_resource",
    [
        ("openstack", CloudFactory),
        ("openstack", GlobalCloudFactory),
    ],
)
async def test_cluster_scheduling(
    aiohttp_server, config, db, loop, cloud_type, cloud_resource
):
    prometheus = await aiohttp_server(make_prometheus({"heat_demand_zone_1": ["0.25"]}))

    cloud = cloud_resource(
        **{
            "spec__type": cloud_type,
            f"spec__{cloud_type}__metrics": [
                MetricRef(name="heat-demand", weight=1, namespaced=False),
            ],
        }
    )
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        spec__constraints__cloud__labels=[],
        spec__constraints__cloud__metrics=[],
    )

    metric = GlobalMetricFactory(
        metadata__name="heat-demand",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus-zone-1",
        spec__provider__metric="heat_demand_zone_1",
    )
    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus-zone-1",
        spec__type="prometheus",
        spec__prometheus__url=f"http://{prometheus.host}:{prometheus.port}",
    )
    await db.put(metric)
    await db.put(metrics_provider)
    await db.put(cluster)
    await db.put(cloud)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.kubernetes_cluster.schedule_kubernetes_cluster(cluster)

        stored = await db.get(
            Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )

        assert stored.status.scheduled_to == resource_ref(cloud)
        assert stored.status.scheduled


async def test_cluster_scheduling_error(aiohttp_server, config, db, loop):
    cluster = ClusterFactory(
        status__state=ClusterState.PENDING,
        status__scheduled_to=None,
        spec__tosca=TOSCA_CLUSTER_MINIMAL,
    )

    await db.put(cluster)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.cluster_queue.put(cluster.metadata.uid, cluster)
        await scheduler.kubernetes_cluster.handle_kubernetes_clusters(run_once=True)

    stored = await db.get(
        Cluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.reason.code == ReasonCode.NO_SUITABLE_RESOURCE


async def test_application_degraded_state(aiohttp_server, config, db, loop):
    # Test that the Application goes in ApplicationState.DEGRADED if no cluster was
    # found, and to ApplicationState.FAILED after backoff_limit is exceeded and
    # to ApplicationState.SUCCESS if a cluster was found instead. Uses two
    # Applications with backoff_limit=1
    prometheus = await aiohttp_server(
        make_prometheus({"heat_demand_1": ("0.5", "0.25")})
    )

    degraded_and_failed = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
        spec__backoff_limit=1,
    )

    degraded_and_success = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
        spec__backoff_limit=1,
    )

    metric = GlobalMetricFactory(
        metadata__name="heat-demand-1",
        spec__min=0,
        spec__max=1,
        spec__provider__name="prometheus",
        spec__provider__metric="heat_demand_1",
    )

    metrics_provider = GlobalMetricsProviderFactory(
        metadata__name="prometheus",
        spec__type="prometheus",
        spec__prometheus__url=server_endpoint(prometheus),
    )

    cluster = ClusterFactory(
        status__state=ClusterState.ONLINE,
        spec__metrics=[MetricRef(name="heat-demand-1", weight=1, namespaced=False)],
    )

    await db.put(degraded_and_failed)
    await db.put(degraded_and_success)
    await db.put(metrics_provider)
    await db.put(metric)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        await scheduler.queue.put(degraded_and_failed.metadata.uid, degraded_and_failed)
        await scheduler.kubernetes_application.handle_kubernetes_applications(
            run_once=True
        )
        degraded_and_failed = await db.get(
            Application,
            namespace=degraded_and_failed.metadata.namespace,
            name=degraded_and_failed.metadata.name,
        )

        await scheduler.queue.put(
            degraded_and_success.metadata.uid, degraded_and_success
        )
        await scheduler.kubernetes_application.handle_kubernetes_applications(
            run_once=True
        )

        degraded_and_success = await db.get(
            Application,
            namespace=degraded_and_success.metadata.namespace,
            name=degraded_and_success.metadata.name,
        )

        assert degraded_and_success.status.state == ApplicationState.DEGRADED

        await scheduler.queue.put(degraded_and_failed.metadata.uid, degraded_and_failed)
        time.sleep(2)
        await scheduler.kubernetes_application.handle_kubernetes_applications(
            run_once=True
        )
        await db.put(cluster)
        await scheduler.queue.put(
            degraded_and_success.metadata.uid, degraded_and_success
        )
        await scheduler.kubernetes_application.handle_kubernetes_applications(
            run_once=True
        )

        degraded_and_failed = await db.get(
            Application,
            namespace=degraded_and_failed.metadata.namespace,
            name=degraded_and_failed.metadata.name,
        )
        degraded_and_success = await db.get(
            Application,
            namespace=degraded_and_success.metadata.namespace,
            name=degraded_and_success.metadata.name,
        )
        assert degraded_and_failed.status.state == ApplicationState.FAILED
        assert degraded_and_success.status.scheduled_to == resource_ref(cluster)


async def test_tenant_separation(aiohttp_server, config, db, loop):

    cluster_other_namespace = ClusterFactory(
        spec__metrics=[],
        metadata__namespace="other_namespace",
        status__state=ClusterState.ONLINE,
    )

    cluster_same_namespace = ClusterFactory(
        spec__metrics=[],
        status__state=ClusterState.ONLINE,
    )

    app = ApplicationFactory(
        spec__constraints__cluster__labels=[],
        spec__constraints__cluster__metrics=[],
        spec__constraints__cluster__custom_resources=[],
        status__state=ApplicationState.PENDING,
        status__is_scheduled=False,
    )

    await db.put(cluster_other_namespace)
    await db.put(app)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        scheduler = Scheduler(server_endpoint(server), worker_count=0)
        await scheduler.prepare(client)
        with pytest.raises(NoClusterFound):
            await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored = await db.get(Application, namespace="testing", name=app.metadata.name)

        assert not stored.status.scheduled
        assert stored.status.state == ApplicationState.PENDING

        await db.put(cluster_same_namespace)

        await scheduler.kubernetes_application.kubernetes_application_received(app)

        stored = await db.get(Application, namespace="testing", name=app.metadata.name)

        assert stored.status.scheduled_to == resource_ref(cluster_same_namespace)
        assert stored.status.kube_controller_triggered
        assert stored.status.scheduled
