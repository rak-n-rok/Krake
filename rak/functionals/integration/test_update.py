"""This module defines E2e integration tests for the resource update functionality of
the Krake API.

The tests are performed on a simple test environment, where only one Cluster and one
Application are present. The general workflow is as follow:

 * A request for the Cluster creation, then the Application creation are sent to the
   Krake API;
 * The Application will be scheduled on the only Cluster;
 * The resources described in the Application are created on the Kubernetes cluster that
   corresponds to the Krake Cluster;
 * When this test environment exists, different actions are performed on the actual
   cluster or the API, to test the behavior of different update mechanisms.
 * A request is sent to delete the Application, then the Cluster.
"""
import random

import yaml
from utils import (
    run,
    Environment,
    create_simple_environment,
    check_return_code,
    check_spec_container_image,
    check_spec_replicas,
    check_http_code_in_output,
    ClusterDefinition,
    ResourceKind,
)


KRAKE_HOMEDIR = "/home/krake"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/git/krake/rak/functionals"


def test_update_application_manifest(minikube_clusters):
    """In the test environment, update the Application with a new manifest. The previous
    manifest has an echo server image with a version 1.10. The updated manifest reverts
    it to the version 1.9.

    The test has the following workflow:

    1. the Application is updated with another manifest, that changes its container
       image;
    2. the new state of the Application on the API is checked, to see if the image
       changed;
    3. the new state of the k8s resource is checked on the actual cluster to see if the
       image changed;
    4. the new state of the Application on the API is checked, to see if the number of
       replicas changed;
    5. the new state of the k8s resource is checked on the actual cluster to see if the
       number of replicas changed.
    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"
    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. Update the Application
        error_message = f"The Application {app.name} could not be updated."
        run(
            f"rok kube app update {app.name} -f {MANIFEST_PATH}/echo-demo-update.yaml",
            condition=check_return_code(error_message),
        )

        # 2. Check that the image version has been changed on the API
        app_details = app.get_resource()
        manifest_spec = app_details["spec"]["manifest"][0]["spec"]["template"]["spec"]
        container_image = manifest_spec["containers"][0]["image"]

        assert container_image == "k8s.gcr.io/echoserver:1.9"

        # 3. Check that the image version has been changed on the cluster
        expected_image = "k8s.gcr.io/echoserver:1.9"
        error_message = (
            f"The image of the container of deployment {app.name}"
            f"should have been updated to {expected_image}."
        )
        run(
            f"kubectl --kubeconfig {kubeconfig_path} get deployment {app.name} -o json",
            condition=check_spec_container_image(expected_image, error_message),
        )

        # 4. Check that the number of replicas has been changed on the API
        replicas = app_details["spec"]["manifest"][0]["spec"].get("replicas")
        expected_replicas = 2
        assert replicas == expected_replicas

        # 5. Check that the number of replicas has been changed on the cluster
        error_message = (
            f"The number of replicas of deployment {app.name}"
            f"should have been updated to {expected_replicas}."
        )
        run(
            f"kubectl --kubeconfig {kubeconfig_path} get deployment {app.name} -o json",
            condition=check_spec_replicas(expected_replicas, error_message),
        )


def test_update_application_labels(minikube_clusters):
    """In the test environment, update the Application with a new label. The original
    Application has no label at all.

    The test has the following workflow:

    1. the Application is updated with two new labels;
    2. the new state of the Application on the API is checked, to see if the labels
       have been added;
    3. one of the current label is updated, the other is removed and a new one is added.
    4. the new state of the Application on the API is checked, to see if the labels
       have been added/updated/removed;

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster = random.choice(minikube_clusters)

    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"
    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"
    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. Update the Application
        first_labels = {"location": "DE", "lbl": "first"}
        app.update_resource(labels=first_labels)

        # 2. Check that the label has been changed on the API
        assert app.get_labels() == first_labels

        # 3. Update the Application
        second_labels = {"lbl": "second", "other": "value"}
        app.update_resource(labels=second_labels)

        # 4. Check that the label has been changed on the API
        assert app.get_labels() == second_labels


def test_update_cluster_kubeconfig(minikube_clusters):
    """In the test environment, update the Cluster with a new kubeconfig. The kubeconfig
     as stored on the API is then compared to the given one.

    1. the Cluster is updated with another kubeconfig
    2. the new state of the Cluster on the API is checked, to see if the kubeconfig
    changed.

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster, other_cluster = random.sample(
        minikube_clusters, len(minikube_clusters)
    )

    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"
    environment = {
        0: [ClusterDefinition(name=minikube_cluster, kubeconfig_path=kubeconfig_path)]
    }

    # Get the content of the kubeconfig file to compare with the updated value on the
    # API.
    other_kubeconfig_path = f"{KRAKE_HOMEDIR}/clusters/config/{other_cluster}"
    with open(other_kubeconfig_path, "r") as file:
        other_content = yaml.safe_load(file)

    with Environment(environment) as env:
        cluster = env.resources[ResourceKind.CLUSTER][0]

        # 1. Update the Cluster
        run(f"rok kube cluster update {cluster.name} -f {other_kubeconfig_path}")

        # 2. Check that the kubeconfig has been changed on the API
        cluster_details = cluster.get_resource()
        # As rok processes the kubeconfig file, the actual value in the Cluster resource
        # is different from the given file.
        resp_kubeconfig = cluster_details["spec"]["kubeconfig"]
        kubeconfig_cluster = resp_kubeconfig["clusters"][0]

        with open(kubeconfig_path, "r") as f:
            original_kubeconfig = yaml.safe_load(f)

        # The kubeconfig file used in the Cluster resource is not anymore the one used
        # when it was created.
        assert kubeconfig_cluster["name"] != original_kubeconfig["clusters"][0]["name"]
        assert (
            kubeconfig_cluster["cluster"]["server"]
            != original_kubeconfig["clusters"][0]["cluster"]["server"]
        )
        # Instead, the kubeconfig now points to the other kubeconfig file, used during
        # the update.
        assert kubeconfig_cluster["name"] == other_content["clusters"][0]["name"]
        assert (
            kubeconfig_cluster["cluster"]["server"]
            == other_content["clusters"][0]["cluster"]["server"]
        )


def test_update_cluster_labels(minikube_clusters):
    """In the test environment, update the Cluster with a new label. The original
    Cluster has no label at all.

    The test has the following workflow:

    1. the Cluster is updated with two new labels;
    2. the new state of the Cluster on the API is checked, to see if the labels
       have been added;
    3. one of the current label is updated, the other is removed and a new one is added.
    4. the new state of the Cluster on the API is checked, to see if the labels
       have been added/updated/removed;

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster = random.choice(minikube_clusters)

    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"
    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"

    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path
    )

    with Environment(environment) as env:
        cluster = env.resources[ResourceKind.CLUSTER][0]

        # 1. Update the Cluster
        first_labels = {"location": "DE", "lbl": "first"}
        cluster.update_resource(labels=first_labels)

        # 2. Check that the label has been changed on the API
        assert cluster.get_labels() == first_labels

        # 3. Update the Cluster
        second_labels = {"lbl": "second", "other": "value"}
        cluster.update_resource(labels=second_labels)

        # 4. Check that the label has been changed on the API
        assert cluster.get_labels() == second_labels


def test_update_no_changes(minikube_clusters):
    """In the test environment, attempt to update the Cluster with the same kubeconfig,
    and the Application with the same manifest file. As the update does not change any
    field of the resources, the update should be rejected in both cases.

    1. the Cluster is updated with the same kubeconfig, it should return an HTTP 400
       error code.
    2. the Application is updated with the same manifest file, it should return an HTTP
    400 error code.

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster = random.choice(minikube_clusters)

    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"
    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"

    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path
    )

    with Environment(environment) as env:
        cluster = env.resources[ResourceKind.CLUSTER][0]
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. "Update" the Cluster (no change is sent)
        run(
            f"rok kube cluster update {cluster.name} -f {kubeconfig_path}",
            condition=check_http_code_in_output(400),
        )

        # 2. "Update" the Application (no change is sent)
        run(
            f"rok kube app update {app.name} -f {manifest_path}",
            condition=check_http_code_in_output(400),
        )
