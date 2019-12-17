from utils import run
import json
import random

KRAKE_HOMEDIR = "/home/krake"
GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"


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


def test_createclusterandapp(minikubeclusters):
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

    CLUSTER_NAME = random.choice(minikubeclusters)
    kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{CLUSTER_NAME}"

    # 1. Create a Minikube cluster from a config file
    response = run(f"rok kube cluster create {kubeconfig_path}")

    # List cluster and assert it's running
    response = run("rok kube cluster list -f json")

    cluster_list = response.json
    assert cluster_list[0]["metadata"]["name"] == CLUSTER_NAME

    # 2. Create an application
    response = run(
        "rok kube app create -f "
        f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}/echo-demo.yaml echo-demo"
    )

    # Get application details and assert it's running on the previously
    # created cluster
    response = run(
        "rok kube app get echo-demo -f json",
        condition=check_app_state(
            "RUNNING", "Unable to observe the application in a RUNNING state"
        ),
    )

    app_details = response.json
    assert app_details["status"]["running_on"]["name"] == CLUSTER_NAME

    svc_url = app_details["status"]["services"]["echo-demo"]

    # 3. Access the application
    response = run(
        f"curl {svc_url}", condition=check_return_code("Application is not reachable")
    )

    # 4. Delete the application
    response = run("rok kube app delete echo-demo")

    # Add a condition to wait for the application to be actually deleted
    response = run(
        "rok kube app list -f json",
        condition=check_empty_list("Unable to observe the application deleted"),
    )

    # 5. Delete the cluster
    response = run(f"rok kube cluster delete {CLUSTER_NAME}")

    # Add a condition to wait for the cluster to be actually deleted
    response = run(
        "rok kube cluster list -f json",
        condition=check_empty_list("Unable to observe the cluster deleted"),
    )


def test_app_cluster_label_constraints(minikubeclusters):
    """Basic end to end testing of application cluster label constraints

    Application cluster label constraints are tested with positive and negative
    expressions as follows:

        Positive expressions:
            "location is DE"
            "location = DE"
            "location == DE"
            "location in (DE,)"

        Negative expressions:
            "location is not DE"
            "location != DE"
            "location not in (DE,)"

    Test iterates over above expressions and applies following workflow:

        1. Create a Minikube cluster from a config file
            In each test iteration is used the same cluster label "location=DE"
        2. Create an application with cluster label constraint <expression>
        3. Validate application deployment
        4. Delete the application
        5. Delete the cluster

    Args:
        minikubeclusters (list): Names of the Minikube backend.

    """

    cluster_label = "location=DE"
    cluster_name = random.choice(minikubeclusters)
    kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{cluster_name}"
    expressions = {
        True: [
            "location is DE",
            "location = DE",
            "location == DE",
            "location in (DE,)",
        ],
        False: ["location is not DE", "location != DE", "location not in (DE,)"],
    }

    for match, constraints in expressions.items():
        for constraint in constraints:

            # 1. Create a Minikube cluster from a config file
            run(f"rok kube cluster create {kubeconfig_path} -l {cluster_label}")

            # 2. Create an application
            cmd_create = f"rok kube app create " \
                         f"-f {KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}/echo-demo.yaml " \
                         f"echo-demo"
            run(cmd_create.split() + ["-L", constraint])

            # 3. Validate application deployment
            # App state should be RUNNING when application cluster label constraints
            # matched cluster labels and FAILED if not matched
            state = "RUNNING" if match else "FAILED"
            reason = None if match else "NO_SUITABLE_RESOURCE"

            # Get application details and assert it's running on the previously
            # created cluster
            run(
                "rok kube app get echo-demo -f json",
                condition=check_app_state(
                    state,
                    f"Unable to observe the application in a {state} state",
                    reason=reason,
                ),
            )

            # 4. Delete the application
            run("rok kube app delete echo-demo")
            # Add a condition to wait for the application to be actually deleted
            run(
                "rok kube app list -f json",
                condition=check_empty_list("Unable to observe the application deleted"),
            )

            # 5. Delete the cluster
            run(f"rok kube cluster delete {cluster_name}")
            # Add a condition to wait for the cluster to be actually deleted
            run(
                "rok kube cluster list -f json",
                condition=check_empty_list("Unable to observe the cluster deleted"),
            )


def test_cluster_metric_provider(minikubeclusters):
    """Basic end to end testing of cluster metric and metrics provider

    Cluster metrics and metrics provider were initialized in etcd database by
    bootstrapping script (see: bootstrapping/bootstrap) based on basic template
    defined in `docker/prometheus/bootstrap.yaml.j2`.
    Basic template defines 5 metrics and one metrics provider as follows:
        metrics:
            heat_demand_zone_1:
                max: 1.0
                min: 0.0
                provider:
                    prometheus
            heat_demand_zone_2
                max: 2.0
                min: 1.0
                provider:
                    prometheus
            heat_demand_zone_3
                max: 3.0
                min: 2.0
                provider:
                    prometheus
            heat_demand_zone_4
                max: 4.0
                min: 3.0
                provider:
                    prometheus
            heat_demand_zone_5
                max: 5.0
                min: 4.0
                provider:
                    prometheus

        metrics_provider:
            prometheus

    Test randomly selects two metrics and applies following workflow:

        1. Create a Minikube clusters from a config file
            Randomly selected metric is assigned to the cluster.
            Cluster with higher zone number metric should be selected by Krake scheduler
        2. Create an application
        3. Validate application deployment
        4. Delete the application
        5. Delete the cluster

    Args:
        minikubeclusters (list): Names of the Minikube backend.

    """

    metrics = [
        "heat_demand_zone_1",
        "heat_demand_zone_2",
        "heat_demand_zone_3",
        "heat_demand_zone_4",
        "heat_demand_zone_5",
    ]
    cluster_metrics = random.sample(set(metrics), 2)

    expected_scheduled_metric = max(cluster_metrics, key=lambda x: int(x[-1]))

    # 1. Create a Minikube clusters from a config file with selected metric
    for cluster, metric in zip(minikubeclusters, cluster_metrics):

        if metric == expected_scheduled_metric:
            expected_scheduled_cluster = cluster

        kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{cluster}"
        run(f"rok kube cluster create {kubeconfig_path} --metric {metric} 1")

    # 2. Create an application
    run(
        "rok kube app create -f "
        f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}/echo-demo.yaml echo-demo"
    )

    # 3. Validate application deployment
    # Get application details and assert it's running on the expected cluster
    response = run(
        "rok kube app get echo-demo -f json",
        condition=check_app_state(
            "RUNNING", "Unable to observe the application in a RUNNING state"
        ),
    )

    app_details = response.json
    assert app_details["status"]["running_on"]["name"] == expected_scheduled_cluster

    # 4. Delete the application
    run("rok kube app delete echo-demo")
    # Add a condition to wait for the application to be actually deleted
    run(
        "rok kube app list -f json",
        condition=check_empty_list("Unable to observe the application deleted"),
    )

    # 5. Delete the clusters
    for cluster in minikubeclusters:
        run(f"rok kube cluster delete {cluster}")

    # Add a condition to wait for the cluster to be actually deleted
    run(
        "rok kube cluster list -f json",
        condition=check_empty_list("Unable to observe the cluster deleted"),
    )
