import os.path
import random
import time

from utils import run, check_return_code, kubectl_cmd
from environment import Environment
from resource_definitions import ClusterDefinition, ApplicationDefinition

KRAKE_HOMEDIR = "/home/krake"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/git/krake/rak/functionals"


def test_complete_hook(minikube_clusters):
    """Test the functionality of the "complete" hook.

    The test has the following workflow:

    1. Add the script to send the complete hook request to the Kubernetes cluster as
    ConfigMap to mount.
    2. Create a Kubernetes deployment with Krake that uses this script;
    3. Wait for the script to send the request to the API to scale-down the Application;
    4. Delete the ConfigMap that contains the script on the Kubernetes cluster.

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    environment = {
        10: [ClusterDefinition(name=minikube_cluster, kubeconfig_path=kubeconfig_path)]
    }

    application_name = "test-hook-complete"
    manifest_path = os.path.join(MANIFEST_PATH, "hook-deploy.yaml")
    app_def = ApplicationDefinition(
        name=application_name, manifest_path=manifest_path, hooks=["complete"]
    )

    with Environment(environment):
        # 1. Add a configMap with the script that can use the Krake hook
        configmap_name = "scripts-configmap"
        error_message = f"The configMap {configmap_name} could not be created."
        script_path = os.path.join(MANIFEST_PATH, "hook-script.py")
        run(
            (
                f"{kubectl_cmd(kubeconfig_path)} create configmap"
                f" {configmap_name} --from-file={script_path}"
            ),
            condition=check_return_code(error_message),
        )

        # 2. Start a deployment that uses the script for the Krake hook
        app_def.create_resource()
        app_def.check_created()

        # 3. Check that after some time, the Application has been deleted on the Krake
        # API.
        app_def.check_deleted()

        # 4. Delete the added configMap
        error_message = f"The configMap {configmap_name} could not be deleted."
        run(
            f"{kubectl_cmd(kubeconfig_path)} delete configmap {configmap_name}",
            condition=check_return_code(error_message),
        )


def test_shutdown_hook(minikube_clusters):
    """Test the functionality of the "shutdown" hook.

    The test has the following workflow:

    1. Add the script to send the shutdown hook request to the Kubernetes cluster as
    ConfigMap to mount.
    2. Create a Kubernetes deployment with Krake that uses this script;
    3. Tell the application to shut down.
    4. Wait for the script to send the request to the API, that the shutdown is finished
    5. Delete the ConfigMap that contains the script on the Kubernetes cluster.

    Args:
        minikube_clusters (list[PathLike]): a list of paths to kubeconfig files.

    """
    minikube_cluster = random.choice(minikube_clusters)
    kubeconfig_path = f"{CLUSTERS_CONFIGS}/{minikube_cluster}"

    environment = {
        10: [ClusterDefinition(name=minikube_cluster, kubeconfig_path=kubeconfig_path)]
    }

    application_name = "test-hook-shutdown"
    manifest_path = os.path.join(MANIFEST_PATH, "hook-shutdown.yaml")
    app_def = ApplicationDefinition(
        name=application_name, manifest_path=manifest_path, hooks=["shutdown"]
    )

    with Environment(environment):
        # 1. Add a configMap with the script that can use the Krake hook
        configmap_name = "sd-service-configmap"
        error_message = f"The configMap {configmap_name} could not be created."
        script_path = os.path.join(MANIFEST_PATH, "hook-script-shutdown-service.py")
        run(
            (
                f"{kubectl_cmd(kubeconfig_path)} create configmap"
                f" {configmap_name} --from-file={script_path}"
            ),
            condition=check_return_code(error_message),
        )

        # 2. Start a deployment that uses the script for the Krake hook
        app_def.create_resource()
        app_def.check_created(delay=20)

        time.sleep(30)

        # 3. Tell the application to shut down.
        app_def.delete_resource()

        time.sleep(60)

        # 4. Wait for the script to send the request to the API, that the shutdown
        # is finished
        app_def.check_deleted(delay=60)

        # 4. Delete the added configMap
        error_message = f"The configMap {configmap_name} could not be deleted."
        run(
            f"{kubectl_cmd(kubeconfig_path)} delete configmap {configmap_name}",
            condition=check_return_code(error_message),
        )
