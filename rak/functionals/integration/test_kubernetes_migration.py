"""This module defines E2E integration tests for the migration of applications
 between kubernetes clusters.

Module covers various test scenarios including constraints and metrics.
Test constraints, metrics and metrics providers are globally defined as follows:
    We trigger the migration by changing:
        1) the cluster label constraints of the application
        2) the manifest (e.g. label change) of the application
        3) metrics

    We also perform negative tests by:
        1) setting the migration constraint to false
        2) increasing the stickiness
    to make sure the migration does not take place.

    Cluster metrics and metrics provider were initialized by
    bootstrapping (see: `krake_bootstrap_db`) `support/static_metrics.yaml`.
    This defines three valid metrics and two valid metrics providers as follows:
        global metrics:
            electricity_cost_1:
                allowed_values = []
                max: 1.0
                min: 0.0
                provider:
                    static_provider
            green_energy_ratio_1:
                allowed_values = []
                max: 1.0
                min: 0.0
                provider:
                    static_provider

        namespaced metrics:
            existing_namespaced_metric:
                allowed_values = []
                max: 1.0
                min: 0.0
                provider:
                    static_provider_w_namespace

        global metrics providers:
            static_provider

        namespaced metrics providers:
            static_provider_w_namespace

    The configured stickiness is assumed to be 0.1.

"""
import itertools
import math
import os
import pytest
import random
import string
import time
import yaml

from functionals.utils import (
    KRAKE_HOMEDIR,
    create_cluster_label_info,
    get_scheduling_score,
    get_other_cluster,
)
from functionals.environment import GIT_DIR, Environment, create_default_environment
from functionals.resource_definitions import ResourceKind
from functionals.resource_provider import provider, WeightedMetric, StaticMetric
from datetime import datetime

COUNTRY_CODES = [
    l1 + l2
    for l1, l2 in itertools.product(string.ascii_uppercase, string.ascii_uppercase)
]


# TODO:! we cloud dynamically read in this value from krake config
def _read_value_from_config(value, default):
    options = [
        "scheduler.yaml",
        os.path.join("/etc/krake/", "scheduler.yaml"),
        os.path.join(f"{KRAKE_HOMEDIR}/{GIT_DIR}/config", "scheduler.yaml"),
    ]
    for path in options:
        if os.path.exists(path):
            with open(path, "r") as fd:
                data = yaml.safe_load(fd)
                print(data)
                return data[value]
    return default


RESCHEDULING_INTERVAL = _read_value_from_config("reschedule_after", 60)


# FIXME: krake#405:
@pytest.mark.skip(
    reason="This test fails now and then. Probably due to the bug described in "
    "issue 405. We decided to skip this test until 405 has been addressed."
)
def test_kubernetes_migration_cluster_constraints(k8s_clusters):
    """Check that an application scheduled on a cluster gets migrated
    (if neither --enable-migration nor --disable-migration has been used)
    when the cluster constraints of the application changes.

    In the test environment:
    1. Create the application, without cluster constraints and migration flag;
    2. Ensure the application was scheduled to a cluster;
    3. Update the cluster constraints to match the other cluster;
    4. Ensure that the application was rescheduled to the requested cluster;

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    # The two clusters and countries used for scheduling in this test
    clusters = random.sample(k8s_clusters, 2)
    countries = random.sample(COUNTRY_CODES, len(clusters))

    # 1. Create the application, without cluster constraints and migration flag;
    cluster_labels = create_cluster_label_info(clusters, "location", countries)
    environment = create_default_environment(clusters, cluster_labels=cluster_labels)
    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure the application was scheduled to a cluster;
        cluster_name = app.get_running_on()
        assert cluster_name in clusters

        # 3. Update the cluster constraints to match the other cluster;
        other_index = 0 if clusters[0] != cluster_name else 1
        app.update_resource(
            cluster_label_constraints=[f"location={countries[other_index]}"]
        )

        # 4. Ensure that the application was rescheduled to the requested cluster;
        app.check_running_on(clusters[other_index], within=RESCHEDULING_INTERVAL)


# FIXME: krake#405:
@pytest.mark.skip(
    reason="This test fails now and then. Probably due to the bug described in "
    "issue 405. We decided to skip this test until 405 has been addressed."
)
def test_kubernetes_migration_at_cluster_constraint_update(k8s_clusters):
    """Check that an application scheduled on a cluster migrates at the time
    of an update of the application's cluster constraints.

    This test should prove that it is not the automatic rescheduling that might
    occur right after an update of the cluster label constraints of an
    application that triggers the migration, but rather the update of the
    application's cluster label constraints itself.

    In the test environment:
    1. Create the application, without cluster constraints and migration flag;
    2. Ensure the application was scheduled to a cluster;
    3. Make sure that updating the application's cluster constraints
    triggers migration every time, by repeating the following steps 6 times:
        3a. Update a cluster label constraints of the application to match
        the other cluster.
        3b. sleep 10 seconds
        3c. Check which cluster the application is scheduled.
        3d. Assert that the application was migrated

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """

    # The two clusters and countries used for scheduling in this test
    clusters = random.sample(k8s_clusters, 2)
    countries = random.sample(COUNTRY_CODES, len(clusters))

    # 1. Create the application, without cluster constraints and migration flag;
    cluster_labels = create_cluster_label_info(clusters, "location", countries)
    environment = create_default_environment(clusters, cluster_labels=cluster_labels)

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure the application was scheduled to a cluster;
        cluster_name = app.get_running_on()
        assert cluster_name in clusters

        # 3. Make sure that updating the application's cluster constraints
        # triggers migration every time, by repeating the following steps 6 times:
        old_running_on = cluster_name
        num_migrations = 0
        num_updates = 0
        for _ in range(6):
            # 3a. Update a cluster label constraints of the application to match
            # the other cluster.
            other_index = 0 if clusters[0] != old_running_on else 1
            app.update_resource(
                cluster_label_constraints=[f"location={countries[other_index]}"]
            )
            num_updates += 1

            # 3b. sleep 10 seconds
            time.sleep(10)

            # 3c. Check which cluster the application is scheduled.
            running_on = app.get_running_on()
            if running_on != old_running_on:
                num_migrations += 1

            # 3d. Assert that the application was migrated
            assert num_migrations == num_updates
            old_running_on = running_on


def test_kubernetes_no_migration_cluster_constraints(k8s_clusters):
    """Check that an application scheduled on a cluster does not get migrated
    if its migration has been disabled.
    If the migration gets enabled it should be migrated according to its
    other constraints.

    In the test environment:
    1. Create the application, with cluster constraints and migration false;
    2. Ensure that the application was scheduled to the requested cluster;
    3. Update the cluster constraints to match the other cluster;
    4. Wait and
        ensure that the application was NOT rescheduled to the requested cluster;
    5. Update the migration constraint to allow migration;
    6. Ensure that the application was rescheduled to the requested cluster;

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    all_clusters = random.sample(k8s_clusters, len(k8s_clusters))
    all_countries = random.sample(COUNTRY_CODES, len(all_clusters))

    # The two clusters and countries used for scheduling in this test
    expected_clusters = all_clusters[:2]
    expected_countries = all_countries[:2]

    # 1. Create the application, with cluster constraints and migration false;
    cluster_labels = create_cluster_label_info(all_clusters, "location", all_countries)
    environment = create_default_environment(
        all_clusters,
        cluster_labels=cluster_labels,
        # We place the application on the second cluster initially
        app_cluster_constraints=[f"location={expected_countries[1]}"],
        app_migration=False,
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure that the application was scheduled to the requested cluster;
        app.check_running_on(expected_clusters[1], within=0)

        # 3. Update the cluster constraints to match the first cluster;
        app.update_resource(
            cluster_label_constraints=[f"location={expected_countries[0]}"],
            update_behavior=["--remove-existing-label-constraints"],
        )

        # 4. Wait and
        # ensure that the application was NOT rescheduled to the requested cluster;
        app.check_running_on(expected_clusters[1], after_delay=RESCHEDULING_INTERVAL)

        # 5. Update the migration constraint to allow migration;
        app.update_resource(migration=True)

        # 6. Ensure that the application was rescheduled to the requested cluster;
        app.check_running_on(expected_clusters[0], within=RESCHEDULING_INTERVAL)


def test_kubernetes_no_migration_metrics(k8s_clusters):
    """Check that an application scheduled on a cluster does not
    migrate due to changing metrics if migration has been disabled.

    In the test environment:
    1. Set the metrics provided by the metrics provider
    2. Set the cluster weights so that the score of cluster 1 is higher than
    the score of cluster 2.
    3. Create the application, without cluster constraints but with
    --disable-migration flag;
    4. Ensure that the application was scheduled to the first cluster;
    5. Change the metrics so that the score of cluster 2 is higher than
    the score of cluster 1;
    6. Wait and ensure that the application was NOT migrated to cluster 2;
    7. Update the migration constraint to allow migration;
    8. Ensure that the application was rescheduled to cluster 2;

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    num_clusters = 2
    assert len(k8s_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(k8s_clusters, num_clusters)
    mp = provider.get_global_static_metrics_provider()
    static_metrics = random.sample(mp.get_valued_metrics(), num_clusters)

    # 1. Set the metrics provided by the metrics provider as soon as it is created
    # when entering the Environment.
    static_metrics[0].value = 0.01
    static_metrics[1].value = 0.1
    mp.set_valued_metrics(static_metrics)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[0]: [
            WeightedMetric(static_metrics[0].metric, 1),
            WeightedMetric(static_metrics[1].metric, 1.5),
        ],
        clusters[1]: [
            WeightedMetric(static_metrics[0].metric, 1.5),
            WeightedMetric(static_metrics[1].metric, 1),
        ],
    }

    score_cluster_1 = get_scheduling_score(clusters[0], static_metrics, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], static_metrics, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints but with
    # --disable-migration flag;
    environment = create_default_environment(
        clusters, metrics=metric_weights, app_migration=False
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 4. Ensure that the application was scheduled to the first cluster;
        app.check_running_on(clusters[0], within=0)

        # 5. Change the metrics so that the score of cluster 2 is higher than
        # the score of cluster 1;
        static_metrics[0].value = 0.2
        static_metrics[1].value = 0.01
        mp.update_resource(metrics=static_metrics)
        score_cluster_1 = get_scheduling_score(
            clusters[0], static_metrics, metric_weights, scheduled_to=clusters[0]
        )
        score_cluster_2 = get_scheduling_score(
            clusters[1], static_metrics, metric_weights, scheduled_to=clusters[0]
        )
        assert score_cluster_1 < score_cluster_2

        # 6. Wait and ensure that the application was NOT migrated to cluster 2;
        # sleep longer than the RESCHEDULING_INTERVAL s
        app.check_running_on(clusters[0], after_delay=RESCHEDULING_INTERVAL + 10)

        # 7. Update the migration constraint to allow migration;
        app.update_resource(migration=True)

        # 8. Ensure that the application was rescheduled to cluster 2;
        app.check_running_on(clusters[1], within=RESCHEDULING_INTERVAL)


def test_kubernetes_auto_metrics_migration(k8s_clusters):
    """Check that an application scheduled on a cluster automatically
    migrates due to changing metrics.

    In the test environment:
    1. Set the metrics provided by the metrics provider
    2. Set the cluster weights so that the score of cluster 1 is higher than
    the score of cluster 2.
    3. Create the application, without cluster constraints and migration flag;
    4. Ensure that the application was scheduled to the first cluster;
    5. Change the metrics so that the score of cluster 2 is higher than
    the score of cluster 1;
    6. Wait and ensure that the application was migrated to cluster 2;

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    num_clusters = 2
    assert len(k8s_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(k8s_clusters, num_clusters)
    mp = provider.get_global_static_metrics_provider()
    static_metrics = random.sample(mp.get_valued_metrics(), num_clusters)

    # 1. Set the metrics provided by the metrics provider
    static_metrics[0].value = 0.01
    static_metrics[1].value = 0.1
    mp.set_valued_metrics(metrics=static_metrics)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[0]: [
            WeightedMetric(static_metrics[0].metric, 1),
            WeightedMetric(static_metrics[1].metric, 1.5),
        ],
        clusters[1]: [
            WeightedMetric(static_metrics[0].metric, 1.5),
            WeightedMetric(static_metrics[1].metric, 1),
        ],
    }
    score_cluster_1 = get_scheduling_score(clusters[0], static_metrics, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], static_metrics, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints and migration flag;
    environment = create_default_environment(clusters, metrics=metric_weights)

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 4. Ensure that the application was scheduled to the first cluster;
        app.check_running_on(clusters[0], within=0)

        # 5. Change the metrics so that the score of cluster 2 is higher than
        # the score of cluster 1;
        static_metrics[0].value = 0.2
        static_metrics[1].value = 0.01
        mp.update_resource(metrics=static_metrics)

        score_cluster_1 = get_scheduling_score(
            clusters[0], static_metrics, metric_weights, scheduled_to=clusters[0]
        )
        score_cluster_2 = get_scheduling_score(
            clusters[1], static_metrics, metric_weights, scheduled_to=clusters[0]
        )
        assert score_cluster_1 < score_cluster_2

        # 6. Wait and ensure that the application was migrated to cluster 2;
        # sleep longer than the RESCHEDULING_INTERVAL s
        app.check_running_on(clusters[1], within=RESCHEDULING_INTERVAL + 10)


def _get_metrics_triggering_migration(
    source,
    target,
    static_metrics,
    cluster_metrics,
    values_option_1=None,
    values_option_2=None,
):
    """Return static metrics that the static metrics provider need to return in
    order for a migration to be triggered from the source to the target cluster.

    Args:
        source (str): name of the source cluster.
        target (str): name of the target cluster.
        static_metrics (list[StaticMetric]): list of the metrics and their values.
        cluster_metrics (dict[str, list[WeightedMetric]]): Dictionary of cluster
            weights. The keys are the names of the clusters and each value is a
            list with the weighted metrics of the cluster.

    Returns:
        list[StaticMetrics]: list of static metrics that will trigger a migration to
            target from source
    """
    num_metrics = len(static_metrics)
    if num_metrics != 2:
        raise NotImplementedError()
    if values_option_1 is None:
        values_option_1 = [0.01, 0.2]
    metrics_option_1 = [
        StaticMetric(m.metric, values_option_1[i]) for i, m in enumerate(static_metrics)
    ]
    if values_option_2 is None:
        values_option_2 = [0.2, 0.01]
    metrics_option_2 = [
        StaticMetric(m.metric, values_option_2[i]) for i, m in enumerate(static_metrics)
    ]
    source_score = get_scheduling_score(
        source, metrics_option_1, cluster_metrics, scheduled_to=source
    )
    source_score_1 = source_score
    target_score = get_scheduling_score(
        target, metrics_option_1, cluster_metrics, scheduled_to=source
    )
    target_score_1 = target_score
    if target_score > source_score:
        return metrics_option_1
    source_score = get_scheduling_score(
        source, metrics_option_2, cluster_metrics, scheduled_to=source
    )
    target_score = get_scheduling_score(
        target, metrics_option_2, cluster_metrics, scheduled_to=source
    )
    if target_score < source_score:
        err_msg = (
            f"Using the provided metrics ({static_metrics}) and weights "
            f"({cluster_metrics}), we were unable to choose metrics that will "
            f"trigger a migration from the source cluster {source} to the target "
            f"cluster {target}. Target score "
            + str(target_score)
            + " - Source score "
            + str(source_score)
            + " | Target score "
            + str(target_score_1)
            + " - Source score "
            + str(source_score_1)
        )
        raise ValueError(err_msg)
    return metrics_option_2


def test_kubernetes_metrics_migration(k8s_clusters):
    """Check that an application scheduled on a cluster does not migrate
    as soon as the metrics change but rather only every RESCHEDULING_INTERVAL
    seconds.

    In the test environment:
    1. Set the metrics provided by the metrics provider
    2. Set the cluster weights so that the score of cluster 1 is higher than
    the score of cluster 2.
    3. Create the application, without cluster constraints and migration flag;
    4. Ensure that the application was scheduled to cluster 1;
    5. Change the metrics so that score of cluster 2 is higher than the score
    of cluster 1.
    6. Wait for the migration to cluster 2 to take place (remember its timestamp)
    7. Change the metrics so that score of cluster 1 is higher than the score
    of cluster 2. (remember this timestamp)
    8. Wait for the migration to cluster 1 to take place (remember its timestamp)
    9. Ensure that the time elapsed between the two migrations was more than
    RESCHEDULING_INTERVAL seconds.
    10. Ensure that the time elapsed between the last change of the metrics
    and the second migration was more than RESCHEDULING_INTERVAL*2/3 seconds apart.

    The fraction 2/3 in Step 10 is chosen arbitrarily, under the constraint that
    the elapsed time (between changing the metrics in step 7 and the migration
    in step 8) has to be rather large in comparison to RESCHEDULING_INTERVAL.
    Otherwise, we cannot ensure that we did not sleep for almost
    RESCHEDULING_INTERVAL seconds after Step 6 and before Step 7. If we did,
    the two migrations could have taken place at the time of changing the metrics,
    which this test should disprove.

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    num_clusters = 2
    assert len(k8s_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(k8s_clusters, num_clusters)
    mp = provider.get_global_static_metrics_provider()
    static_metrics = random.sample(mp.get_valued_metrics(), num_clusters)

    # 1. Set the metrics provided by the metrics provider
    static_metrics[0].value = 0.01
    static_metrics[1].value = 0.1
    mp.set_valued_metrics(metrics=static_metrics)

    first_cluster = clusters[0]
    second_cluster = get_other_cluster(first_cluster, clusters)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[0]: [
            WeightedMetric(static_metrics[0].metric, 1),
            WeightedMetric(static_metrics[1].metric, 1.5),
        ],
        clusters[1]: [
            WeightedMetric(static_metrics[0].metric, 1.5),
            WeightedMetric(static_metrics[1].metric, 1),
        ],
    }
    score_cluster_1_init = get_scheduling_score(
        first_cluster, static_metrics, metric_weights
    )
    score_cluster_2_init = get_scheduling_score(
        second_cluster, static_metrics, metric_weights
    )
    debug_info = {
        "k8s_clusters": k8s_clusters,
        "metric_weights": metric_weights,
        "initial_metrics": static_metrics,
        "score_cluster_1_init": score_cluster_1_init,
        "score_cluster_2_init": score_cluster_2_init,
    }
    assert score_cluster_1_init > score_cluster_2_init, f"debug_info: {debug_info}"

    # 3. Create the application, without cluster constraints and migration flag;
    environment = create_default_environment(clusters, metrics=metric_weights)

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 4. Ensure that the application was scheduled to cluster 1;
        app.check_running_on(
            first_cluster,
            within=0,
            error_message=f"App was not running on the expected cluster "
            f"{first_cluster }. debug_info: {debug_info}",
        )

        # 5. Change the metrics so that score of cluster 2 is higher than
        # the score of cluster 1.
        static_metrics = _get_metrics_triggering_migration(
            first_cluster, second_cluster, static_metrics, metric_weights
        )
        mp.update_resource(metrics=static_metrics)

        # check that the scores are as we expect
        score_first_c_b4_mig1 = get_scheduling_score(
            first_cluster,
            static_metrics,
            metric_weights,
            scheduled_to=first_cluster,
        )
        score_second_c_b4_mig1 = get_scheduling_score(
            second_cluster,
            static_metrics,
            metric_weights,
            scheduled_to=first_cluster,
        )
        debug_info.update(
            {
                "metrics_mig1": static_metrics,
                "score_first_c_b4_mig1": score_first_c_b4_mig1,
                "score_second_c_b4_mig1": score_second_c_b4_mig1,
            }
        )
        assert (
            score_first_c_b4_mig1 < score_second_c_b4_mig1
        ), f"debug_info: {debug_info}"

        # 6. Wait for the migration to cluster 2 to take place (remember its timestamp)
        app.check_running_on(
            second_cluster,
            within=RESCHEDULING_INTERVAL + 10,
            error_message=f"App was not running on the expected cluster "
            f"{second_cluster}. debug_info: {debug_info}",
        )
        migration_one = time.time()  # the approximate time of 1st migration

        # 7. Change the metrics so that score of cluster 1 is higher than the
        # score of cluster 2. (remember this timestamp)
        static_metrics = _get_metrics_triggering_migration(
            second_cluster, first_cluster, static_metrics, metric_weights
        )
        mp.update_resource(metrics=static_metrics)
        metric_change_time = time.time()

        # check that the scores are as we expect
        score_first_c_b4_mig2 = get_scheduling_score(
            first_cluster,
            static_metrics,
            metric_weights,
            scheduled_to=second_cluster,
        )
        score_second_c_b4_mig2 = get_scheduling_score(
            second_cluster,
            static_metrics,
            metric_weights,
            scheduled_to=second_cluster,
        )
        debug_info.update(
            {
                "metrics_mig2": static_metrics,
                "score_first_c_b4_mig2": score_first_c_b4_mig2,
                "score_second_c_b4_mig2": score_second_c_b4_mig2,
            }
        )
        assert (
            score_first_c_b4_mig2 > score_second_c_b4_mig2
        ), f"debug_info: {debug_info}"

        # 8. Wait for the migration to cluster 1 to take place (remember its timestamp)
        app.check_running_on(
            first_cluster,
            within=RESCHEDULING_INTERVAL + 10,
            error_message=f"app was not running on the expected cluster "
            f"{first_cluster}. debug_info: {debug_info}",
        )
        migration_two = time.time()  # approximate time of second migration

        # 9. Ensure that the time elapsed between the two migrations was more
        # than RESCHEDULING_INTERVAL seconds.
        elapsed = migration_two - migration_one
        assert elapsed >= RESCHEDULING_INTERVAL, (
            f"Two migrations took place only {elapsed} seconds apart. "
            f"Expected at least {RESCHEDULING_INTERVAL} seconds. "
            f"The first migration happened at {migration_one} and the second "
            f"at {migration_two}. "
            f"debug_info: {debug_info} app_info: {app.get_resource()}"
        )

        # 10. Ensure that the time elapsed between the last change of the metrics
        # and the second migration was more than RESCHEDULING_INTERVAL*2/3
        # seconds apart. (See docstring for an explanation of the value 2/3.)
        elapsed = migration_two - metric_change_time
        assert elapsed > RESCHEDULING_INTERVAL * 0.67, (
            f"Changing the metrics occurred too close to the second migration"
            f"to be able to tell if the test was successful. "
            f"The metrics were changed only {elapsed} seconds before the "
            f"second migration. Expected: {RESCHEDULING_INTERVAL * 0.67}. "
            f"debug_info: {debug_info}"
        )


def test_kubernetes_migration_fluctuating_metrics(k8s_clusters):
    """Check that an application scheduled on a cluster does not migrate
    as soon as the metrics change but rather only every RESCHEDULING_INTERVAL
    seconds.

    In the test environment:
    1. Set the metrics provided by the metrics provider
    2. Set the cluster weights so that the score of cluster 1 is higher than
    the score of cluster 2.
    3. Create the application, without cluster constraints and migration flag;
    4. Ensure that the application was scheduled to cluster 1;
    5. In a loop running for 1.25 * RESCHEDULING_INTERVAL seconds,
    5a. Change the metrics so that score of other cluster is higher than the score
    of current cluster.
    5b. Wait for the migration to other cluster to take place (remember its timestamp)
    5c. Ensure the time since previous migration >= RESCHEDULING_INTERVAL
    6. Ensure that the number of migrations >= 5.

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    num_clusters = 2
    assert len(k8s_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(k8s_clusters, num_clusters)
    mp = provider.get_global_static_metrics_provider()
    static_metrics = random.sample(mp.get_valued_metrics(), num_clusters)

    # 1. Set the metrics provided by the metrics provider
    static_metrics[0].value = 0.9
    static_metrics[1].value = 0.1
    mp.set_valued_metrics(metrics=static_metrics)

    first_cluster = clusters[0]
    second_cluster = get_other_cluster(first_cluster, clusters)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[0]: [
            WeightedMetric(static_metrics[0].metric, 10),
            WeightedMetric(static_metrics[1].metric, 1),
        ],
        clusters[1]: [
            WeightedMetric(static_metrics[0].metric, 1),
            WeightedMetric(static_metrics[1].metric, 10),
        ],
    }
    score_cluster_1_init = get_scheduling_score(
        first_cluster, static_metrics, metric_weights
    )
    score_cluster_2_init = get_scheduling_score(
        second_cluster, static_metrics, metric_weights
    )
    assert score_cluster_1_init > score_cluster_2_init

    # 3. Create the application, without cluster constraints and migration flag;
    environment = create_default_environment(clusters, metrics=metric_weights)

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 4. Ensure that the application was scheduled to cluster 1;
        app.check_running_on(first_cluster, within=0)

        this_cluster = first_cluster
        next_cluster = second_cluster

        # 5. In a loop running for 4.8 * RESCHEDULING_INTERVAL seconds,
        num_migrations = 0
        num_intervals = 4.8
        app_creation_time = 5
        previous_migration_time = None
        start_time = time.time()
        while time.time() - start_time < num_intervals * (
            RESCHEDULING_INTERVAL + app_creation_time
        ):
            # while time.time() - start_time < num_intervals * (RESCHEDULING_INTERVAL):
            # 5a. Change the metrics so that score of other cluster is higher
            # than the score of current cluster.
            static_metrics = _get_metrics_triggering_migration(
                this_cluster,
                next_cluster,
                static_metrics,
                metric_weights,
                values_option_1=[0.1, 0.9],
                values_option_2=[0.9, 0.1],
            )
            mp.update_resource(metrics=static_metrics)

            # 5b. Wait for the migration to other cluster to take place
            # (remember its timestamp)
            app.check_running_on(
                next_cluster, within=RESCHEDULING_INTERVAL + app_creation_time
            )
            migration_time = time.time()  # the approximate time of migration
            num_migrations += 1

            # 5c. Ensure the time since previous migration >= RESCHEDULING_INTERVAL
            if previous_migration_time:
                app_dict = app.get_resource()
                scheduled_datetime = datetime.strptime(
                    app_dict["status"]["scheduled"], "%Y-%m-%dT%H:%M:%S.%f%z"
                )
                assert (
                    datetime.timestamp(scheduled_datetime) - previous_migration_time
                    >= RESCHEDULING_INTERVAL
                )
                assert datetime.timestamp(
                    scheduled_datetime
                ) - previous_migration_time <= RESCHEDULING_INTERVAL + (
                    1.25 * RESCHEDULING_INTERVAL
                )

            # set up the loop variables for the next iteration of the loop
            this_cluster, next_cluster = next_cluster, this_cluster
            previous_migration_time = migration_time

        # 6. Ensure that the number of migrations == expected_num_migrations.
        expected_num_migrations = math.ceil(num_intervals)
        assert num_migrations >= expected_num_migrations, (
            f"There were {num_migrations} migrations within "
            f"{num_intervals * RESCHEDULING_INTERVAL} seconds. "
            f"Expected: {expected_num_migrations}. actual time taken:"
            f" {(time.time() - start_time)}"
        )


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
def test_kubernetes_metrics_migration_at_update(k8s_clusters):
    """Check that an application scheduled on a cluster migrates at the time
    of a user's update of the application if the metrics have changed.

    In the test environment:
    1. Set the metrics provided by the metrics provider
    2. Set the cluster weights so that the score of cluster 1 is higher than
    the score of cluster 2.
    3. Create the application, without cluster constraints and migration flag;
    4. Ensure that the application was scheduled to cluster 1;
    5. Change the metrics so that score of cluster 2 is higher than the score
    of cluster 1.
    6. Ensure that the migration to cluster 2 takes place in a timely fashion and
    remember its timestamp.
    7. Wait some seconds for all resulting updates to be executed.
    8. Change the metrics so that score of cluster 1 is higher than the score
    of cluster 2.
    9. Update the application with a label (which in itself does not cause migration)
    10. Ensure that the migration to cluster 1 takes place in a timely fashion and
    remember its timestamp.
    11. Ensure that the time elapsed between the two migrations was less than
    RESCHEDULING_INTERVAL seconds.

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    num_clusters = 2
    assert len(k8s_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(k8s_clusters, num_clusters)
    mp = provider.get_global_static_metrics_provider()
    static_metrics = random.sample(mp.get_valued_metrics(), num_clusters)

    # 1. Set the metrics provided by the metrics provider
    static_metrics[0] = 0.01
    static_metrics[1] = 0.1
    mp.set_valued_metrics(metrics=static_metrics)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[0]: [
            WeightedMetric(static_metrics[0].metric, 1),
            WeightedMetric(static_metrics[1].metric, 1.5),
        ],
        clusters[1]: [
            WeightedMetric(static_metrics[0].metric, 1.5),
            WeightedMetric(static_metrics[1].metric, 1),
        ],
    }
    score_cluster_1 = get_scheduling_score(clusters[0], static_metrics, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], static_metrics, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints and migration flag;
    environment = create_default_environment(clusters, metrics=metric_weights)

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 4. Ensure that the application was scheduled to cluster 1;
        first_cluster = clusters[0]
        app.check_running_on(first_cluster, within=0)

        second_cluster = get_other_cluster(first_cluster, clusters)

        # 5. Change the metrics so that score of cluster 2 is higher than the score
        # of cluster 1.
        static_metrics = _get_metrics_triggering_migration(
            first_cluster, second_cluster, static_metrics, metric_weights
        )
        mp.update_resource(metrics=static_metrics)

        # check that the scores are as we expect
        score_first = get_scheduling_score(
            first_cluster, static_metrics, metric_weights, scheduled_to=first_cluster
        )
        score_second = get_scheduling_score(
            second_cluster, static_metrics, metric_weights, scheduled_to=first_cluster
        )
        assert score_first < score_second

        # 6. Ensure that the migration to cluster 2 takes place in a timely fashion and
        # remember its timestamp.
        app.check_running_on(second_cluster, within=RESCHEDULING_INTERVAL + 10)
        first_migration = time.time()  # the approximate time of 1st migration

        # 7. Wait some seconds for all resulting updates to be executed.
        time.sleep(10)

        # 8. Change the metrics so that score of cluster 1 is higher than the score
        # of cluster 2.
        static_metrics = _get_metrics_triggering_migration(
            second_cluster, first_cluster, static_metrics, metric_weights
        )
        mp.update_resource(metrics=static_metrics)

        # check that the scores are as we expect
        score_first = get_scheduling_score(
            first_cluster, static_metrics, metric_weights, scheduled_to=second_cluster
        )
        score_second = get_scheduling_score(
            second_cluster, static_metrics, metric_weights, scheduled_to=second_cluster
        )
        assert score_second < score_first

        # 9. Update the application with a label (not in itself causing migration)
        app.update_resource(labels={"foo": second_cluster})

        # 10. Ensure that the migration to cluster 1 takes place in a timely fashion and
        # remember its timestamp.
        app.check_running_on(first_cluster, within=RESCHEDULING_INTERVAL)
        second_migration = time.time()  # approximate time of second migration

        # 11. Ensure that the time elapsed between the two migrations was less than
        # RESCHEDULING_INTERVAL seconds.
        elapsed = second_migration - first_migration
        assert elapsed < RESCHEDULING_INTERVAL, (
            f"Two migrations took place {elapsed} seconds apart. "
            f"Expected less than {RESCHEDULING_INTERVAL} seconds."
        )


def test_kubernetes_stickiness_migration(k8s_clusters):
    """Check that an application scheduled to a cluster does not
    migrate due to changing metrics if the stickiness prevents it.

    In the test environment:
    1. Set the metrics provided by the metrics provider
    2. Set the cluster weights so that the score of cluster 1 is higher than
    the score of cluster 2.
    3. Create the application, without cluster constraints and migration flag;
    4. Ensure that the application was scheduled to the first cluster;
    5. Change the metrics so that if it hadn't been for stickiness
    the score of cluster 2 would have been higher than the score of cluster 1;
    6. Wait and ensure that the application was not migrated to cluster 2;

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    num_clusters = 2
    assert len(k8s_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(k8s_clusters, num_clusters)
    mp = provider.get_global_static_metrics_provider()
    static_metrics = random.sample(mp.get_valued_metrics(), num_clusters)

    # 1. Set the metrics provided by the metrics provider as soon as it is created
    # when entering the Environment.
    static_metrics[0].value = 0.01
    static_metrics[1].value = 0.1
    mp.set_valued_metrics(static_metrics)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[0]: [
            WeightedMetric(static_metrics[0].metric, 1),
            WeightedMetric(static_metrics[1].metric, 1.5),
        ],
        clusters[1]: [
            WeightedMetric(static_metrics[0].metric, 1.5),
            WeightedMetric(static_metrics[1].metric, 1),
        ],
    }
    cluster_1 = clusters[0]
    cluster_2 = clusters[1]
    score_cluster_1 = get_scheduling_score(cluster_1, static_metrics, metric_weights)
    score_cluster_2 = get_scheduling_score(cluster_2, static_metrics, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints and migration flag;
    environment = create_default_environment(clusters, metrics=metric_weights)

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 4. Ensure that the application was scheduled to cluster 1;
        app.check_running_on(cluster_1, within=0)

        # 5. Change the metrics so that if it hadn't been for stickiness
        # the score of cluster 2 would have been higher than the score of cluster 1;
        static_metrics[0].value = 0.02
        static_metrics[1].value = 0.01
        mp.update_resource(metrics=static_metrics)

        # Sanity checks:
        # Since the app is running on cluster_1, score_cluster_1 should be higher...
        score_cluster_1 = get_scheduling_score(
            cluster_1, static_metrics, metric_weights, scheduled_to=cluster_1
        )
        score_cluster_2 = get_scheduling_score(
            cluster_2, static_metrics, metric_weights, scheduled_to=cluster_1
        )
        assert score_cluster_1 > score_cluster_2
        # ... but ignoring that the app is running on cluster_1, score_cluster_2
        # should be higher.
        score_cluster_1_no_stickiness = get_scheduling_score(
            cluster_1, static_metrics, metric_weights
        )
        score_cluster_2_no_stickiness = get_scheduling_score(
            cluster_2, static_metrics, metric_weights
        )
        assert score_cluster_1_no_stickiness < score_cluster_2_no_stickiness

        # 6. Wait and ensure that the application was not migrated to cluster 2;
        # Wait until the RESCHEDULING_INTERVAL s have past.
        observed_metrics = mp.read_metrics()
        msg = (
            f"Cluster weights: {metric_weights}. "
            f"Expected metrics: {static_metrics}. "
            f"Observed metrics: {observed_metrics}. "
            f"Score expected cluster: {score_cluster_1}. "
            f"Score other cluster: {score_cluster_2}. "
            f"Score expected cluster w/o stickiness: "
            f"{score_cluster_1_no_stickiness}. "
            f"Score other cluster w/o stickiness: "
            f"{score_cluster_2_no_stickiness}. "
        )
        assert all(
            observed_metrics[static_metric.metric.name] == static_metric.value
            for static_metric in static_metrics
        ), msg
        msg = (
            f"The app was not running on the expected cluster {cluster_1} "
            f"after {RESCHEDULING_INTERVAL + 10} seconds. " + msg
        )
        app.check_running_on(
            cluster_1, after_delay=RESCHEDULING_INTERVAL + 10, error_message=msg
        )
