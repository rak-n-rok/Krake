from utils import run
import json

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


def test_createclusterandapp(minikubecluster):
    """Basic end to end testing

    We run a basic workflow in 5 steps:
    1. Create a Minikube cluster from a config file
    2. Create an application
    3. Access the application
    4. Delete the application
    5. Delete the cluster

    Args:
        minikubecluster (str): Name of the Minikube backend.

    """

    CLUSTER_NAME = minikubecluster
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


def test_app_cluster_label_constraints(minikubecluster):
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
        minikubecluster (str): Name of the Minikube backend.

    """

    cluster_label = "location=DE"
    cluster_name = minikubecluster
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
