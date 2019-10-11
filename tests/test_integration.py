import util
import json

KRAKE_HOMEDIR = "/home/krake"


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

        app_details = response.json
        try:
            assert app_details["status"]["state"] == "RUNNING"
        except (KeyError, json.JSONDecodeError):
            raise AssertionError(error_message)

    def check_empty_list(response, error_message):
        try:
            assert response.json == []
        except json.JSONDecodeError:
            raise AssertionError(error_message)

    CLUSTER_NAME = minikubecluster
    kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{CLUSTER_NAME}"

    # 1. Create a Minikube cluster from a config file
    response = util.run(f"rok kube cluster create {kubeconfig_path}")

    # List cluster and assert it's running
    response = util.run("rok kube cluster list -f json")

    cluster_list = response.json
    assert cluster_list[0]["metadata"]["name"] == CLUSTER_NAME

    # 2. Create an application
    response = util.run(
        "rok kube app create -f "
        f"{KRAKE_HOMEDIR}/git/krake/tests/echo-demo.yaml echo-demo"
    )

    # Get application details and assert it's running on the previously
    # created cluster
    response = util.run(
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
    response = util.run(f"curl {svc_url}", retry=10, interval=1)

    # 4. Delete the application
    response = util.run("rok kube app delete echo-demo")

    # Add a condition to wait for the application to be actually deleted
    response = util.run(
        "rok kube app list -f json",
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the application deleted",
    )

    # 5. Delete the cluster
    response = util.run(f"rok kube cluster delete {CLUSTER_NAME}")

    # Add a condition to wait for the cluster to be actually deleted
    response = util.run(
        "rok kube cluster list -f json",
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the cluster deleted",
    )
