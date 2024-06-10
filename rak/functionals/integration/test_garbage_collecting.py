""" This module defines E2E integration tests for the deletion and
  migration of applications and kubernetes clusters handled by the
  garbage collector.


"""
# ~ import itertools
# ~ import math
import os
import pytest
import random

# ~ import string
import time
import yaml

from functionals.utils import (
    run,
    check_cluster_created_and_up,
    check_app_created_and_up,
    check_resource_deleted,
    # ~ create_cluster_label_info,
    # ~ get_scheduling_score,
    # ~ get_other_cluster,
)

from functionals.environment import (
    Environment,
    create_multiple_cluster_environment,
    get_default_kubeconfig_path,
    OBSERVER_PATH,
    MANIFEST_PATH,
)
from functionals.resource_definitions import ResourceKind
# ~ from functionals.resource_provider import provider, WeightedMetric, StaticMetric
# ~ from datetime import datetime

KRAKE_HOMEDIR = "/home/krake"
GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
# ~ MANIFEST_PATH = f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}"


# TODO:! we cloud dynamically read in this value from krake config
def _read_value_from_config(value, default):
    options = [
        "scheduler.yaml",
        os.path.join("/etc/krake/", "scheduler.yaml"),
        os.path.join(f"{KRAKE_HOMEDIR}/{GIT_DIR}/config", "scheduler.yaml"),
    ]
    for path in options:
        if os.path.exists(path):
            with open(path, "r") as fd:
                data = yaml.safe_load(fd)
                print(data)
                return data[value]
    return default


RESCHEDULING_INTERVAL = _read_value_from_config("reschedule_after", 60)


def test_kubernetes_application_deletion_on_cluster_deletion(k8s_clusters):
    """Check that an application scheduled on a cluster gets deleted
    when the cluster it is running on gets deleted.

    In the test environment:
    1. Create enviornment of two clusters and one app
    2. Retrieve the name of the cluster on which the application was scheduled
    3. Check the cluster the app is Running on
    4. Delete cluster app is running on
    5. Check if the application has been deleted

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.
    """
    # The two clusters used for testing the deletion in this test
    clusters = random.sample(k8s_clusters, 2)
    kubeconfig_paths = {c: get_default_kubeconfig_path(c) for c in clusters}

    # The setup of the enviornment an the application manifest
    # TODO:!!! create enviornment using more then one app
    manifest_path = f"{MANIFEST_PATH}/echo-demo.yaml"
    app_name="echo-cascade-deletion"
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        manifest_path=manifest_path,
        app_name=app_name,
    )

    # 1. Create enviornment of two clusters and one app
    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Retrieve the name of the cluster on which the application was scheduled
        cluster_name = app.get_running_on()
        assert cluster_name in clusters

        # 3. Check the cluster the app is Running on
        error_message = f"The Cluster {cluster_name} has not been created."
        run(
            f"rok kube cluster get {cluster_name} -o json",
            retry=90,
            interval=10,
            condition=check_cluster_created_and_up(error_message, expected_state="ONLINE"),
        ).json

        # 4. Delete cluster app is running on
        error_message = f"The Cluster {cluster_name} has not been deleted after 3min."
        run(
            f"rok kube cluster delete {cluster_name}",
            retry=36,
            interval=5,
            condition=check_resource_deleted(error_message),
        )

        # 5. Check if the application has been deleted
        error_message = f"The Application {app_name} has not been deleted"
        run(
            f"rok kube app get {app_name} -o json",
            retry=90,
            interval=10,
            condition=check_resource_deleted(error_message),
        ).json



def test_kubernetes_application_migration_on_cluster_deletion(k8s_clusters):
    """Check that an application scheduled on a cluster gets migrated
    (if --disable-migration has not been used)
    when the cluster it is running on gets deleted.

    In the test environment:
    1. Create the application, without cluster constraints and migration flag;
    2. Ensure the application was scheduled to a cluster;
    3. delete the cluster the application is running on;
    4. Ensure that the application was rescheduled to the requested cluster;
    5. Check Cluster got succescfully deleted

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.

    """
    # The two clusters and countries used for scheduling in this test
    clusters = random.sample(k8s_clusters, 2)

    # 1. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: get_default_kubeconfig_path(c) for c in clusters}

    # TODO:!!! create enviornment using more then one app
    manifest_path = f"{MANIFEST_PATH}/echo-demo-cascade_policy.yaml"
    observer_schema_path = (
        f"{OBSERVER_PATH}/echo-demo-cascade_policy-observer-schema.yaml"
    )
    app_name="echo-cascade-migration"
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        manifest_path=manifest_path,
        observer_schema_path=observer_schema_path,
        app_name=app_name,
    )

    with Environment(environment) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        # 2. Ensure the application was scheduled to a cluster;
        cluster_name = app.get_running_on()
        print(cluster_name)
        assert cluster_name in clusters

        # 3. Check which cluster the app is Running on;
        no_app_index = 0 if clusters[0] != cluster_name else 1
        app_index = 0 if clusters[0] == cluster_name else 1

        # 4. Ensure that the application was scheduled to the requested cluster;
        app.check_running_on(clusters[app_index], within=RESCHEDULING_INTERVAL)

        # 5. Delete cluster app is running on and check cluster got deleted
        error_message = f"The Cluster {cluster_name} has not been deleted after 3min."
        run(
            f"rok kube cluster delete {cluster_name}",
            retry=36,
            interval=5,
            condition=check_resource_deleted(error_message),
        )

        # ~ # 6. Check app is still running
        # ~ error_message = f"The application has not been successfully migrated"
        # ~ run(
            # ~ f"rok kube app get {app_name}",
            # ~ retry=36,
            # ~ interval=5,
            # ~ condition=check_app_created_and_up(error_message, expected_state="RUNNING",)
        # ~ )

        cluster_name = app.get_running_on()

        print(cluster_name)
        # 7. Check app got migrated to Cluster it was not running on
        app.check_running_on(clusters[no_app_index], within=RESCHEDULING_INTERVAL)
