from utils import run
import json

KRAKE_HOMEDIR = "/home/krake"
GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"


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

    def check_app_running(response, error_message):

        try:
            app_details = response.json
            assert app_details["status"]["state"] == "RUNNING", error_message
        except (KeyError, json.JSONDecodeError):
            raise AssertionError(error_message)

    def check_return_code(response, error_message):
        assert response.returncode == 0, error_message

    def check_empty_list(response, error_message):
        try:
            assert response.json == [], error_message
        except json.JSONDecodeError:
            raise AssertionError(error_message)

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
        retry=10,
        interval=1,
        condition=check_app_running,
        error_message="Unable to observe the application in a RUNNING state",
    )

    app_details = response.json
    assert app_details["status"]["cluster"]["name"] == CLUSTER_NAME

    svc_url = app_details["status"]["services"]["echo-demo"]

    # 3. Access the application
    response = run(
        f"curl {svc_url}",
        retry=10,
        interval=1,
        condition=check_return_code,
        error_message="Application is not reachable",
    )

    # 4. Delete the application
    response = run("rok kube app delete echo-demo")

    # Add a condition to wait for the application to be actually deleted
    response = run(
        "rok kube app list -f json",
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the application deleted",
    )

    # 5. Delete the cluster
    response = run(f"rok kube cluster delete {CLUSTER_NAME}")

    # Add a condition to wait for the cluster to be actually deleted
    response = run(
        "rok kube cluster list -f json",
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the cluster deleted",
    )
