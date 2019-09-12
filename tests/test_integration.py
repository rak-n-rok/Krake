import util
import logging
import json

logging.basicConfig(level=logging.DEBUG)

KRAKE_HOMEDIR = "/home/krake"
CLUSTER_NAME = "minikube-cluster-nightrun-1"


# CLUSTER_NAME_TEMPLATE = "minikube-cluster-{commit}"
# Attention: Global variable :(
# CLUSTER_NAME  = CLUSTER_NAME_TEMPLATE.format(commit=os.environ["CI_REF"])


def test_scenario1():
    kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{CLUSTER_NAME}"

    # Create cluster
    cmd = f"rok kube cluster create {kubeconfig_path}"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    # List cluster and assert it's running
    cmd = "rok kube cluster list -f json"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    cluster_list = json.loads(response)
    # cluster_list = response.json()
    assert cluster_list[0]["metadata"]["name"] == CLUSTER_NAME
    assert cluster_list[0]["status"]["state"] == "RUNNING"

    # Create application

    cmd = f"rok kube app create -f \
        {KRAKE_HOMEDIR}/git/krake/tests/echo-demo.yaml echo-demo"

    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    # Get application details and assert it's running on the previously
    # created cluster
    cmd = "rok kube app get echo-demo -f json"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    app_details = json.loads(response)

    assert (
        app_details["status"]["cluster"]
        == f"/kubernetes/namespaces/system/clusters/{CLUSTER_NAME}"
    )
    assert app_details["status"]["state"] == "RUNNING"

    svc_url = app_details["status"]["services"]["echo-demo"]

    # Connect to the application
    cmd = f"curl {svc_url}"
    response = util.run(cmd, retry=10, interval=1)

    logging.info("response from the command: %s\n", response)

    # Try to delete the cluster when an application is still running,
    # expecting a Conflict
    cmd = f"rok kube cluster delete {CLUSTER_NAME}"
    response = util.run(cmd, check=False)
    logging.info("response from the command: %s\n", response)

    assert "409 Client Error" in response

    # Delete the application
    cmd = "rok kube app delete echo-demo"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    cmd = "rok kube app list -f json"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    assert json.loads(response) == []

    # Delete the cluster
    cmd = f"rok kube cluster delete {CLUSTER_NAME}"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    cmd = "rok kube cluster list -f json"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    assert json.loads(response) == []
