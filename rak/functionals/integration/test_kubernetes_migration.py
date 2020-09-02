"""This module defines E2E integration tests for the migration of applications
 between kubernetes clusters.

    We trigger the migration by changing:
        1) the cluster label constraints of the application

    We also test negative behaviour by:
        1) setting the migration constraint to false
    to make sure the migration does not take place.
"""
import itertools
import string
import time
from utils import (
    Environment,
    create_multiple_cluster_environment,
)
import random

KRAKE_HOMEDIR = "/home/krake"
GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}"
COUNTRY_CODES = [
    l1 + l2
    for l1, l2 in itertools.product(string.ascii_uppercase, string.ascii_uppercase)
]


def test_kubernetes_migration_cluster_constraints(minikube_clusters):
    """Check that an application scheduled on a cluster gets migrated
    (if neither --enable-migration nor --disable-migration has been used)
    when the cluster constraints of the application cahnges.

    In the test environment:
    1. Create the application, without cluster constraints and migration flag;
    2. Ensure the application was scheduled to a cluster;
    3. Update the cluster constraints to match the other cluster;
    4. Ensure that the application was rescheduled to the requested cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    # The two clusters and countries used for scheduling in this test
    clusters = random.sample(minikube_clusters, 2)
    countries = random.sample(COUNTRY_CODES, len(clusters))

    # 1. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    cluster_labels = dict(zip(clusters, [[f"location={cc}"] for cc in countries]))
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        cluster_labels=cluster_labels,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 2. Ensure the application was scheduled to a cluster;
        cluster_name = app.get_running_on()
        assert cluster_name in clusters

        # 3. Update the cluster constraints to match the other cluster;
        other_index = 0 if clusters[0] != cluster_name else 1
        app.update(cluster_labels=[f"location={countries[other_index]}"])

        # 4. Ensure that the application was rescheduled to the requested cluster;
        app.check_running_on(clusters[other_index])


def test_kubernetes_migration_at_cluster_constraint_update(minikube_clusters):
    """Check that an application scheduled on a cluster migrates at the time
    of a an update of the application's cluster constraints.

    This test should prove that it is not the automatic rescheduling that might
    occur right after an update of the cluster label constraints of an
    application that triggers the migration, but rather the update of the
    application's cluster label constraints itself.

    In the test environment:
    1. Create the application, without cluster constraints and migration flag;
    2. Ensure the application was scheduled to a cluster;
    3. Make sure that updating the application's cluster constraints
    triggers migration every time, by repeating the following steps 6 times:
        3a. Update a cluster label constraints of the application to match
        the other cluster.
        3b. sleep 20 seconds
        3c. Check which cluster the application is scheduled.
        3d. Assert that the application was migrated

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """

    # The two clusters and countries used for scheduling in this test
    clusters = random.sample(minikube_clusters, 2)
    countries = random.sample(COUNTRY_CODES, len(clusters))

    # 1. Create the application, without cluster constraints and migration flag;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in clusters}
    cluster_labels = dict(zip(clusters, [[f"location={cc}"] for cc in countries]))
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        cluster_labels=cluster_labels,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 2. Ensure the application was scheduled to a cluster;
        cluster_name = app.get_running_on()
        assert cluster_name in clusters

        # 3. Make sure that updating the application's cluster constraints
        # triggers migration every time, by repeating the following steps 6 times:
        old_running_on = cluster_name
        num_migrations = 0
        num_updates = 0
        for _ in range(6):
            # 3a. Update a cluster label constraints of the application to match
            # the other cluster.
            other_index = 0 if clusters[0] != old_running_on else 1
            app.update(cluster_labels=[f"location={countries[other_index]}"])
            num_updates += 1

            # 3b. sleep 20 seconds
            time.sleep(20)

            # 3c. Check which cluster the application is scheduled.
            running_on = app.get_running_on()
            if running_on != old_running_on:
                num_migrations += 1

            # 3d. Assert that the application was migrated
            assert num_migrations == num_updates
            old_running_on = running_on


def test_kubernetes_no_migration_cluster_constraints(minikube_clusters):
    """Check that an application scheduled on a cluster does not get migrated
    if its migration has been disabled.
    If the migration gets enabled it should be migrated according to its
    other constraints.

    In the test environment:
    1. Create the application, with cluster constraints and migration false;
    2. Ensure that the application was scheduled to the requested cluster;
    3. Update the cluster constraints to match the other cluster;
    4. Wait and
        ensure that the application was NOT rescheduled to the requested cluster;
    5. Update the migration constraint to allow migration;
    6. Ensure that the application was rescheduled to the requested cluster;

    Args:
        minikube_clusters (list): Names of the Minikube backend.

    """
    all_clusters = random.sample(minikube_clusters, len(minikube_clusters))
    all_countries = random.sample(COUNTRY_CODES, len(all_clusters))

    # The two clusters and countries used for scheduling in this test
    expected_clusters = all_clusters[:2]
    expected_countries = all_countries[:2]

    # 1. Create the application, with cluster constraints and migration false;
    kubeconfig_paths = {c: f"{CLUSTERS_CONFIGS}/{c}" for c in all_clusters}
    cluster_labels = dict(
        zip(all_clusters, [[f"location={cc}"] for cc in all_countries])
    )
    environment = create_multiple_cluster_environment(
        kubeconfig_paths,
        cluster_labels=cluster_labels,
        app_name="echo-demo",
        manifest_path=f"{MANIFEST_PATH}/echo-demo.yaml",
        # We place the application on the second cluster initially
        app_cluster_constraints=[f"location={expected_countries[1]}"],
        app_migration=False,
    )

    with Environment(environment) as resources:
        app = resources["Application"][0]

        # 2. Ensure that the application was scheduled to the requested cluster;
        app.check_running_on(expected_clusters[1])

        # 3. Update the cluster constraints to match the first cluster;
        app.update(cluster_labels=[f"location={expected_countries[0]}"])

        # 4. Wait and
        # ensure that the application was NOT rescheduled to the requested cluster;
        time.sleep(10)
        app.check_running_on(expected_clusters[1])

        # 5. Update the migration constraint to allow migration;
        app.update(migration=True)

        # 6. Ensure that the application was rescheduled to the requested cluster;
        app.check_running_on(expected_clusters[0])
