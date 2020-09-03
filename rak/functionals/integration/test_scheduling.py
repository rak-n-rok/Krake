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

    Basic template also defines 1 unreachable metrics provider and corresponding metric:
    `heat_demand_zone_unreachable`.
"""

import itertools
import string
import time
from typing import NamedTuple, List

from utils import (
    Environment,
    run,
    check_app_state,
    check_empty_list,
    check_return_code,
    create_multiple_cluster_environment,
    create_simple_environment,
)
import random

KRAKE_HOMEDIR = "/home/krake"
GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"
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
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}"
COUNTRY_CODES = [
    l1 + l2
    for l1, l2 in itertools.product(string.ascii_uppercase, string.ascii_uppercase)
]


def execute_tests(tests):
    """Execute tests

    Each test is described by application which should be deployed on defined cluster.

    Args:
        tests (List[Test]): List of tests

    """
    expected_cluster = ""

    for test in tests:
        # 1. Create a Minikube clusters from a config file with defined arguments
        for cluster in test.clusters:

            if cluster.scheduled_to:
                expected_cluster = cluster.name

            kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{cluster.name}"
            args = []
            if cluster.metrics:
                args.extend(
                    itertools.chain(
                        *[["--metric", metric, "1"] for metric in cluster.metrics]
                    )
                )
            if cluster.labels:
                args.extend(
                    itertools.chain(*[["--label", label] for label in cluster.labels])
                )
            cmd_create = f"rok kube cluster create {kubeconfig_path}"
            run(cmd_create.split() + args)

        # 2. Create an application
        args_app = []
        if test.application.cluster_label_constraints:
            args_app.extend(
                itertools.chain(
                    *[["-L", clc] for clc in test.application.cluster_label_constraints]
                )
            )
        cmd_create_app = (
            f"rok kube app create "
            f"-f {KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}/echo-demo.yaml "
            f"{test.application.name}"
        )
        run(cmd_create_app.split() + args_app)

        # 3. Validate application deployment
        # Get application details and assert it's running on the expected cluster,
        # if defined
        if expected_cluster:
            response = run(
                f"rok kube app get {test.application.name} -f json",
                retry=5,
                interval=10,
                condition=check_app_state(
                    "RUNNING", "Unable to observe the application in a RUNNING state"
                ),
            )

            app_details = response.json
            assert app_details["status"]["running_on"]["name"] == expected_cluster

            # 4. Delete the application
            run(f"rok kube app delete {test.application.name}")
            # Add a condition to wait for the application to be actually deleted
            run(
                "rok kube app list -f json",
                condition=check_empty_list("Unable to observe the application deleted"),
            )
        else:
            run(
                "rok kube app list -f json",
                condition=check_empty_list(
                    "Unable to observe the empty list of applications"
                ),
            )

        # 5. Delete the clusters
        for cluster in test.clusters:
            run(f"rok kube cluster delete {cluster.name}")

        # Add a condition to wait for the cluster to be actually deleted
        run(
            "rok kube cluster list -a -f json",
            condition=check_empty_list("Unable to observe the cluster deleted"),
        )


class Application(NamedTuple):
    name: str
    cluster_label_constraints: list = []


class Cluster(NamedTuple):
    name: str
    scheduled_to: bool = False
    labels: list = []
    metrics: list = []


class Test(NamedTuple):
    application: Application
    clusters: List[Cluster]


def test_create_cluster_and_app(minikube_clusters):
    """Basic end to end testing

    We run a basic workflow in 5 steps:
    1. Create a Minikube cluster from a config file
    2. Create an application
    3. Access the application
    4. Delete the application
    5. Delete the cluster

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    cluster = random.choice(minikube_clusters)
    execute_tests(
        [
            Test(
                application=Application(name="app-test"),
                clusters=[Cluster(name=cluster, scheduled_to=True)],
            )
        ]
    )


def test_scheduler_cluster_label_constraints(minikube_clusters):
    """Basic end to end testing of application cluster label constraints

    Test iterates over the `CONSTRAINT_EXPRESSIONS` and applies workflow as follows:

        1. Create a Minikube clusters from a config file
            The cluster labels `location=DE` and `location=IT` are randomly assigned
            to the clusters. `scheduled_to` variable is set to True if the cluster
            should be selected by the scheduler algorithm.
        2. Create an application with the cluster label constraint <expression>
        3. Validate application deployment
        4. Delete the application
        5. Delete the clusters

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    tests = []
    for match, constraints in CONSTRAINT_EXPRESSIONS.items():
        for constraint in constraints:

            random.shuffle(minikube_clusters)

            tests.append(
                Test(
                    application=Application(
                        name="app-test", cluster_label_constraints=[constraint]
                    ),
                    clusters=[
                        Cluster(
                            name=minikube_clusters[0],
                            labels=["location=DE"],
                            scheduled_to=match,
                        ),
                        Cluster(
                            name=minikube_clusters[1],
                            labels=["location=IT"],
                            scheduled_to=not match,
                        ),
                    ],
                )
            )
    execute_tests(tests)


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
    ) as resources:
        app = resources["Application"][0]

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
        run(app.delete_command())
        run(
            "rok kube app list -f json",
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


def test_kubernetes_no_migration(minikube_clusters):
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
    6. Wait and
        ensure that the application was rescheduled to the requested cluster;

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
        run(app.update_command(cluster_labels=[f"location={expected_countries[0]}"]))

        # 4. Wait and
        # ensure that the application was NOT rescheduled to the requested cluster;
        time.sleep(10)
        app.check_running_on(expected_clusters[1])

        # 5. Update the migration constraint to allow migration;
        run(app.update_command(migration=True))

        # 6. Wait and
        # ensure that the application was rescheduled to the requested cluster.
        time.sleep(10)
        app.check_running_on(expected_clusters[0])


def test_scheduler_clusters_with_metrics(minikube_clusters):
    """Basic end to end testing of clusters metrics

    Cluster metrics and metrics provider are tested multiple times (3) as follows:

        1. Create a Minikube clusters from a config file
            Randomly selected metric is assigned to the randomly selected to both
            clusters. `scheduled_to` variable is set to True if the cluster should
            be selected by the scheduler algorithm.
        2. Create an application
        3. Validate application deployment
        4. Delete the application
        5. Delete the clusters

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    tests = []
    for _ in range(3):

        random.shuffle(minikube_clusters)
        metric_clusters = random.sample(set(METRICS), 2)
        metric_max = max(metric_clusters, key=lambda x: int(x[-1]))

        tests.append(
            Test(
                application=Application(name="app-test"),
                clusters=[
                    Cluster(
                        name=minikube_clusters[0],
                        metrics=[metric_clusters[0]],
                        scheduled_to=metric_clusters[0] == metric_max,
                    ),
                    Cluster(
                        name=minikube_clusters[1],
                        metrics=[metric_clusters[1]],
                        scheduled_to=metric_clusters[1] == metric_max,
                    ),
                ],
            )
        )
    execute_tests(tests)


def test_scheduler_clusters_one_with_metrics(minikube_clusters):
    """Basic end to end testing of clusters metrics

    Cluster metrics and metrics provider are tested multiple times (3) as follows:

        1. Create a Minikube clusters from a config file
            Randomly selected metric is assigned only to one randomly selected cluster.
            `scheduled_to` variable is set to True if the cluster should
            be selected by the scheduler algorithm.
        2. Create an application
        3. Validate application deployment
        4. Delete the application
        5. Delete the clusters

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    tests = []
    for _ in range(3):

        random.shuffle(minikube_clusters)
        metric = random.choice(METRICS)

        tests.append(
            Test(
                application=Application(name="app-test"),
                clusters=[
                    Cluster(
                        name=minikube_clusters[0], metrics=[metric], scheduled_to=True
                    ),
                    Cluster(name=minikube_clusters[1], metrics=[], scheduled_to=False),
                ],
            )
        )
    execute_tests(tests)


def test_scheduler_cluster_label_constraints_with_metrics(minikube_clusters):
    """Basic end to end testing of application cluster label constraints with
    metrics

    Test iterates over the `CONSTRAINT_EXPRESSIONS` and applies workflow as follows:

        1. Create a Minikube clusters from a config file
            The cluster labels `location=DE`, `location=IT` and randomly selected metric
            are randomly assigned to the clusters. `scheduled_to` variable is set to
            True if the cluster should be selected by the scheduler algorithm.
        2. Create an application with the cluster label constraint <expression>
        3. Validate application deployment
        4. Delete the application
        5. Delete the clusters

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    tests = []
    for match, constraints in CONSTRAINT_EXPRESSIONS.items():
        for constraint in constraints:

            random.shuffle(minikube_clusters)
            metric_clusters = random.sample(set(METRICS), 2)

            tests.append(
                Test(
                    application=Application(
                        name="app-test", cluster_label_constraints=[constraint]
                    ),
                    clusters=[
                        Cluster(
                            name=minikube_clusters[0],
                            labels=["location=DE"],
                            metrics=[metric_clusters[0]],
                            scheduled_to=match,
                        ),
                        Cluster(
                            name=minikube_clusters[1],
                            labels=["location=IT"],
                            metrics=[metric_clusters[1]],
                            scheduled_to=not match,
                        ),
                    ],
                )
            )
    execute_tests(tests)


def test_unreachable_metrics_provider(minikube_clusters):
    """Basic end to end testing of unreachable metrics provider

    Test applies workflow as follows:

        1. Create a Minikube clusters from a config file
            Assign `heat_demand_zone_unreachable` metric to the randomly selected
            cluster. `scheduled_to` variable is set to True if the cluster should be
            selected by the scheduler algorithm.
        2. Create an application
        3. Validate application deployment
        4. Delete the application
        5. Delete the clusters

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    random.shuffle(minikube_clusters)
    execute_tests(
        [
            Test(
                application=Application(name="app-test"),
                clusters=[
                    Cluster(
                        name=minikube_clusters[0],
                        metrics=["heat_demand_zone_unreachable"],
                        scheduled_to=False,
                    ),
                    Cluster(
                        name=minikube_clusters[1],
                        metrics=[random.choice(METRICS)],
                        scheduled_to=True,
                    ),
                ],
            )
        ]
    )
