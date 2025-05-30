"""This module defines E2E integration tests for the KubernetesObserver of the
KubernetesController. It is responsible for updating the current state of a Kubernetes
Application, if the Application has been modified on the actual cluster.

The tests are performed on a simple test environment, where only one Cluster and one
Application is present. The general workflow is as follows:

 * A request for the Cluster registration, then the Application creation is sent to the
   Krake API;
 * The Application will be scheduled on the only Cluster;
 * The resources described in the Application are created on the Kubernetes cluster that
   corresponds to the Krake Cluster;
 * When this test environment exists, different actions are performed on the actual
   cluster or the API, to test the behavior of the KubernetesObserver.
 * A request is sent to delete the Application, then the Cluster.
"""
import json
import random
import tempfile
import time
import pytest

from functionals.utils import (
    run,
    check_resource_deleted,
    check_return_code,
    check_spec_container_image,
    check_spec_replicas,
    check_resource_container_health,
    kubectl_cmd,
)
from functionals.environment import (
    CLUSTERS_CONFIGS,
    OBSERVER_PATH,
    Environment,
    MANIFEST_PATH,
    create_default_environment,
    get_default_kubeconfig_path,
    create_simple_environment,
)
from functionals.resource_definitions import ApplicationDefinition, ResourceKind


def test_kubernetes_observer_deletion(k8s_clusters):
    """Check that if an observed resource of an Application is deleted on its cluster,
    the Observer watches it and notifies the API, which leads to the recreation of the
    resource.

    In the test environment:
    1. Delete an observed resource on the actual given kubernetes cluster. The
    KubernetesObserver should be seeing this change and the resource should be
    recreated.
    2. Ensure the presence of this resource after it has been deleted.

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = get_default_kubeconfig_path(k8s_cluster)

    environment = create_default_environment([k8s_cluster])
    with Environment(environment):
        # 1. Delete an observed resource on the cluster
        error_message = "The deployment echo-demo could not be deleted"
        run(
            f"{kubectl_cmd(kubeconfig_path)} delete deployment echo-demo",
            condition=check_return_code(error_message),
        )

        # 2. Check if the deleted resource is back
        error_message = "The Observer did not bring the deployment back up."
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo",
            condition=check_return_code(error_message),
        )


def test_kubernetes_observer_update_on_cluster(k8s_clusters):
    """Check that if an observed field of a resource is updated on its cluster, the
    Observer watches it and notifies the API, which leads to the resource being reverted
    to its original state.

    In the test environment:
    1. Update an observed field of a resource directly on the actual given kubernetes
    cluster. The KubernetesObserver should be seeing this change and the resource
    should be reverted to its previous state.
    2. Verify the specifications of this resource after it has been updated. Compare it
    to its original specifications.

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = get_default_kubeconfig_path(k8s_cluster)

    environment = create_default_environment([k8s_cluster])
    with Environment(environment):
        # 1. Update a resource on the cluster
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "echo", "image": "registry.k8s.io/echoserver:1.4"}
                        ]
                    }
                }
            }
        }
        # A list of "words" split between spaces is needed.
        command = kubectl_cmd(kubeconfig_path).split()
        command += ["patch", "deployment", "echo-demo", "--patch", json.dumps(patch)]
        error_message = "The echo-demo Application could not be patched."
        run(command, condition=check_return_code(error_message))

        # 2. Check if the resource updated has been reverted to its previous state
        expected_image = "registry.k8s.io/echoserver:1.10"
        error_message = (
            "The Observer did not revert the deployment to its previous state."
        )
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_spec_container_image(expected_image, error_message),
        )


@pytest.mark.skip(reason="Doesn't work for now")
def test_kubernetes_observer_update_on_cluster_nonobserved(k8s_clusters):
    """Check that if a non-observed field of a resource is updated on its cluster, the
    Observer doesn't notify the API. The resource is not reverted to its original state.

    In the test environment:
    1. Update a non-observed field of a resource directly on the actual given
    kubernetes cluster.
    2. Verify the specifications of this resource after it has been updated. Compare it
    to its original specifications.

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{k8s_cluster}"

    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"
    observer_schema_path = f"{OBSERVER_PATH}/echo-demo-observer-schema-custom-1.yaml"
    environment = create_simple_environment(
        k8s_cluster,
        kubeconfig_path,
        "echo-demo",
        manifest_path=manifest_path,
        observer_schema_path=observer_schema_path,
    )

    with Environment(environment):
        # 1. Update a resource on the cluster
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "echo", "image": "registry.k8s.io/echoserver:1.4"}
                        ]
                    }
                }
            }
        }
        # A list of "words" split between spaces is needed.
        command = kubectl_cmd(kubeconfig_path).split()
        command += ["patch", "deployment", "echo-demo", "--patch", json.dumps(patch)]
        error_message = "The echo-demo Application could not be patched."
        run(command, condition=check_return_code(error_message))

        # 2. Check that the image has not been reverted to the previous state
        expected_image = "registry.k8s.io/echoserver:1.10"
        error_message = (
            "The Observer did not revert the deployment to its previous state."
        )
        with pytest.raises(AssertionError, match=error_message):
            run(
                f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
                condition=check_spec_container_image(expected_image, error_message),
            )


def test_kubernetes_observer_update_on_cluster_noninitialized(k8s_clusters):
    """This test demonstrates that the Observer behavior also works on fields which are
    not initialized by the user, as long as the field is observed.

    In the test environment:
    1. Update an observed field of a resource directly on the actual given kubernetes
    cluster. The KubernetesObserver should be seeing this change and the resource
    should be reverted to its previous state.
    2. Verify the specifications of this resource after it has been updated. Compare it
    to its original specifications.

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{k8s_cluster}"

    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"
    observer_schema_path = f"{OBSERVER_PATH}/echo-demo-observer-schema-custom-1.yaml"
    environment = create_simple_environment(
        k8s_cluster,
        kubeconfig_path,
        "echo-demo",
        manifest_path=manifest_path,
        observer_schema_path=observer_schema_path,
    )

    with Environment(environment):
        # 1. Update a resource on the cluster
        patch = {"spec": {"replicas": 2}}
        # A list of "words" split between spaces is needed.
        command = kubectl_cmd(kubeconfig_path).split()
        command += ["patch", "deployment", "echo-demo", "--patch", json.dumps(patch)]
        error_message = "The echo-demo Application could not be patched."
        run(command, condition=check_return_code(error_message))

        # 2. Check that the deployment has been reverted to its previous state
        expected_replicas_count = 1
        error_message = (
            "The Observer did not revert the deployment to its previous state."
        )
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_spec_replicas(expected_replicas_count, error_message),
        )


nginx_deployment = """
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: nginx-deployment
    spec:
      selector:
        matchLabels:
          app: nginx
      template:
        metadata:
          labels:
            app: nginx
        spec:
          containers:
          - name: nginx
            image: nginx:1.7.9
            ports:
            - containerPort: 80
    """


def test_kubernetes_observer_additional_resource(k8s_clusters):
    """Check that if a resource that does not belong to any Application is added on the
    cluster of an Application, the Observer should be silent and not notify the API. No
    changes should be observed.

    In the test environment:
    1. Read the state of the created Application, and its k8s deployment and service on
    the cluster, before doing anything.
    2. Add a resource on the cluster, not bound to any Krake Application
    3. Compare the current state of the Application and its resources on the cluster to
    the state they had beforehand.
    4. Remove the additional resource.

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = get_default_kubeconfig_path(k8s_cluster)

    environment = create_default_environment([k8s_cluster])
    with Environment(environment, creation_delay=30) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. Read the state of the Application on the API and on the cluster to
        # be able to compare afterwards
        app_before = app.get_resource()

        error_message = "The Application echo-demo could not be found on the cluster."
        response = run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_return_code(error_message),
        )
        deployment_before = response.json

        error_message = "The Service echo-demo could not be found on the cluster."
        response = run(
            f"{kubectl_cmd(kubeconfig_path)} get service echo-demo -o json",
            condition=check_return_code(error_message),
        )
        service_before = response.json

        try:
            # 2. Add another resource on the cluster, not bound to Krake
            with tempfile.NamedTemporaryFile() as file:
                file.write(nginx_deployment.encode("utf-8"))
                file.seek(0)
                run(f"{kubectl_cmd(kubeconfig_path)} create -f {file.name}")

            # 3. Check that the Observer did not perform anything
            time.sleep(10)

            # Verify the created deployments: compare the name (and numbers) of expected
            # deployments to actual ones.
            response = run(f"{kubectl_cmd(kubeconfig_path)} get deployment -o json")
            deployments = response.json["items"]
            deployment_names = {i["metadata"]["name"] for i in deployments}
            assert deployment_names == {"echo-demo", "nginx-deployment"}

            # Compare the Application data before and after having added the resource
            app_after = app.get_resource()
            # The application is rescheduled, so the "kube_controller_triggered"
            # timestamp is updated. The test would break if the timestamp was not the
            # same on the "before" and "after" outputs.
            app_before["status"]["kube_controller_triggered"] = app_after["status"][
                "kube_controller_triggered"
            ]
            app_before["status"]["container_health"] = app_after["status"][
                "container_health"
            ]
            # handle weird behaviour of scheduler ("retries" only set sometimes)
            app_before["status"]["retries"] = app_after["status"]["retries"]
            assert app_before == app_after

            # Compare the Application deployment data before and after having added the
            # resource
            response = run(
                f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
                condition=check_return_code(error_message),
            )
            deployment_after = response.json
            assert deployment_before["spec"] == deployment_after["spec"]

            # Compare the Application service data before and after having added the
            # resource
            error_message = "The Service echo-demo could not be found on the cluster."
            response = run(
                f"{kubectl_cmd(kubeconfig_path)} get service echo-demo -o json",
                condition=check_return_code(error_message),
            )
            service_after = response.json
            assert service_before["spec"] == service_after["spec"]

        finally:
            # 4. Remove the additional resources
            run(
                f"{kubectl_cmd(kubeconfig_path)} delete deployment nginx-deployment",
                condition=check_return_code(
                    "The nginx-deployment could not be deleted"
                ),
            )


def test_kubernetes_observer_update_on_api(k8s_clusters):
    """Check that if an Application has been updated on the API, after the
    KubernetesController updated it on the cluster, it should not be reverted to its
    original state because of the KubernetesObserver.

    In the test environment:
    1. Update the Application on the API;
    2. Ensure that the resources of the Application have been updated on the cluster;
    3. Wait some time to ensure that the KubernetesObserver of the Application did not
    revert its state to the original one.

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = get_default_kubeconfig_path(k8s_cluster)

    environment = create_default_environment([k8s_cluster])
    with Environment(environment):
        # 1. Update the Application on the API
        run(f"krakectl kube app update echo-demo -f {MANIFEST_PATH}/echo-demo-update.yaml")

        # 2. Check if the resource has been updated on the cluster
        expected_image = "registry.k8s.io/echoserver:1.9"
        error_message = "The deployment was not updated on the cluster."
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_spec_container_image(expected_image, error_message),
        )

        # 3. Check again that the resource has then NOT been updated by the Observer.
        time.sleep(10)
        expected_image = "registry.k8s.io/echoserver:1.9"
        error_message = (
            "The observer should not update the Application back to its previous state."
        )
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_spec_container_image(expected_image, error_message),
        )


def test_kubernetes_observer_delete_on_api(k8s_clusters):
    """Check that if an Application has been deleted on the API, after the
    KubernetesController deleted it on the cluster, it should not be reverted to its
    original state because of the KubernetesObserver.

    In the test environment:
    1. Delete the Application on the API;
    2. Ensure that the resources of the Application have been deleted on the cluster;
    3. Wait some time to ensure that the KubernetesObserver of the Application did not
    trigger the recreation of the resources.

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = get_default_kubeconfig_path(k8s_cluster)

    environment = create_default_environment([k8s_cluster])
    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. Delete the Application on the API
        app.delete_resource(True)

        # 2. Check that resource has NOT been put back up on the cluster by the
        # observer's doing
        time.sleep(10)
        error_message = "The Observer brought the deleted deployment back up."
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_resource_deleted(error_message),
        )

        # 3. Create the resource again but with other specs
        new_manifest_path = f"{MANIFEST_PATH}/echo-demo-update.yaml"
        new_app = ApplicationDefinition(name=app.name, manifest_path=new_manifest_path)
        new_app.create_resource(True)

        # 4. Check that the resource has not been reverted to its previous state due to
        # the observer.
        time.sleep(10)
        expected_image = "registry.k8s.io/echoserver:1.9"
        error_message = (
            "The kubernetes observer should not update the Application back to its "
            "previous state."
        )
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_spec_container_image(expected_image, error_message),
        )


def test_kubernetes_observer_recreated(k8s_clusters):
    """Check that if an Application has been updated on the API, its corresponding
    KubernetesObserver has been updated too, by modifying the resources on the cluster,
    and checking that the observer reverted the resources to the updated state.

    In the test environment:
    1. Update an Application on the API: image from 1.10 --> 1.9
    2. Modify the resources of the Application on the cluster directly: 1.9 --> 1.4
    3. Check that the observer notified the API of the change, and that it has been
    reverted: 1.4 --> 1.9

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = get_default_kubeconfig_path(k8s_cluster)

    environment = create_default_environment([k8s_cluster])
    with Environment(environment):
        # 1. Update a resource on the API
        run(f"krakectl kube app update echo-demo -f {MANIFEST_PATH}/echo-demo-update.yaml")

        # Ensure that the resource has been updated on the cluster
        expected_image = "registry.k8s.io/echoserver:1.9"
        error_message = "The deployment was not updated on the cluster."
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_spec_container_image(expected_image, error_message),
        )

        # 2. Update a resource on the cluster
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "echo", "image": "registry.k8s.io/echoserver:1.4"}
                        ]
                    }
                }
            }
        }
        # A list of "words" split between spaces is needed.
        command = kubectl_cmd(kubeconfig_path).split()
        command += ["patch", "deployment", "echo-demo", "--patch", json.dumps(patch)]
        error_message = "The echo-demo Application could not be patched."
        run(command, condition=check_return_code(error_message))

        # 3. Check if the resource updated has been reverted to the updated state
        expected_image = "registry.k8s.io/echoserver:1.9"
        error_message = (
            "The kubernetes observer should update the Application back to its previous"
            " state."
        )
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_spec_container_image(expected_image, error_message),
        )


class ContainerHealth(object):
    desired_pods: int = 0
    running_pods: int = 0
    completed_pods: int = 0
    failed_pods: int = 0


def test_kubernetes_observe_container_health(k8s_clusters):
    """Check that an applications information are changed according to their current
    pod (health) information.

    In the test environment:
    1. Check if the pod health information are correct
    2. Update the application, so that the pod information change
    3. Check if the pod health information changed according to the updated manifest

    Args:
        k8s_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    k8s_cluster = random.choice(k8s_clusters)
    kubeconfig_path = get_default_kubeconfig_path(k8s_cluster)

    environment = create_default_environment([k8s_cluster])
    with Environment(environment):

        # 1. Check if the pod health information are correct
        pd = ContainerHealth()
        pd.desired_pods = 1
        pd.running_pods = 1
        error_message = "The observed pod healths don't match the required pod healths."
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_resource_container_health(pd, error_message),
        )

        # 2. Update a resource with the API
        run(f"krakectl kube app update echo-demo -f {MANIFEST_PATH}/echo-demo-update.yaml")

        # 3. Check if the pod health information changed according to
        # the updated manifest
        pd.desired_pods = 2
        pd.running_pods = 2
        error_message = "The observed pod healths don't match the required pod healths."
        run(
            f"{kubectl_cmd(kubeconfig_path)} get deployment echo-demo -o json",
            condition=check_resource_container_health(pd, error_message),
        )
