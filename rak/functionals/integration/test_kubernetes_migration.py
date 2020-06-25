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
    run,
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


def test_kubernetes_no_migration(minikube_clusters):
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
    6. Wait and
        ensure that the application was rescheduled to the requested cluster;

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
        run(app.update_command(cluster_labels=[f"location={expected_countries[0]}"]))

        # 4. Wait and
        # ensure that the application was NOT rescheduled to the requested cluster;
        time.sleep(10)
        app.check_running_on(expected_clusters[1])

        # 5. Update the migration constraint to allow migration;
        run(app.update_command(migration=True))

        # 6. Wait and
        # ensure that the application was rescheduled to the requested cluster.
        time.sleep(10)
        app.check_running_on(expected_clusters[0])
