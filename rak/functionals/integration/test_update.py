"""This module defines E2e integration tests for the resource update functionality of
the Krake API.

The tests are performed on a simple test environment, where only one Cluster and one
Application is present. The general workflow is as follows:

 * A request for the Cluster registration, then the Application creation is sent to the
   Krake API;
 * The Application will be scheduled on the only Cluster;
 * The resources described in the Application are created on the Kubernetes cluster that
   corresponds to the Krake Cluster;
 * When this test environment exists, different actions are performed on the actual
   cluster or the API, to test the behavior of different update mechanisms.
 * A request is sent to delete the Application, then the Cluster.
"""
import random
import pytest
import time
import yaml
from functionals.utils import (
    run,
    check_return_code,
    check_spec_container_image,
    check_spec_replicas,
    check_http_code_in_output,
)
from functionals.environment import Environment, create_simple_environment
from functionals.resource_definitions import ClusterDefinition, ResourceKind


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
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path=manifest_path
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
    3. one of the current label is updated and a new one is added.
    4. the new state of the Application on the API is checked, to see if the labels
       have been added/updated.
    5. the labels are replaced by new ones

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster = random.choice(minikube_clusters)

    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"
    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"
    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path=manifest_path
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. Update the Application
        first_labels = {"location": "DE", "lbl": "first"}
        app.update_resource(labels=first_labels, update_behavior = ["--remove-existing-labels"])

        # 2. Check that the label has been changed on the API
        expected_labels = app.get_labels()
        assert app.get_labels() == first_labels

        # 3. Update the Application
        second_labels = {"lbl": "second", "location": "GB"}

        app.update_resource(labels=second_labels)

        expected_labels.update(second_labels)

        # 4. Check that the label has been changed on the API
        assert app.get_labels() == expected_labels

        third_labels = {"foo": "bar"}
        update_behavior = ["--remove-existing-labels"]
        app.update_resource(labels=third_labels, update_behavior=update_behavior)

        expected_labels = third_labels

        assert app.get_labels() == expected_labels


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
        0: [
            ClusterDefinition(
                name=minikube_cluster, kubeconfig_path=kubeconfig_path, register=True
            )
        ]
    }

    # Get the content of the kubeconfig file to compare with the updated value on the
    # API.
    other_kubeconfig_path = f"{CLUSTERS_CONFIGS}/{other_cluster}"
    with open(other_kubeconfig_path, "r") as file:
        other_content = yaml.safe_load(file)

    with Environment(environment) as env:
        cluster = env.resources[ResourceKind.CLUSTER][0]

        # 1. Update the Cluster
        run(f"rok kube cluster update {cluster.name} -k {other_kubeconfig_path}")

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
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path=manifest_path
    )

    with Environment(environment) as env:
        cluster = env.resources[ResourceKind.CLUSTER][0]

        # 1. Update the Cluster
        first_labels = {"location": "DE", "lbl": "first"}
        cluster.update_resource(labels=first_labels)

        # 2. Check that the label has been changed on the API
        expected_labels = first_labels
        assert cluster.get_labels() == expected_labels

        # 3. Update the Cluster
        second_labels = {"lbl": "second", "other": "value"}
        cluster.update_resource(labels=second_labels)

        # 4. Check that the label has been changed on the API
        expected_labels.update(second_labels)
        assert cluster.get_labels() == expected_labels

        # 5. Update the Cluster
        update_behavior = ["--remove-existing-labels"]
        third_labels = {"location": "GB"}
        cluster.update_resource(labels=third_labels, update_behavior=update_behavior)

        # 6. Check that the label has been changed on the API
        expected_labels = third_labels
        assert cluster.get_labels() == expected_labels


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
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path=manifest_path
    )

    with Environment(environment) as env:
        cluster = env.resources[ResourceKind.CLUSTER][0]
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. "Update" the Cluster (no change is sent)
        run(
            f"rok kube cluster update {cluster.name} -k {kubeconfig_path}",
            condition=check_http_code_in_output(400),
        )

        # 2. "Update" the Application (no change is sent)
        run(
            f"rok kube app update {app.name} -f {manifest_path}",
            condition=check_http_code_in_output(400),
        )


@pytest.mark.parametrize("tosca_from", ["dict", "url"])
def test_update_no_changes_tosca(minikube_clusters, tosca_from, file_server):
    """Update the Application with the same TOSCA template file
    defined by a dict or a URL.

    As the update does not change any field of the resources,
    the update should be rejected in both cases.

    The Application is updated with the TOSCA template, that contains the
    same application definition. It should return an HTTP 400 error code.

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.
        tosca_from (str): Parametrize the test with the `dict` and `url` values.
        file_server (callable): Callable that start http server with endpoint
           to get the given file.

    """
    minikube_cluster = random.choice(minikube_clusters)

    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"
    is_url = False
    if tosca_from == "dict":
        tosca = f"{MANIFEST_PATH}/echo-demo-tosca.yaml"
    elif tosca_from == "url":
        is_url = True
        tosca = file_server(
            f"{MANIFEST_PATH}/echo-demo-tosca.yaml",
            file_name="echo-demo-tosca.yaml",
        )
    else:
        raise ValueError(f"{tosca_from} source not supported.")

    environment = create_simple_environment(
        minikube_cluster,
        kubeconfig_path,
        "echo-demo",
        tosca=tosca,
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]
        # "Update" the Application with TOSCA template that contains
        # the same definition
        run(
            f"rok kube app update {app.name} {'--url' if is_url else '--file'} {tosca}",
            condition=check_http_code_in_output(400),
        )


def test_update_no_changes_csar(minikube_clusters, archive_files, file_server):
    """Update the Application with the same CSAR defined by a URL.

    As the update does not change any field of the resources,
    the update should be rejected.

    The Application is updated with CSAR, that points to the
    same application definition. It should return an HTTP 400 error code.

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.
        archive_files (callable): Callable that archives given files to
          the ZIP archive.
        file_server (callable): Callable that starts a http server with an endpoint to
          get the given file.

    """
    minikube_cluster = random.choice(minikube_clusters)

    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"
    tosca = f"{MANIFEST_PATH}/echo-demo-tosca.yaml"
    tosca_meta = f"{MANIFEST_PATH}/TOSCA-Metadata/TOSCA.meta"

    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("echo-demo-tosca.yaml", tosca),
            ("TOSCA-Metadata/TOSCA.meta", tosca_meta),
        ],
    )
    csar_url = file_server(csar_path, file_name="archive.csar")

    environment = create_simple_environment(
        minikube_cluster,
        kubeconfig_path,
        "echo-demo",
        csar=csar_url,
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]
        # "Update" the Application with CSAR that contains
        # the same definition
        run(
            f"rok kube app update {app.name} --url {csar_url}",
            condition=check_http_code_in_output(400),
        )


@pytest.mark.parametrize("tosca_from", ["dict", "url"])
def test_update_application_tosca(minikube_clusters, tosca_from, file_server):
    """In the test environment, update the Application with a new TOSCA template
       defined as a URL and dict.

    The previous TOSCA template has an echo server image with a version 1.10.
    The updated TOSCA reverts it to the version 1.9.

    The test has the following workflow:

    1. the Application is updated with another TOSCA, that changes its container
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
        tosca_from (str): Parametrize the test with the `dict` and `url` values.
        file_server (callable): Callable that start a http server with endpoint
          to get the given file.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    is_url = False
    if tosca_from == "dict":
        tosca = f"{MANIFEST_PATH}/echo-demo-tosca.yaml"
        tosca_updated = f"{MANIFEST_PATH}/echo-demo-update-tosca.yaml"
    elif tosca_from == "url":
        is_url = True
        tosca = file_server(
            f"{MANIFEST_PATH}/echo-demo-tosca.yaml",
            file_name="echo-demo-tosca.yaml",
        )
        tosca_updated = file_server(
            f"{MANIFEST_PATH}/echo-demo-update-tosca.yaml",
            file_name="echo-demo-update-tosca.yaml",
        )
    else:
        raise ValueError(f"{tosca_from} source not supported.")

    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", tosca=tosca
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]
        # TODO: Implement better `wait-for the running state` mechanism
        time.sleep(10)  # Wait for TOSCA translations
        # 1. Update the Application
        error_message = f"The Application {app.name} could not be updated."
        run(
            f"rok kube app update {app.name} {'--url' if is_url else '--file'}"
            f" {tosca_updated}",
            condition=check_return_code(error_message),
        )

        # 2. Check that the image version has been changed on the API
        # TODO: Implement better `wait-for the running state` mechanism
        time.sleep(10)  # Wait for TOSCA translations
        app_details = app.get_resource()
        manifest_spec = app_details["spec"]["manifest"][0]["spec"]["template"]["spec"]
        container_image = manifest_spec["containers"][0]["image"]

        assert container_image == "k8s.gcr.io/echoserver:1.9"

        # 3. Check that the image version has been changed on the cluster
        expected_image = "k8s.gcr.io/echoserver:1.9"
        error_message = (
            f"The image of the container of deployment {app.name}"
            f" should have been updated to {expected_image}."
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


def test_update_application_csar(minikube_clusters, archive_files, file_server):
    """In the test environment, update the Application
    with a new CSAR file defined as URL.

    The previous CSAR file has an echo server image with a version 1.10.
    The updated CSAR file reverts it to the version 1.9.

    The test has the following workflow:

    1. the Application is updated with another CSAR file that changes its container
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
        archive_files (callable): Callable that archive given files
          to the ZIP archive.
        file_server (callable): Callable that start http server with endpoint
          to get the given file.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    tosca = f"{MANIFEST_PATH}/echo-demo-tosca.yaml"
    tosca_updated = f"{MANIFEST_PATH}/echo-demo-update-tosca.yaml"
    tosca_meta = f"{MANIFEST_PATH}/TOSCA-Metadata/TOSCA.meta"

    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("echo-demo-tosca.yaml", tosca),
            ("TOSCA-Metadata/TOSCA.meta", tosca_meta),
        ],
    )
    csar_url = file_server(csar_path, file_name="archive.csar")
    csar_updated_path = archive_files(
        archive_name="archive_updated.csar",
        files=[
            ("echo-demo-tosca.yaml", tosca_updated),
            ("TOSCA-Metadata/TOSCA.meta", tosca_meta),
        ],
    )
    csar_updated_url = file_server(csar_updated_path, file_name="archive_updated.csar")

    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", csar=csar_url
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]
        # TODO: Implement better `wait-for the running state` mechanism
        time.sleep(10)  # Wait for CSAR translations
        # 1. Update the Application
        error_message = f"The Application {app.name} could not be updated."
        run(
            f"rok kube app update {app.name} --url {csar_updated_url}",
            condition=check_return_code(error_message),
        )

        # 2. Check that the image version has been changed on the API
        # TODO: Implement better `wait-for the running state` mechanism
        time.sleep(10)  # Wait for CSAR translations
        app_details = app.get_resource()
        manifest_spec = app_details["spec"]["manifest"][0]["spec"]["template"]["spec"]
        container_image = manifest_spec["containers"][0]["image"]

        assert container_image == "k8s.gcr.io/echoserver:1.9"

        # 3. Check that the image version has been changed on the cluster
        expected_image = "k8s.gcr.io/echoserver:1.9"
        error_message = (
            f"The image of the container of deployment {app.name}"
            f" should have been updated to {expected_image}."
        )
        run(
            f"kubectl --kubeconfig {kubeconfig_path}"
            f" get deployment {app.name} -o json",
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
            f"kubectl --kubeconfig {kubeconfig_path}"
            f" get deployment {app.name} -o json",
            condition=check_spec_replicas(expected_replicas, error_message),
        )


@pytest.mark.parametrize("tosca_from", ["dict", "url"])
def test_update_manifest_application_by_tosca(
    minikube_clusters, tosca_from, file_server
):
    """In the test environment (where the application is created by the manifest file),
    update the Application with a new TOSCA template. The previous manifest file
    has an echo server image with a version 1.10. The TOSCA template reverts
    it to the version 1.9.

    TOSCA template is defined by a dict and a URL.

    The test has the following workflow:

    0. the Application is created with the manifest file
       (within :func:`create_simple_environment`)
    1. the Application is updated with TOSCA manifest, that changes its container
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
        tosca_from (str): Parametrize the test with the `dict` and `url` values.
        file_server (callable): Callable that starts a http server with an endpoint
          to get the given file.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"

    is_url = False
    if tosca_from == "dict":
        tosca_updated = f"{MANIFEST_PATH}/echo-demo-update-tosca.yaml"
    elif tosca_from == "url":
        is_url = True
        tosca_updated = file_server(
            f"{MANIFEST_PATH}/echo-demo-update-tosca.yaml",
            file_name="echo-demo-update-tosca.yaml",
        )
    else:
        raise ValueError(f"{tosca_from} source not supported.")

    # 0. the Application is created with the manifest file
    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path=manifest_path
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. Update the Application with TOSCA template
        error_message = f"The Application {app.name} could not be updated."
        run(
            f"rok kube app update {app.name} {'--url' if is_url else '--file'}"
            f" {tosca_updated}",
            condition=check_return_code(error_message),
        )

        # 2. Check that the image version has been changed on the API
        # TODO: Implement better `wait-for the running state` mechanism
        time.sleep(10)  # Wait for TOSCA translations
        app_details = app.get_resource()
        manifest_spec = app_details["spec"]["manifest"][0]["spec"]["template"]["spec"]
        container_image = manifest_spec["containers"][0]["image"]

        assert container_image == "k8s.gcr.io/echoserver:1.9"

        # 3. Check that the image version has been changed on the cluster
        expected_image = "k8s.gcr.io/echoserver:1.9"
        error_message = (
            f"The image of the container of deployment {app.name}"
            f" should have been updated to {expected_image}."
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


def test_update_manifest_application_by_csar(
    minikube_clusters, archive_files, file_server
):
    """In the test environment (where the application is created by the manifest file),
    update the Application with a new CSAR file. The previous manifest file
    has an echo server image with a version 1.10. The CSAR file reverts
    it to the version 1.9.

    The test has the following workflow:

    0. the Application is created with the manifest file
       (within :func:`create_simple_environment`)
    1. the Application is updated with CSAR, that changes its container
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
        archive_files (callable): Callable that archives given files
          to the ZIP archive.
        file_server (callable): Callable that start a http server with an endpoint
          to get the given file.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"
    tosca_updated = f"{MANIFEST_PATH}/echo-demo-update-tosca.yaml"
    tosca_meta = f"{MANIFEST_PATH}/TOSCA-Metadata/TOSCA.meta"

    csar_updated_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("echo-demo-tosca.yaml", tosca_updated),
            ("TOSCA-Metadata/TOSCA.meta", tosca_meta),
        ],
    )
    csar_updated_url = file_server(csar_updated_path, file_name="example_updated.csar")

    # 0. the Application is created with the manifest file
    environment = create_simple_environment(
        minikube_cluster, kubeconfig_path, "echo-demo", manifest_path=manifest_path
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 1. Update the Application with CSAR
        error_message = f"The Application {app.name} could not be updated."
        run(
            f"rok kube app update {app.name} --url {csar_updated_url}",
            condition=check_return_code(error_message),
        )

        # 2. Check that the image version has been changed on the API
        # TODO: Implement better `wait-for the running state` mechanism
        time.sleep(10)  # Wait for CSAR translations
        app_details = app.get_resource()
        manifest_spec = app_details["spec"]["manifest"][0]["spec"]["template"]["spec"]
        container_image = manifest_spec["containers"][0]["image"]

        assert container_image == "k8s.gcr.io/echoserver:1.9"

        # 3. Check that the image version has been changed on the cluster
        expected_image = "k8s.gcr.io/echoserver:1.9"
        error_message = (
            f"The image of the container of deployment {app.name}"
            f" should have been updated to {expected_image}."
        )
        run(
            f"kubectl --kubeconfig {kubeconfig_path} "
            f"get deployment {app.name} -o json",
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
            f"kubectl --kubeconfig {kubeconfig_path} "
            f"get deployment {app.name} -o json",
            condition=check_spec_replicas(expected_replicas, error_message),
        )
