"""This module defines E2e integration tests for the Krake client.

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
from typing import NamedTuple, List

from utils import run
import json
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


def check_app_state(state, error_message, reason=None):
    def validate(response):
        try:
            app_details = response.json
            assert app_details["status"]["state"] == state, error_message
            if reason:
                assert app_details["status"]["reason"]["code"] == reason, error_message
        except (KeyError, json.JSONDecodeError):
            raise AssertionError(error_message)

    return validate


def check_return_code(error_message):
    def validate(response):
        assert response.returncode == 0, error_message

    return validate


def check_empty_list(error_message):
    def validate(response):
        try:
            assert response.json == [], error_message
        except json.JSONDecodeError:
            raise AssertionError(error_message)

    return validate


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


def test_create_cluster_and_app(minikubeclusters):
    """Basic end to end testing

    We run a basic workflow in 5 steps:
    1. Create a Minikube cluster from a config file
    2. Create an application
    3. Access the application
    4. Delete the application
    5. Delete the cluster

    Args:
        minikubeclusters (list): Names of the Minikube backend.

    """
    cluster = random.choice(minikubeclusters)
    execute_tests(
        [
            Test(
                application=Application(name="app-test"),
                clusters=[Cluster(name=cluster, scheduled_to=True)],
            )
        ]
    )


def test_scheduler_cluster_label_constraints(minikubeclusters):
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
        minikubeclusters (list): Names of the Minikube backend.

    """
    tests = []
    for match, constraints in CONSTRAINT_EXPRESSIONS.items():
        for constraint in constraints:

            random.shuffle(minikubeclusters)

            tests.append(
                Test(
                    application=Application(
                        name="app-test", cluster_label_constraints=[constraint]
                    ),
                    clusters=[
                        Cluster(
                            name=minikubeclusters[0],
                            labels=["location=DE"],
                            scheduled_to=match,
                        ),
                        Cluster(
                            name=minikubeclusters[1],
                            labels=["location=IT"],
                            scheduled_to=not match,
                        ),
                    ],
                )
            )
    execute_tests(tests)


def test_scheduler_clusters_with_metrics(minikubeclusters):
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
        minikubeclusters (list): Names of the Minikube backend.

    """
    tests = []
    for _ in range(3):

        random.shuffle(minikubeclusters)
        metric_clusters = random.sample(set(METRICS), 2)
        metric_max = max(metric_clusters, key=lambda x: int(x[-1]))

        tests.append(
            Test(
                application=Application(name="app-test"),
                clusters=[
                    Cluster(
                        name=minikubeclusters[0],
                        metrics=[metric_clusters[0]],
                        scheduled_to=metric_clusters[0] == metric_max,
                    ),
                    Cluster(
                        name=minikubeclusters[1],
                        metrics=[metric_clusters[1]],
                        scheduled_to=metric_clusters[1] == metric_max,
                    ),
                ],
            )
        )
    execute_tests(tests)


def test_scheduler_clusters_one_with_metrics(minikubeclusters):
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
        minikubeclusters (list): Names of the Minikube backend.

    """
    tests = []
    for _ in range(3):

        random.shuffle(minikubeclusters)
        metric = random.choice(METRICS)

        tests.append(
            Test(
                application=Application(name="app-test"),
                clusters=[
                    Cluster(
                        name=minikubeclusters[0], metrics=[metric], scheduled_to=True
                    ),
                    Cluster(name=minikubeclusters[1], metrics=[], scheduled_to=False),
                ],
            )
        )
    execute_tests(tests)


def test_scheduler_cluster_label_constraints_with_metrics(minikubeclusters):
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
        minikubeclusters (list): Names of the Minikube backend.

    """
    tests = []
    for match, constraints in CONSTRAINT_EXPRESSIONS.items():
        for constraint in constraints:

            random.shuffle(minikubeclusters)
            metric_clusters = random.sample(set(METRICS), 2)

            tests.append(
                Test(
                    application=Application(
                        name="app-test", cluster_label_constraints=[constraint]
                    ),
                    clusters=[
                        Cluster(
                            name=minikubeclusters[0],
                            labels=["location=DE"],
                            metrics=[metric_clusters[0]],
                            scheduled_to=match,
                        ),
                        Cluster(
                            name=minikubeclusters[1],
                            labels=["location=IT"],
                            metrics=[metric_clusters[1]],
                            scheduled_to=not match,
                        ),
                    ],
                )
            )
    execute_tests(tests)


def test_unreachable_metrics_provider(minikubeclusters):
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
        minikubeclusters (list): Names of the Minikube backend.

    """
    random.shuffle(minikubeclusters)
    execute_tests(
        [
            Test(
                application=Application(name="app-test"),
                clusters=[
                    Cluster(
                        name=minikubeclusters[0],
                        metrics=["heat_demand_zone_unreachable"],
                        scheduled_to=False,
                    ),
                    Cluster(
                        name=minikubeclusters[1],
                        metrics=[random.choice(METRICS)],
                        scheduled_to=True,
                    ),
                ],
            )
        ]
    )
