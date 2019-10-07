import util
import logging
import json

logging.basicConfig(level=logging.DEBUG)

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

    def check_app_running(response):
        try:
            app_details = json.loads(response)
            if app_details["status"]["state"] == "RUNNING":
                return True
        except (KeyError, json.JSONDecodeError):
            return False

    def check_empty_list(response):
        try:
            if json.loads(response) == []:
                return True
        except json.JSONDecodeError:
            return False

    CLUSTER_NAME = minikubecluster
    kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{CLUSTER_NAME}"

    # 1. Create a Minikube cluster from a config file
    response = util.run(f"rok kube cluster create {kubeconfig_path}")
    logging.info("response from the command: %s\n", response)

    # List cluster and assert it's running
    response = util.run("rok kube cluster list -f json")
    logging.info("response from the command: %s\n", response)

    cluster_list = json.loads(response)
    assert cluster_list[0]["metadata"]["name"] == CLUSTER_NAME

    # 2. Create an application
    response = util.run(
        f"rok kube app create -f \
        {KRAKE_HOMEDIR}/git/krake/tests/echo-demo.yaml echo-demo"
    )
    logging.info("response from the command: %s\n", response)

    # Get application details and assert it's running on the previously
    # created cluster
    response = util.run(
        "rok kube app get echo-demo -f json",
        retry=10,
        interval=1,
        condition=check_app_running,
        error_message="Unable to observe the application in a RUNNING state",
    )
    logging.info("response from the command: %s\n", response)

    app_details = json.loads(response)

    assert app_details["status"]["cluster"]["name"] == CLUSTER_NAME
    assert app_details["status"]["state"] == "RUNNING"

    svc_url = app_details["status"]["services"]["echo-demo"]

    # 3. Access the application
    response = util.run(f"curl {svc_url}", retry=10, interval=1)

    logging.info("response from the command: %s\n", response)

    # 4. Delete the application
    response = util.run("rok kube app delete echo-demo")
    logging.info("response from the command: %s\n", response)

    # Add a condition to wait for the application to be actually deleted
    response = util.run(
        "rok kube app list -f json",
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the application deleted",
    )
    logging.info("response from the command: %s\n", response)

    assert json.loads(response) == []

    # 5. Delete the cluster
    response = util.run(f"rok kube cluster delete {CLUSTER_NAME}")
    logging.info("response from the command: %s\n", response)

    # Add a condition to wait for the cluster to be actually deleted
    response = util.run(
        "rok kube cluster list -f json",
        retry=10,
        interval=1,
        condition=check_empty_list,
        error_message="Unable to observe the cluster deleted",
    )
    logging.info("response from the command: %s\n", response)

    assert json.loads(response) == []
