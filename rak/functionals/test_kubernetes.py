import json
from rak.test_utils import run


KRAKE_HOMEDIR = "/home/krake"
GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"


def test_create_cluster_and_app(host, minikubecluster):
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

    kubeconfig = f"{KRAKE_HOMEDIR}/clusters/config/{minikubecluster}"

    # 1. Create a Minikube cluster from a config file
    run(f"rok kube cluster create {kubeconfig}", host)

    # List cluster and assert it's running
    cluster_list = run("rok kube cluster list -f json", host).json
    assert cluster_list[0]["metadata"]["name"] == minikubecluster

    # 2. Create an application
    manifest = f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}/echo-demo.yaml"
    run(f"rok kube app create -f {manifest} echo-demo", host)

    # Get application details and assert it's running on the previously
    # created cluster
    app_details = run(
        "rok kube app get echo-demo -f json",
        host=host,
        retry=10,
        interval=1,
        condition=check_app_running,
        error_message="Unable to observe the application in a RUNNING state",
    ).json
    assert app_details["status"]["running_on"]["name"] == minikubecluster

    service_endpoint = app_details["status"]["services"]["echo-demo"]

    # 3. Access the application
    run(
        f"curl {service_endpoint}",
        host=host,
        retry=10,
        interval=1,
        condition=check_return_code,
        error_message="Application is not reachable",
    )

    # 4. Delete the application
    run("rok kube app delete echo-demo", host)

    # Add a condition to wait for the application to be actually deleted
    run(
        "rok kube app list -f json",
        host=host,
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the application deleted",
    )

    # 5. Delete the cluster
    run(f"rok kube cluster delete {minikubecluster}", host)

    # Add a condition to wait for the cluster to be actually deleted
    run(
        "rok kube cluster list -f json",
        host=host,
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the cluster deleted",
    )
