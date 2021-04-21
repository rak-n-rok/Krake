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

import random
import time
from functionals.utils import (
    run,
    check_empty_list,
    check_return_code,
    create_cluster_label_info,
    get_other_cluster,
    get_scheduling_score,
)
from functionals.environment import (
    Environment,
    create_simple_environment,
    create_default_environment,
    CLUSTERS_CONFIGS,
    MANIFEST_PATH,
)
from functionals.resource_definitions import ResourceKind
from functionals.resource_provider import provider, WeightedMetric, NonExistentMetric


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
    """Basic end-to-end testing

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
    with Environment(environment, creation_delay=30) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 3. Ensure that the application was scheduled to the cluster;
        app.check_running_on(cluster)

    # 4. Delete the application and cluster;
    # 5. Check that the application and cluster were properly deleted.
    # (Checks 4-5 are performed automatically when exiting the environment);


def test_create_on_other_namespace(minikube_clusters):
    """Check that resources defined in a namespace which is NOT "default" in a manifest
    given to an application are deployed to the right namespace.

    In the test environment:
    1. Create the application
    2. Ensure that the k8s resources were deployed to the right namespace
    3. Delete the Application
    4. Ensure no resource is left on the namespace

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    manifest_path = f"{MANIFEST_PATH}/echo-demo-namespaced.yaml"
    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path
    )

    def create_namespace(resources):
        error_message = "The namespace 'secondary' could not be created"
        run(
            f"kubectl --kubeconfig {kubeconfig_path} create namespace secondary",
            condition=check_return_code(error_message),
        )

    def delete_namespace(resources):
        error_message = "The namespace 'secondary' could not be deleted"
        run(
            f"kubectl --kubeconfig {kubeconfig_path} delete namespace secondary",
            condition=check_return_code(error_message),
        )

    # 1. Create the application
    with Environment(
        environment,
        before_handlers=[create_namespace],
        after_handlers=[delete_namespace],
        creation_delay=60
    ) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure that the k8s resources were deployed to the right namespace
        error_message = (
            "The deployment 'echo-demo' is not present in the 'secondary' namespace"
        )
        run(
            f"kubectl --kubeconfig {kubeconfig_path} -n secondary"
            " get deployment echo-demo",
            condition=check_return_code(error_message),
        )

        # 3. Delete the Application
        app.delete_resource()
        run(
            "rok kube app list -o json",
            condition=check_empty_list(
                "Unable to observe the empty list of applications"
            ),
        )

        # 4. Ensure no resource is left on the namespace
        time.sleep(30)  # Wait for the namespace to leave the "Terminating" state

        error_message = (
            "The deployment 'echo-demo' is still present in the 'secondary' namespace"
        )
        run(
            f"kubectl --kubeconfig {kubeconfig_path} -n secondary"
            " get deployment echo-demo",
            condition=check_return_code(error_message, expected_code=1),
        )


def test_scheduler_cluster_label_constraints(minikube_clusters):
    """Basic end-to-end testing of application cluster label constraints

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
    num_clusters = 2
    countries = ["DE", "IT"]

    for match, constraints in CONSTRAINT_EXPRESSIONS.items():

        # We expect the app to be scheduled on the DE cluster if match and
        # otherwise on the IT cluster, so we remember this index into the
        # 'countries' list (and later also into the 'clusters' list).
        expected_index = 0 if match else 1  # choose DE if match else IT

        for app_cluster_constraint in constraints:
            # The two clusters used in this test (randomly ordered)
            clusters = random.sample(minikube_clusters, num_clusters)

            # 1. Create two clusters from a config file with the cluster labels
            #     `location=DE` and `location=IT` (in random order);
            # 2. Create an application with the cluster label constraint given by
            #     `CONSTRAINT_EXPRESSIONS`;
            cluster_labels = create_cluster_label_info(clusters, "location", countries)
            environment = create_default_environment(
                clusters,
                cluster_labels=cluster_labels,
                app_cluster_constraints=[app_cluster_constraint],
            )
            with Environment(environment) as env:
                app = env.resources[ResourceKind.APPLICATION][0]

                # 3. Ensure that the application was scheduled to the requested cluster;
                app.check_running_on(clusters[expected_index])


def test_scheduler_clusters_with_metrics(minikube_clusters):
    """Basic end-to-end testing of namespaced and global cluster metrics

    Metrics and metrics provider are tested twice as follows:

        1. Set the metric values to different values in each run
        2. Create two Minikube clusters (from a config file) with both a global
        metric and a namespaced metric and an application. The clusters have
        different metric weights, which results in them having different scores.
        3. Ensure that the application was scheduled to the cluster with the
        highest score;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    # The two clusters and metrics used in this test
    num_clusters = 2
    clusters = random.sample(minikube_clusters, num_clusters)
    mp = provider.get_namespaced_static_metrics_provider()
    namespaced_static_metric = random.choice(mp.get_valued_metrics())
    gmp = provider.get_global_static_metrics_provider()
    global_static_metric = random.choice(gmp.get_valued_metrics())
    static_metrics = [namespaced_static_metric, global_static_metric]

    # Choose the metric weights for each cluster
    metric_weights = {
        clusters[0]: [
            WeightedMetric(namespaced_static_metric.metric, 1.5),
            WeightedMetric(global_static_metric.metric, 1),
        ],
        clusters[1]: [
            WeightedMetric(namespaced_static_metric.metric, 1),
            WeightedMetric(global_static_metric.metric, 1.5),
        ],
    }

    # Run the test twice and use different metric values in each iteration so
    # that another cluster is picked in each iteration.
    prev_max_score_cluster = None
    for values in [[0.8, 0.7], [0.7, 0.8]]:

        # 1. Set the metric values to different values in each run
        namespaced_static_metric.value = values[0]
        mp.set_valued_metrics(metrics=[namespaced_static_metric])
        global_static_metric.value = values[1]
        gmp.set_valued_metrics(metrics=[global_static_metric])

        # Calculate the scores and determine the cluster with the highest score.
        scores = {
            c: get_scheduling_score(c, static_metrics, metric_weights) for c in clusters
        }
        max_score_cluster = max(scores, key=scores.get)

        # (Sanity check that a different cluster is chosen in each iteration)
        assert prev_max_score_cluster != max_score_cluster

        # 2. Create two Minikube clusters (from a config file) with both a global
        # metric and a namespaced metric and an application. The clusters have
        # different metric weights, which results in them having different scores.
        environment = create_default_environment(clusters, metrics=metric_weights)
        with Environment(environment) as env:
            app = env.resources[ResourceKind.APPLICATION][0]

            # 3. Ensure that the application was scheduled to the cluster with the
            # highest score;
            app.check_running_on(max_score_cluster, within=0)

        prev_max_score_cluster = max_score_cluster


def test_scheduler_clusters_with_global_metrics(minikube_clusters):
    """Basic end-to-end testing of clusters metrics

    Cluster metrics and metrics provider are tested multiple times (3) as follows:

        1. Create two Minikube clusters (from a config file) with a randomly
            selected metric assigned to each cluster and an application.
        2. Ensure that the application was scheduled to the expected cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    for i in range(3):
        # The two clusters and metrics used in this test (randomly ordered)
        num_clusters = 2
        clusters = random.sample(minikube_clusters, num_clusters)
        gmp = provider.get_global_prometheus_metrics_provider()
        prometheus_metrics = random.sample(gmp.get_valued_metrics(), num_clusters)

        # Determine to which cluster we expect the application to be scheduled.
        # (Since the weights of the metrics will be the same
        # for all clusters), the cluster with the highest metric value
        # is expected to be chosen by the scheduler.)
        max_metric_value = max(
            prometheus_metric.value for prometheus_metric in prometheus_metrics
        )
        expected_cluster = next(
            clusters[i]
            for i in range(num_clusters)
            if prometheus_metrics[i].value == max_metric_value
        )

        # 1. Create two Minikube clusters (from a config file) with a randomly
        #     selected metric assigned to each cluster and an application.
        metric_weights = {
            clusters[i]: [WeightedMetric(prometheus_metrics[i].metric, 1)]
            for i in range(num_clusters)
        }
        environment = create_default_environment(clusters, metrics=metric_weights)
        with Environment(environment) as env:
            app = env.resources[ResourceKind.APPLICATION][0]

            # 2. Ensure that the application was scheduled to the expected cluster;
            cluster1 = env.resources[ResourceKind.CLUSTER][0]
            cluster2 = env.resources[ResourceKind.CLUSTER][1]
            cluster1_json = cluster1.get_resource()
            cluster2_json = cluster2.get_resource()
            expected_cluster_json = (
                cluster1_json if cluster1.name == expected_cluster else cluster2_json
            )
            other_cluster_json = (
                cluster1_json if cluster1.name != expected_cluster else cluster2_json
            )
            err_msg = (
                f"During the {i}-th iteration: Unable to observe that the "
                f"application {app.name} is running on cluster {expected_cluster}. "
                f"Expected cluster: {expected_cluster_json}. "
                f"Other cluster: {other_cluster_json}"
            )
            app.check_running_on(expected_cluster, error_message=err_msg)


def test_scheduler_clusters_with_one_metric(minikube_clusters):
    """Basic end-to-end testing of clusters with namespaced and global metrics

    The same test is executed six times. First three times with one cluster
    having no metrics and one cluster haveing one namespaced metric.
    Then three times with one cluster having no metrics and one cluster having
    one global metric.

    The three tests of each setup, each run as follows:

        1. Create two Minikube clusters (from a config file) (one with a
            metric and one without any) and an application.
        2. Ensure that the app was scheduled to the cluster with the metric;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    mps = [
        provider.get_namespaced_static_metrics_provider(),
        provider.get_global_static_metrics_provider(),
    ]
    for mp in mps:
        for _ in range(3):
            # The two clusters and metrics used in this test (randomly ordered)
            num_clusters = 2
            clusters = random.sample(minikube_clusters, num_clusters)
            static_metric = random.choice(mp.get_valued_metrics())

            # 1. Create two Minikube clusters (from a config file) (one with a
            #     namespaced metric and one without any) and an application.
            cluster_w_metrics = random.choice(clusters)
            metric_weights = dict.fromkeys(clusters, [])
            metric_weights[cluster_w_metrics] = [
                WeightedMetric(static_metric.metric, 1)
            ]
            environment = create_default_environment(clusters, metrics=metric_weights)
            with Environment(environment) as env:
                app = env.resources[ResourceKind.APPLICATION][0]

                # 2. Ensure that the app was scheduled to the cluster with the metric;
                app.check_running_on(cluster_w_metrics)


def test_scheduler_cluster_label_constraints_with_metrics(minikube_clusters):
    """Basic end-to-end testing of application cluster label constraints with
    metrics

    Test iterates over the `CONSTRAINT_EXPRESSIONS` and applies workflow as follows:

        1. Create an application (with a cluster label constraint given from
            `CONSTRAINT_EXPRESSIONS`) and two Minikube clusters (from a config file)
            with cluster labels (randomly selected from: `location=DE`,
            `location=IT`) and randomly selected metrics.
        2. Ensure that the application was scheduled to the cluster, which the
            application selected through its cluster label constraints. The cluster
            label constraints have priority over the rank calculated from the metrics.

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    mp = provider.get_global_prometheus_metrics_provider()
    num_clusters = 2
    countries = ["DE", "IT"]
    for match, constraints in CONSTRAINT_EXPRESSIONS.items():

        # We expect the app to be scheduled on the DE cluster if match and
        # otherwise on the IT cluster, so we remember this index into the
        # 'countries' list (and later also into the 'clusters' list).
        expected_index = 0 if match else 1  # choose DE if match else IT

        for app_cluster_constraint in constraints:
            # The two clusters, countries and metrics used in this test
            # (randomly ordered)
            clusters = random.sample(minikube_clusters, num_clusters)
            prometheus_metrics = random.sample(mp.get_valued_metrics(), num_clusters)

            # 1. Create an application (with a cluster label constraint given from
            # `CONSTRAINT_EXPRESSIONS`) and two Minikube clusters (from a config file)
            # with cluster labels (randomly selected from: `location=DE`,
            # `location=IT`) and randomly selected metrics.
            cluster_labels = create_cluster_label_info(clusters, "location", countries)
            metric_weights = {
                clusters[i]: [WeightedMetric(prometheus_metrics[i].metric, 1)]
                for i in range(num_clusters)
            }
            environment = create_default_environment(
                clusters,
                metrics=metric_weights,
                cluster_labels=cluster_labels,
                app_cluster_constraints=[app_cluster_constraint],
            )
            with Environment(environment) as env:
                app = env.resources[ResourceKind.APPLICATION][0]

                # 2. Ensure that the application was scheduled to the requested cluster;
                app.check_running_on(clusters[expected_index])


def test_one_unreachable_metrics_provider(minikube_clusters):
    """Basic end-to-end testing of unreachable metrics provider

    Test applies workflow as follows:

        1. Create one application, and two clusters with metrics - one with
            metrics from a reachable metrics provider and one with
            the metrics from an unreachable provider.
        2. Ensure that the application was scheduled to the cluster with
            the metrics provided by the reachable metrics provider;
        3. Ensure that the cluster without failing metrics is online and not reporting
            any failing metrics.
        4. Ensure that the status of the cluster with failing metrics was updated to
            notify the user of the failing metrics (state changed and list of reasons
            added).

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    # The two clusters and metrics used in this test (randomly ordered)
    num_clusters = 2
    clusters = random.sample(minikube_clusters, num_clusters)
    unreachable_mp = provider.get_global_prometheus_metrics_provider(reachable=False)
    unreachable_prometheus_metric = random.choice(unreachable_mp.get_valued_metrics())
    reachable_mp = provider.get_global_prometheus_metrics_provider()
    reachable_prometheus_metric = random.choice(reachable_mp.get_valued_metrics())
    prometheus_metrics = [unreachable_prometheus_metric, reachable_prometheus_metric]

    # Determine to which cluster we expect the application to be scheduled.
    # (The cluster with the reachable metric is expected to be chosen by the scheduler,
    # and the reachable metrics will be given to the last cluster.
    expected_cluster = clusters[-1]

    # 1. Create one application, one cluster without metrics, and one with
    #     the metric `heat_demand_zone_unreachable`.
    metric_weights = {
        clusters[i]: [WeightedMetric(prometheus_metrics[i].metric, 1)]
        for i in range(num_clusters)
    }
    environment = create_default_environment(clusters, metrics=metric_weights)
    with Environment(environment, creation_delay=30) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure that the application was scheduled to the expected cluster;
        app.check_running_on(expected_cluster)

        # 3. Ensure that the cluster without failing metrics is online and not reporting
        # any failing metrics.
        expected_cluster_res = env.get_resource_definition(
            ResourceKind.CLUSTER, expected_cluster
        )
        assert expected_cluster_res.get_state() == "ONLINE"
        assert expected_cluster_res.get_metrics_reasons() == {}

        # 4. Ensure that the status of the cluster with failing metrics was updated to
        # notify the user of the failing metrics (state changed and list of reasons
        # added).
        other_cluster_name = get_other_cluster(expected_cluster, clusters)
        other_cluster_res = env.get_resource_definition(
            ResourceKind.CLUSTER, other_cluster_name
        )

        assert other_cluster_res.get_state() == "FAILING_METRICS"
        metrics_reasons = other_cluster_res.get_metrics_reasons()
        assert "heat_demand_zone_unreachable" in metrics_reasons
        assert (
            metrics_reasons["heat_demand_zone_unreachable"]["code"]
            == "UNREACHABLE_METRICS_PROVIDER"
        )


def test_all_unreachable_metrics_provider(minikube_clusters):
    """Basic end to end testing of unreachable metrics provider

    Test applies workflow as follows:

        1. Create one application, one cluster without metrics, and one with
            the metric `heat_demand_zone_unreachable`.
            Any cluster might be chosen by the scheduler.
        2. Ensure that although all metrics providers are unreachable, the scheduler
            manages to schedule the application to one of the matching clusters.
        3. Ensure that the status of the cluster with metrics was updated to notify
            the user of the failing metrics (state changed and list of reasons added).
        4. Ensure that the cluster without metrics is not reporting any failing metrics.

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    # The two clusters and metrics used in this test (randomly ordered)
    num_clusters = 2
    clusters = random.sample(minikube_clusters, num_clusters)
    mp = provider.get_global_prometheus_metrics_provider(reachable=False)
    unreachable_metric = random.choice(mp.get_valued_metrics())

    # 1. Create one application, one cluster without metrics, and one with
    #     the metric `heat_demand_zone_unreachable`.
    metric_weights = {
        clusters[0]: [WeightedMetric(unreachable_metric.metric, 1)],
        clusters[1]: [],
    }
    environment = create_default_environment(clusters, metrics=metric_weights)
    with Environment(environment, creation_delay=20) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure that although all metrics providers are unreachable, the scheduler
        #    manages to schedule the application to one of the matching clusters.
        # The app may run on any of the clusters.
        running_on = app.get_running_on()
        assert running_on in clusters

        # 3. Ensure that the status of the cluster with metrics was updated to notify
        # the user of the failing metrics (state changed and list of reasons added).
        cluster_with_metric = env.resources[ResourceKind.CLUSTER][0]
        assert cluster_with_metric.get_state() == "FAILING_METRICS"
        metrics_reasons = cluster_with_metric.get_metrics_reasons()
        assert "heat_demand_zone_unreachable" in metrics_reasons
        assert (
            metrics_reasons["heat_demand_zone_unreachable"]["code"]
            == "UNREACHABLE_METRICS_PROVIDER"
        )

        # 4. Ensure that the cluster without metrics is not reporting any failing
        # metrics.
        cluster_wo_metric = env.resources[ResourceKind.CLUSTER][1]
        assert cluster_wo_metric.get_state() == "ONLINE"
        assert cluster_wo_metric.get_metrics_reasons() == {}


def test_metric_not_in_database(minikube_clusters):
    """Basic end to end testing of cluster referencing a metric not found in the Krake
    database.

    Test applies workflow as follows:

        1. Create one application and one cluster with a reference to metric which is
            not present in the database.
        2. Ensure that even if the metrics fetching failed, the Application is still
            deployed.
        3. Ensure that the status of the cluster with metrics was updated to notify
            the user of the failing metrics (state changed and list of reasons added).

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    # The two clusters and metrics used in this test (randomly ordered)
    num_clusters = 2
    chosen_cluster = random.sample(minikube_clusters, num_clusters)[0]

    non_existent_metric = NonExistentMetric()
    metric_weights = {
        chosen_cluster: [WeightedMetric(non_existent_metric, 1)],
    }

    # 1. Create one application and one cluster with a reference to metric which is
    # not present in the database.
    environment = create_default_environment([chosen_cluster], metrics=metric_weights)
    with Environment(environment, creation_delay=20) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure that even if the metrics fetching failed, the Application is still
        # deployed.
        assert app.get_state() == "RUNNING"
        running_on = app.get_running_on()
        assert running_on in chosen_cluster

        # 3. Ensure that the status of the cluster with metrics was updated to notify
        # the user of the failing metrics (state changed and list of reasons added).
        cluster = env.resources[ResourceKind.CLUSTER][0]
        assert cluster.get_state() == "FAILING_METRICS"
        metrics_reasons = cluster.get_metrics_reasons()
        assert non_existent_metric.name in metrics_reasons
        assert metrics_reasons[non_existent_metric.name]["code"] == "UNKNOWN_METRIC"
