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
    This defines two valid metrics and one valid metrics provider as follows:
        metrics:
            electricity_cost_1:
                max: 1.0
                min: 0.0
                provider:
                    static_provider
            latency_1:
                max: 1.0
                min: 0.0
                provider:
                    static_provider

        metrics_provider:
            static_provider

    The configured stickiness is assumed to be 0.1.

"""
import itertools
import random
import string
import time
from utils import (
    Environment,
    create_multiple_cluster_environment,
    get_scheduling_score,
    set_static_metrics,
)

KRAKE_HOMEDIR = "/home/krake"
GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}"
METRICS = [
    "electricity_cost_1",
    "latency_1",
]
COUNTRY_CODES = [
    l1 + l2
    for l1, l2 in itertools.product(string.ascii_uppercase, string.ascii_uppercase)
]


def test_kubernetes_migration_cluster_constraints(minikube_clusters):
    """Check that an application scheduled on a cluster gets migrated
    (if neither --enable-migration nor --disable-migration has been used)
    when the cluster constraints of the application changes.

    In the test environment:
    1. Create the application, without cluster constraints and migration flag;
    2. Ensure the application was scheduled to a cluster;
    3. Update the cluster constraints to match the other cluster;
    4. Ensure that the application was rescheduled to the requested cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    # The two clusters and countries used for scheduling in this test
    clusters = random.sample(minikube_clusters, 2)
    countries = random.sample(COUNTRY_CODES, len(clusters))

    # 1. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    cluster_labels = dict(zip(clusters, [[f"location={cc}"] for cc in countries]))
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        cluster_labels=cluster_labels,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 2. Ensure the application was scheduled to a cluster;
        cluster_name = app.get_running_on()
        assert cluster_name in clusters

        # 3. Update the cluster constraints to match the other cluster;
        other_index = 0 if clusters[0] != cluster_name else 1
        app.update(cluster_labels=[f"location={countries[other_index]}"])

        # 4. Ensure that the application was rescheduled to the requested cluster;
        app.check_running_on(clusters[other_index])


def test_kubernetes_migration_at_cluster_constraint_update(minikube_clusters):
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
        3b. sleep 20 seconds
        3c. Check which cluster the application is scheduled.
        3d. Assert that the application was migrated

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """

    # The two clusters and countries used for scheduling in this test
    clusters = random.sample(minikube_clusters, 2)
    countries = random.sample(COUNTRY_CODES, len(clusters))

    # 1. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    cluster_labels = dict(zip(clusters, [[f"location={cc}"] for cc in countries]))
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        cluster_labels=cluster_labels,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

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
            app.update(cluster_labels=[f"location={countries[other_index]}"])
            num_updates += 1

            # 3b. sleep 20 seconds
            time.sleep(20)

            # 3c. Check which cluster the application is scheduled.
            running_on = app.get_running_on()
            if running_on != old_running_on:
                num_migrations += 1

            # 3d. Assert that the application was migrated
            assert num_migrations == num_updates
            old_running_on = running_on


def test_kubernetes_no_migration_cluster_constraints(minikube_clusters):
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
        minikube_clusters (list): Names of the Minikube backend.

    """
    all_clusters = random.sample(minikube_clusters, len(minikube_clusters))
    all_countries = random.sample(COUNTRY_CODES, len(all_clusters))

    # The two clusters and countries used for scheduling in this test
    expected_clusters = all_clusters[:2]
    expected_countries = all_countries[:2]

    # 1. Create the application, with cluster constraints and migration false;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in all_clusters}
    cluster_labels = dict(
        zip(all_clusters, [[f"location={cc}"] for cc in all_countries])
    )
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        cluster_labels=cluster_labels,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
        # We place the application on the second cluster initially
        app_cluster_constraints=[f"location={expected_countries[1]}"],
        app_migration=False,
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 2. Ensure that the application was scheduled to the requested cluster;
        app.check_running_on(expected_clusters[1])

        # 3. Update the cluster constraints to match the first cluster;
        app.update(cluster_labels=[f"location={expected_countries[0]}"])

        # 4. Wait and
        # ensure that the application was NOT rescheduled to the requested cluster;
        time.sleep(10)
        app.check_running_on(expected_clusters[1])

        # 5. Update the migration constraint to allow migration;
        app.update(migration=True)

        # 6. Ensure that the application was rescheduled to the requested cluster;
        app.check_running_on(expected_clusters[0])


def test_kubernetes_no_migration_metrics(minikube_clusters):
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
        minikube_clusters (list): Names of the Minikube backend.

    """
    assert len(METRICS) >= 2
    num_clusters = 2
    assert len(minikube_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(minikube_clusters, num_clusters)
    metrics = random.sample(METRICS, num_clusters)

    # 1. Set the metrics provided by the metrics provider
    metric_values = {
        metrics[0]: 0.01,
        metrics[1]: 0.1,
    }
    set_static_metrics(metric_values)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[i]: {
            metrics[i % num_clusters]: 1,
            metrics[(i + 1) % num_clusters]: 1.5,
        }
        for i in range(num_clusters)
    }
    score_cluster_1 = get_scheduling_score(clusters[0], metric_values, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], metric_values, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints but with
    # --disable-migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        metrics=metric_weights,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
        app_migration=False,
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 4. Ensure that the application was scheduled to the first cluster;
        app.check_running_on(clusters[0])

        # 5. Change the metrics so that the score of cluster 2 is higher than
        # the score of cluster 1;
        metric_values = {
            metrics[0]: 0.2,
            metrics[1]: 0.01,
        }
        set_static_metrics(metric_values)
        score_cluster_1 = get_scheduling_score(
            clusters[0], metric_values, metric_weights, scheduled_to=clusters[0]
        )
        score_cluster_2 = get_scheduling_score(
            clusters[1], metric_values, metric_weights, scheduled_to=clusters[0]
        )
        assert score_cluster_1 < score_cluster_2

        # 6. Wait and ensure that the application was NOT migrated to cluster 2;
        # sleep longer than the rescheduling interval of 60s
        time.sleep(70)
        app.check_running_on(clusters[0])

        # 7. Update the migration constraint to allow migration;
        app.update(migration=True)

        # 8. Ensure that the application was rescheduled to cluster 2;
        app.check_running_on(clusters[1])


def test_kubernetes_auto_metrics_migration(minikube_clusters):
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
        minikube_clusters (list): Names of the Minikube backend.

    """
    assert len(METRICS) >= 2
    num_clusters = 2
    assert len(minikube_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(minikube_clusters, num_clusters)
    metrics = random.sample(METRICS, num_clusters)

    # 1. Set the metrics provided by the metrics provider
    metric_values = {
        metrics[0]: 0.01,
        metrics[1]: 0.1,
    }
    set_static_metrics(metric_values)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[i]: {
            metrics[i % num_clusters]: 1,
            metrics[(i + 1) % num_clusters]: 1.5,
        }
        for i in range(num_clusters)
    }
    score_cluster_1 = get_scheduling_score(clusters[0], metric_values, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], metric_values, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        metrics=metric_weights,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 4. Ensure that the application was scheduled to the first cluster;
        app.check_running_on(clusters[0])

        # 5. Change the metrics so that the score of cluster 2 is higher than
        # the score of cluster 1;
        metric_values = {
            metrics[0]: 0.2,
            metrics[1]: 0.01,
        }
        set_static_metrics(metric_values)
        score_cluster_1 = get_scheduling_score(
            clusters[0], metric_values, metric_weights, scheduled_to=clusters[0]
        )
        score_cluster_2 = get_scheduling_score(
            clusters[1], metric_values, metric_weights, scheduled_to=clusters[0]
        )
        assert score_cluster_1 < score_cluster_2

        # 6. Wait and ensure that the application was migrated to cluster 2;
        # sleep longer than the rescheduling interval of 60s
        time.sleep(70)
        app.check_running_on(clusters[1])


def test_kubernetes_metrics_migration_at_update(minikube_clusters):
    """Check that an application scheduled on a cluster migrates at the time
    of a an update of the application due to
    changing metrics.

    In the test environment:
    1. Set the metrics provided by the metrics provider
    2. Set the cluster weights so that the score of cluster 1 is higher than
    the score of cluster 2.
    3. Create the application, without cluster constraints and migration flag;
    4. Ensure that the application was scheduled to cluster 1;
    5. Make sure that changing metric values only triggers migration once/minute
    by repeating the following steps 6 times (assuming a rescheduling interval
    of 60s):
        5a. Change the metrics so that the score of the other cluster is higher
            than the score of the cluster to which the application is scheduled;
        5b. sleep 10 seconds
        5c. Check which cluster the application is scheduled
        5d. increment a counter if the application was migrated
        5e. assert counter <= 1

    6. Make sure that changing metric values AND updating the application
    triggers migration every time, by repeating the following steps 6 times:
        6a. Change the metrics so that the score of the other cluster is higher
            than the score of the cluster to which the application is scheduled;
        6b. Update a label of the application to a new value.
        6c. sleep 10 seconds
        6d. Check which cluster the application is scheduled.
        6e. Assert that the application was migrated

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """

    def _get_other_cluster(this_cluster, clusters):
        """
        Return the cluster in clusters, which is not this_cluster.

        Args:
            this_cluster (str): name of this_cluster
            clusters (list): list of two cluster names.

        Returns:
            the name of the other cluster.
        """
        return clusters[0] if clusters[1] == this_cluster else clusters[1]

    def _get_metrics_triggering_migration(source, target):
        """
        Returns the metrics that the static metrics provider need to return in
        order for a migration to be triggered from the source to the target cluster.

        Args:
            source (str): name of the source cluster.
            target (str): name of the target cluster.

        Returns:
            dict: metrics that will trigger a migration to target from source
            (metric names as keys and metric values as values).

        """
        metrics_set_1 = {
            metrics[0]: 0.01,
            metrics[1]: 0.2,
        }
        metrics_set_2 = {
            metrics[0]: 0.2,
            metrics[1]: 0.01,
        }
        source_score = get_scheduling_score(
            source, metrics_set_1, metric_weights, scheduled_to=source
        )
        target_score = get_scheduling_score(
            target, metrics_set_1, metric_weights, scheduled_to=source
        )
        if target_score > source_score:
            return metrics_set_1
        source_score = get_scheduling_score(
            source, metrics_set_2, metric_weights, scheduled_to=source
        )
        target_score = get_scheduling_score(
            target, metrics_set_2, metric_weights, scheduled_to=source
        )
        assert target_score > source_score
        return metrics_set_2

    assert len(METRICS) >= 2
    num_clusters = 2
    assert len(minikube_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(minikube_clusters, num_clusters)
    metrics = random.sample(METRICS, num_clusters)

    # 1. Set the metrics provided by the metrics provider
    metric_values = {
        metrics[0]: 0.01,
        metrics[1]: 0.1,
    }
    set_static_metrics(metric_values)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[i]: {
            metrics[i % num_clusters]: 1,
            metrics[(i + 1) % num_clusters]: 1.5,
        }
        for i in range(num_clusters)
    }
    score_cluster_1 = get_scheduling_score(clusters[0], metric_values, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], metric_values, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        metrics=metric_weights,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 4. Ensure that the application was scheduled to the first cluster;
        app.check_running_on(clusters[0])

        # 5. Make sure that changing metric values only triggers migration once/minute
        # by repeating the following steps 6 times (assuming a rescheduling interval
        # of 60s):
        old_running_on = clusters[0]
        num_migrations = 0
        for _ in range(6):
            # 5a. Change the metrics so that the score of the other cluster is
            # higher than the score of the cluster to which the application is
            # scheduled;
            new_cluster = _get_other_cluster(old_running_on, clusters)
            metric_values = _get_metrics_triggering_migration(
                old_running_on, new_cluster
            )
            set_static_metrics(metric_values)
            score_old = get_scheduling_score(
                old_running_on,
                metric_values,
                metric_weights,
                scheduled_to=old_running_on,
            )
            score_new = get_scheduling_score(
                new_cluster, metric_values, metric_weights, scheduled_to=old_running_on
            )
            assert score_old < score_new

            # 5b. sleep 10 seconds
            time.sleep(10)

            # 5c. Check on which cluster the application is scheduled.
            # It is important not to use app.check_running_on(clusters[1]) since
            # this method waits and retries, and that functionality is tested in
            # another test method (i.e., test_kubernetes_auto_metrics_migration()).
            running_on = app.get_running_on()

            # 5d. increment a counter if the application was migrated
            if old_running_on != running_on:
                num_migrations += 1
                assert running_on == new_cluster

            # 5e. assert counter <= 1
            assert num_migrations <= 1
            old_running_on = running_on

        assert num_migrations == 1

        # 6. Make sure that changing metric values AND updating the application
        # triggers migration EVERY time, by repeating the following steps 6 times:
        old_running_on = app.get_running_on()
        num_migrations = 0
        num_updates = 0
        for _ in range(6):
            # 6a. Change the metrics so that the score of the other cluster is
            # higher than the score of the cluster to which the application is
            # scheduled;
            new_cluster = _get_other_cluster(old_running_on, clusters)
            metric_values = _get_metrics_triggering_migration(
                old_running_on, new_cluster
            )
            set_static_metrics(metric_values)
            score_old = get_scheduling_score(
                old_running_on,
                metric_values,
                metric_weights,
                scheduled_to=old_running_on,
            )
            score_new = get_scheduling_score(
                new_cluster, metric_values, metric_weights, scheduled_to=old_running_on
            )
            assert score_old < score_new

            # 6b. Update a label of the application to a new value.
            app.update(labels={"foo": new_cluster})
            num_updates += 1

            # 6c. sleep 10 seconds
            time.sleep(10)

            # 6d. Check on which cluster the application is scheduled.
            # It is important not to use app.check_running_on(clusters[1]) since
            # this method waits and retries, and that functionality is tested in
            # another test method (i.e., test_kubernetes_auto_metrics_migration()).
            running_on = app.get_running_on()
            if running_on != old_running_on:
                num_migrations += 1

            # 6e. Ensure that the application was migrated
            # Instead of just assert old_running_on != running_on we count
            # the number of updates and migrations to be able to see at what
            # point it fails in case of failure.
            assert num_migrations == num_updates
            assert old_running_on != running_on
            assert running_on == new_cluster
            old_running_on = running_on


def test_kubernetes_stickiness_migration(minikube_clusters):
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
        minikube_clusters (list): Names of the Minikube backend.

    """
    assert len(METRICS) >= 2
    num_clusters = 2
    assert len(minikube_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(minikube_clusters, num_clusters)
    metrics = random.sample(METRICS, num_clusters)

    # 1. Set the metrics provided by the metrics provider
    metric_values = {
        metrics[0]: 0.01,
        metrics[1]: 0.1,
    }
    set_static_metrics(metric_values)

    # 2. Set the cluster weights so that the score of cluster 1 is higher than
    # the score of cluster 2.
    metric_weights = {
        clusters[i]: {
            metrics[i % num_clusters]: 1,
            metrics[(i + 1) % num_clusters]: 1.5,
        }
        for i in range(num_clusters)
    }
    score_cluster_1 = get_scheduling_score(clusters[0], metric_values, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], metric_values, metric_weights)
    assert score_cluster_1 > score_cluster_2

    # 3. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        metrics=metric_weights,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 4. Ensure that the application was scheduled to the first cluster;
        app.check_running_on(clusters[0])

        # 5. Change the metrics so that if it hadn't been for stickiness
        # the score of cluster 2 would have been higher than the score of cluster 1;
        metric_values = {
            metrics[0]: 0.02,
            metrics[1]: 0.01,
        }
        set_static_metrics(metric_values)
        # Since the app is running on cluster[0], score_cluster_1 should be higher...
        score_cluster_1 = get_scheduling_score(
            clusters[0], metric_values, metric_weights, scheduled_to=clusters[0]
        )
        score_cluster_2 = get_scheduling_score(
            clusters[1], metric_values, metric_weights, scheduled_to=clusters[0]
        )
        assert score_cluster_1 > score_cluster_2
        # ... but ignoring that the app is running on cluster[0], score_cluster_2
        # should be higher.
        score_cluster_1 = get_scheduling_score(
            clusters[0], metric_values, metric_weights
        )
        score_cluster_2 = get_scheduling_score(
            clusters[1], metric_values, metric_weights
        )
        assert score_cluster_1 < score_cluster_2

        # 6. Wait and ensure that the application was not migrated to cluster 2;
        # Wait until the rescheduling interval (60s) has past.
        time.sleep(70)
        app.check_running_on(clusters[0])
