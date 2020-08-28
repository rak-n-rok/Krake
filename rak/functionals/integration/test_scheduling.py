"""This module defines E2e integration tests for the scheduling algorithm of Krake.

Module covers various test scenarios including constraints and metrics.
Test constraints, metrics and metrics providers are globally defined as follows:
    Application cluster label constraints are tested with positive and negative
        expressions as follows:

            Positive expressions:
                "location is DE"
                "location = DE"
                "location=DE"
                "location == DE"
                "location in (DE,)"

            Negative expressions:
                "location is not DE"
                "location != DE"
                "location not in (DE,)"

    Cluster metrics and metrics provider were initialized by
    bootstrapping script (see: `krake_bootstrap_db`) using basic template
    defined in `docker/prometheus/bootstrap.yaml.j2`.
    Basic template defines 5 valid metrics and one valid metrics provider as follows:
        metrics:
            heat_demand_zone_[1, 2, 3, 4, 5]:
                max: 5.0
                min: 0.0
                provider:
                    prometheus

        metrics_provider:
            prometheus

    The values provided by the dummy provider for metric `heat_demand_zone_i`
    will be between i-1 and i.

    Basic template also defines 1 unreachable metrics provider and corresponding metric:
    `heat_demand_zone_unreachable`.
"""

from utils import (
    Environment,
    create_default_environment,
    create_cluster_info,
)
import random

METRICS = [
    "heat_demand_zone_1",
    "heat_demand_zone_2",
    "heat_demand_zone_3",
    "heat_demand_zone_4",
    "heat_demand_zone_5",
]
CONSTRAINT_EXPRESSIONS = {
    True: [
        "location is DE",
        "location=DE",
        "location = DE",
        "location == DE",
        "location in (DE,)",
    ],
    False: ["location is not DE", "location != DE", "location not in (DE,)"],
}


def test_create_cluster_and_app(minikube_clusters):
    """Basic end to end testing

    1. Create cluster and application;
    2. Check that the application is in RUNNING state;
    3. Ensure that the application was scheduled to the cluster;
    4. Delete the application and cluster;
    5. Check that the application and cluster were properly deleted.

    Args:
        minikube_clusters (list): Names of the Minikube backend.
    """
    cluster = random.choice(minikube_clusters)
    environment = create_default_environment([cluster])

    # 1. Create cluster and application
    # 2. Check that the application is in RUNNING state
    # (Checks 1-2 are performed automatically when entering the environment);
    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 3. Ensure that the application was scheduled to the cluster;
        app.check_running_on(cluster)

    # 4. Delete the application and cluster;
    # 5. Check that the application and cluster were properly deleted.
    # (Checks 4-5 are performed automatically when exiting the environment);


def test_scheduler_cluster_label_constraints(minikube_clusters):
    """Basic end to end testing of application cluster label constraints

    The test repeatedly creates an application and two clusters with the
    labels `location=DE` and `location=IT` randomly assigned to the clusters.
    Each time the application is created with a different cluster label
    constraint, thus creating an expectation as to which cluster it should be
    scheduled.

    The test iterates over the `CONSTRAINT_EXPRESSIONS` which contains the
    cluster label constraints for the application and a boolean indicating
    whether the application due to this constraint is expected to be scheduled
    to the cluster with `location=DE`.

    The work workflow for each iteration is as follows:

        1. Create two clusters from a config file with the cluster labels
            `location=DE` and `location=IT` (in random order);
        2. Create an application with the cluster label constraint given by
            `CONSTRAINT_EXPRESSIONS`;
        3. Ensure that the application was scheduled to the requested cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    for match, constraints in CONSTRAINT_EXPRESSIONS.items():
        for app_cluster_constraint in constraints:
            # The two clusters used in this test (randomly ordered)
            clusters = random.sample(minikube_clusters, 2)
            countries = ["DE", "IT"]

            # Determine which cluster we expect the application to be scheduled to
            requested_cluster = clusters[0]  # The DE cluster

            # 1. Create two clusters from a config file with the cluster labels
            #     `location=DE` and `location=IT` (in random order);
            # 2. Create an application with the cluster label constraint given by
            #     `CONSTRAINT_EXPRESSIONS`;
            cluster_labels = create_cluster_info(clusters, "location", countries)
            environment = create_default_environment(
                clusters,
                cluster_labels=cluster_labels,
                app_cluster_constraints=[app_cluster_constraint],
            )
            with Environment(environment) as resources:
                app = resources["Application"][0]

                # 3. Ensure that the application was scheduled to the requested cluster;
                app.check_running_on(requested_cluster)


def test_scheduler_clusters_with_metrics(minikube_clusters):
    """Basic end to end testing of clusters metrics

    Cluster metrics and metrics provider are tested multiple times (3) as follows:

        1. Create two Minikube clusters (from a config file) with a randomly
            selected metric assigned to each cluster and an application.
        2. Ensure that the application was scheduled to the expected cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    for _ in range(3):
        # The two clusters and metrics used in this test (randomly ordered)
        num_clusters = 2
        clusters = random.sample(minikube_clusters, num_clusters)
        metric_names = random.sample(set(METRICS), num_clusters)
        weights = [1] * num_clusters

        # Determine to which cluster we expect the application to be scheduled.
        # (Due to the implementation of the dummy metrics provider, the metric
        # with the highest suffix will have the highest value. Therefore
        # (and since the weights of the metrics will be the same
        # for all clusters), the cluster with the highest metric name suffix
        # is expected to be chosen by the scheduler.)
        metric_max = max(metric_names, key=lambda x: int(x[-1]))
        max_index = next(
            i for i in range(num_clusters) if metric_max == metric_names[i]
        )
        expected_cluster = clusters[max_index]

        # 1. Create two Minikube clusters (from a config file) with a randomly
        #     selected metric assigned to each cluster and an application.
        cluster_metrics = create_cluster_info(clusters, metric_names, weights)
        environment = create_default_environment(clusters, metrics=cluster_metrics)
        with Environment(environment) as resources:
            app = resources["Application"][0]

            # 2. Ensure that the application was scheduled to the expected cluster;
            app.check_running_on(expected_cluster)


def test_scheduler_clusters_one_with_metrics(minikube_clusters):
    """Basic end to end testing of clusters metrics

    Cluster metrics and metrics provider are tested multiple times (3) as follows:

        1. Create two Minikube clusters (from a config file) with a randomly
            selected metric assigned only to one randomly selected cluster,
            and an application.
            The cluster with the metric is expected to be chosen by the scheduler.
        2. Ensure that the application was scheduled to the expected cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    for _ in range(3):

        # the two clusters and one metric to be used in this test
        clusters = random.sample(minikube_clusters, 2)
        metric_names = [random.choice(METRICS)]
        weights = [1]

        # Determine to which cluster we expect the application to be scheduled.
        # (The cluster with the metric is expected to be chosen by the scheduler.)
        expected_cluster = clusters[0]

        # 1. Create two Minikube clusters (from a config file) with a randomly
        #     selected metric assigned to one cluster and an application.
        metrics_by_cluster = create_cluster_info(clusters, metric_names, weights)
        environment = create_default_environment(clusters, metrics=metrics_by_cluster)
        with Environment(environment) as resources:
            app = resources["Application"][0]

            # 2. Ensure that the application was scheduled to the expected cluster;
            app.check_running_on(expected_cluster)


def test_scheduler_cluster_label_constraints_with_metrics(minikube_clusters):
    """Basic end to end testing of application cluster label constraints with
    metrics

    Test iterates over the `CONSTRAINT_EXPRESSIONS` and applies workflow as follows:

        1. Create an application (with a cluster label constraint given from
            `CONSTRAINT_EXPRESSIONS`) and two Minikube clusters (from a config file)
            with cluster labels (randomly selected from: `location=DE`,
            `location=IT`) and randomly selected metrics.
        2. Ensure that the application was scheduled to the requested cluster;


    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """

    for match, constraints in CONSTRAINT_EXPRESSIONS.items():
        for app_cluster_constraint in constraints:
            # The two clusters, countries and metrics used in this test
            # (randomly ordered)
            num_clusters = 2
            clusters = random.sample(minikube_clusters, num_clusters)
            metric_names = random.sample(set(METRICS), num_clusters)
            weights = [1] * num_clusters
            countries = ["DE", "IT"]

            # Determine to which cluster we expect the application to be scheduled
            requested_cluster = clusters[0]  # The DE cluster

            # 1. Create an application (with a cluster label constraint given from
            # `CONSTRAINT_EXPRESSIONS`) and two Minikube clusters (from a config file)
            # with cluster labels (randomly selected from: `location=DE`,
            # `location=IT`) and randomly selected metrics.
            cluster_labels = create_cluster_info(clusters, "location", countries)
            metrics = create_cluster_info(clusters, metric_names, weights)
            environment = create_default_environment(
                clusters,
                metrics=metrics,
                cluster_labels=cluster_labels,
                app_cluster_constraints=[app_cluster_constraint],
            )
            with Environment(environment) as resources:
                app = resources["Application"][0]

                # 2. Ensure that the application was scheduled to the requested cluster;
                app.check_running_on(requested_cluster)


def test_unreachable_metrics_provider(minikube_clusters):
    """Basic end to end testing of unreachable metrics provider

    Test applies workflow as follows:

        1. Create one application, one cluster without metrics, and one with
            the metric `heat_demand_zone_unreachable`.
            The cluster without the metric is expected to be chosen by the scheduler.
        2. Ensure that the application was scheduled to the expected cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    # The two clusters and metrics used in this test (randomly ordered)
    num_clusters = 2
    clusters = random.sample(minikube_clusters, num_clusters)
    metric_names = ["heat_demand_zone_unreachable"]
    weights = [1]

    metrics_by_cluster = create_cluster_info(clusters, metric_names, weights)

    # Determine to which cluster we expect the application to be scheduled.
    # (The cluster without the metric is expected to be chosen by the scheduler.)
    expected_cluster = next(c for c in clusters if not metrics_by_cluster[c])

    # 1. Create one application, one cluster without metrics, and one with
    #     the metric `heat_demand_zone_unreachable`.
    environment = create_default_environment(clusters, metrics=metrics_by_cluster)
    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 2. Ensure that the application was scheduled to the expected cluster;
        app.check_running_on(expected_cluster)
