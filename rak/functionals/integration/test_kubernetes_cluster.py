"""This module defines E2E integration tests for the CRUD operations of actual
Kubernetes clusters using the Krake Infrastructure Controller.
"""
import time

from yarl import URL

from functionals.utils import (
    run,
    check_return_code,
    check_cluster_created_and_up,
    check_resource_deleted,
)


KRAKE_HOMEDIR = "/home/krake"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/git/krake/rak/functionals"
TOSCA_PATH = f"{KRAKE_HOMEDIR}/git/krake/examples/templates/tosca"


def test_cluster_crud(
    im_container,
    im_container_port,
    os_auth_url,
    os_project_name,
    os_username,
    os_password,
):
    """Test Cluster CRUD operations over the rok CLI.

    The test method performs the following tests:

    1. Register IM Infrastructure Provider
    2. Register OpenStack IaaS Cloud
    3. Create a Cluster
    4. Wait for the actual Kubernetes cluster to be created and healthy
    5. Check the number of cluster nodes.
    6. Update a Cluster
    7. Wait for the actual Kubernetes cluster to be updated and healthy
    8. Check the number of cluster nodes.
    9. Delete a Cluster
    10. Wait for the actual Kubernetes cluster to be deleted
    11. Delete Infrastructure Provider
    12. Delete Cloud

    Args:
        im_container (str): IM container name.
        im_container_port (str): IM container port.
        os_auth_url (str): OpenStack cloud auth URL.
        os_project_name (str): OpenStack cloud project name.
        os_username (str): OpenStack cloud password auth. username.
        os_password (str): OpenStack cloud password auth. password.

    """
    cluster_manifest_path = f"{TOSCA_PATH}/im-cluster.yaml"
    cluster_manifest_update_path = f"{TOSCA_PATH}/im-cluster-scale-up.yaml"
    provider_name = "im-provider"
    cloud_name = "os-cloud"
    cluster_name = "test-cluster"

    # 1. Register IM Infrastructure Provider
    error_message = (
        f"The Infrastructure Provider {provider_name} could not be registered."
    )
    run(
        f"rok infra provider register --type im"
        f" --url http://{im_container}:{im_container_port}"
        f" --username test --password test {provider_name}",
        condition=check_return_code(error_message),
    )
    # 2. Register OpenStack IaaS Cloud
    # Only URL with scheme, host and port is required,
    # hence the e.g. path is removed here
    os_auth = URL(os_auth_url).origin()
    error_message = f"The Cloud {cloud_name} could not be registered."
    run(
        f"rok infra cloud register --type openstack --url {os_auth}"
        f" --project {os_project_name} --username {os_username}"
        f" --password {os_password} --infra-provider {provider_name}"
        f" {cloud_name}",
        condition=check_return_code(error_message),
    )
    # 3. Create a Cluster
    error_message = f"The Cluster {cluster_name} could not be created."
    run(
        f"rok kube cluster create -f {cluster_manifest_path} {cluster_name}",
        condition=check_return_code(error_message),
    )
    # 4. Wait for the actual Kubernetes cluster to be created and healthy
    # In a normal conditions the actual Kubernetes cluster creation
    # described by `cluster_manifest_path` TOSCA takes approximately 10min.
    # Wait up to 90 retries with 10s delay = 900s = 15min
    error_message = f"The Cluster {cluster_name} has not been created after 15min."
    cluster_details = run(
        f"rok kube cluster get {cluster_name} -o json",
        retry=90,
        interval=10,
        condition=check_cluster_created_and_up(error_message, expected_state="ONLINE"),
    ).json
    # 5. Check the number of cluster nodes. Cluster should consist from
    # 1 control plane node and 1 worker node
    assert len(cluster_details["status"]["nodes"]) == 2
    # 6. Update a Cluster
    error_message = f"The Cluster {cluster_name} could not be updated."
    run(
        f"rok kube cluster update -f {cluster_manifest_update_path} {cluster_name}",
        condition=check_return_code(error_message),
    )
    time.sleep(10)  # Wait for Cluster state transition from `ONLINE` to `RECONCILING`
    # 7. Wait for the actual Kubernetes cluster to be updated and healthy
    # In a normal conditions the actual Kubernetes cluster reconciliation
    # described by `cluster_manifest_update_path` TOSCA takes approximately 5min.
    # Wait up to 48 retries with 10s delay = 480s = 8min
    error_message = f"The Cluster {cluster_name} has not been updated after 8min."
    cluster_details = run(
        f"rok kube cluster get {cluster_name} -o json",
        retry=48,
        interval=10,
        condition=check_cluster_created_and_up(error_message, expected_state="ONLINE"),
    ).json
    # 8. Check the number of cluster nodes. Cluster should consist from
    # 1 control plane node and 2 worker nodes
    assert len(cluster_details["status"]["nodes"]) == 3
    # 9. Delete a Cluster
    error_message = f"The Cluster {cluster_name} could not be deleted."
    run(
        f"rok kube cluster delete {cluster_name}",
        condition=check_return_code(error_message),
    )
    # 10. Wait for the actual Kubernetes cluster to be deleted
    # In a normal conditions the actual Kubernetes cluster deletion
    # takes approximately 50sec.
    # Wait up to 36 retries with 5s delay = 180s = 3min
    error_message = f"The Cluster {cluster_name} has not been deleted after 3min."
    run(
        f"rok kube cluster get {cluster_name}",
        retry=36,
        interval=5,
        condition=check_resource_deleted(error_message),
    )
    # 11. Delete Infrastructure Provider
    error_message = f"The Infrastructure Provider {provider_name} could not be deleted."
    run(
        f"rok infra provider delete {provider_name}",
        condition=check_return_code(error_message),
    )
    # 12. Delete Cloud
    error_message = f"The Cloud {cloud_name} could not be deleted."
    run(
        f"rok infra cloud delete {cloud_name}",
        condition=check_return_code(error_message),
    )
