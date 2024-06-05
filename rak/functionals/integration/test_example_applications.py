import os
import random
import time
import re

from functionals.utils import (
    get_scheduling_score,
    get_other_cluster,
)

from functionals.utils import run, check_return_code, kubectl_cmd
from functionals.environment import (
    TEMPLATES_PATH,
    CLUSTERS_CONFIGS,
    Environment,
    create_default_environment,
)
from functionals.resource_definitions import (
    ApplicationDefinition,
)
from functionals.resource_provider import provider, WeightedMetric

from minio import Minio


RESCHEDULING_INTERVAL = 10


def test_mnist_application(k8s_clusters):
    """
    Tests the functionality of the "Mnist" example application.

    This test has multiple execution reasons:
    1. Test complete AND shutdown hook for a real-world application
    2. Test a stateful application, and it's functionality in combination with Krake
    3. Test minio as an external persistence solution, until Krake can deal with
       volumes or similar normal kinds of persistence

    To run the test, the following steps are executed:
    1. Set the metrics provided by the metrics provider
    2. Set the metric weights for the clusters, so that cluster 2 starts higher
       than cluster 1
    3. Create the environment with the applications and their respective metric
       weights in them
    4. Add a configmap for the shutdown hook script on both clusters
    5. Create the application and test its deployment. A significant delay is
       needed, since the docker image needs to be downloaded first, which could take
       some time
    6. Change the metrics so that score of cluster 1 is higher than
       the score of cluster 2
    7. Wait for the migration to cluster 1 to take place (remember its timestamp)
    8. Check after a significant delay, if the application was deleted
    9. Check minio, if the expected bucket exists and all the objects are included
       in the main folder.
    10. Delete the added configmap on both clusters
    """

    num_clusters = 2
    assert len(k8s_clusters) == num_clusters

    # The two clusters and metrics used in this test
    clusters = random.sample(k8s_clusters, num_clusters)

    gmp = provider.get_global_static_metrics_provider()
    static_metrics = random.sample(gmp.get_valued_metrics(), num_clusters)

    # 1. Set the metrics provided by the metrics provider
    static_metrics[0].value = 0.9
    static_metrics[1].value = 0.1
    gmp.set_valued_metrics(metrics=static_metrics)

    first_cluster = clusters[0]
    second_cluster = get_other_cluster(first_cluster, clusters)

    # 2. Set the metric weights for the clusters, so that cluster 2 starts higher
    # than cluster 1
    metric_weights = {
        clusters[0]: [
            WeightedMetric(static_metrics[0].metric, 1),
            WeightedMetric(static_metrics[1].metric, 10),
        ],
        clusters[1]: [
            WeightedMetric(static_metrics[0].metric, 10),
            WeightedMetric(static_metrics[1].metric, 1),
        ],
    }
    score_cluster_1 = get_scheduling_score(clusters[0], static_metrics, metric_weights)
    score_cluster_2 = get_scheduling_score(clusters[1], static_metrics, metric_weights)
    debug_info = {
        "k8sclusters": k8s_clusters,
        "metric_weights": metric_weights,
        "initial_metrics": static_metrics,
        "score_cluster_1_init": score_cluster_1,
        "score_cluster_2_init": score_cluster_2,
    }
    assert score_cluster_1 < score_cluster_2, f"debug_info: {debug_info}"

    manifest_path = os.path.join(TEMPLATES_PATH, "mnist/k8s/mnist.yaml")
    observer_schema_path = os.path.join(
        TEMPLATES_PATH, "mnist/mnist-observer-schema.yaml"
    )
    app_def = ApplicationDefinition(
        name="mnist",
        manifest_path=manifest_path,
        hooks=["complete", "shutdown"],
        observer_schema_path=observer_schema_path,
    )

    # 3. Create the environment with the applications and their respective metric
    # weights in them
    environment = create_default_environment(clusters, metrics=metric_weights)

    with Environment(environment):

        # 4. Add a configmap for the shutdown hook script on both clusters
        configmap_name = "mnist-shutdown"
        error_message = f"The configmap {configmap_name} could not be created."
        script_path = os.path.join(TEMPLATES_PATH, "mnist/mnist-shutdown.py")
        for i in [0, 1]:
            run(
                (
                    f"{kubectl_cmd(f'{CLUSTERS_CONFIGS}/{clusters[i]}')} create"
                    f" configmap {configmap_name} --from-file={script_path}"
                ),
                condition=check_return_code(error_message),
            )

        # 5. Create the application and test its deployment. A significant delay is
        # needed, since the docker image needs to be downloaded first, which could take
        # some time
        app_def.create_resource()

        app_def.check_created(delay=130)

        # 6. Change the metrics so that score of cluster 1 is higher than
        # the score of cluster 2
        static_metrics[0].value = 0.1
        static_metrics[1].value = 0.9
        gmp.update_resource(metrics=static_metrics)

        # Check the new scores and compare them
        score_cluster_1_c = get_scheduling_score(
            clusters[0], static_metrics, metric_weights
        )
        score_cluster_2_c = get_scheduling_score(
            clusters[1], static_metrics, metric_weights
        )
        debug_info = {
            "k8sclusters": k8s_clusters,
            "metric_weights": metric_weights,
            "initial_metrics": static_metrics,
            "score_cluster_1_init": score_cluster_1_c,
            "score_cluster_2_init": score_cluster_2_c,
        }
        assert score_cluster_1_c > score_cluster_2_c, f"debug_info: {debug_info}"

        # 7. Wait for the migration to cluster 1 to take place (remember its timestamp)
        app_def.check_running_on(
            second_cluster,
            within=RESCHEDULING_INTERVAL + 10,
            error_message=f"App was not running on the expected cluster "
            f"{second_cluster}. debug_info: {debug_info}",
        )

        logs = ""
        i = 0
        while i < 4:
            time.sleep(30)
            logs0 = run(
                (
                    f"{kubectl_cmd(f'{CLUSTERS_CONFIGS}/{clusters[0]}')} logs mnist"
                    " --follow"
                )
            )
            logs1 = run(
                (
                    f"{kubectl_cmd(f'{CLUSTERS_CONFIGS}/{clusters[1]}')} logs mnist"
                    "--follow"
                )
            )
            i += 1
            logs += logs0.output + "\n" + logs1.output

        # 8. Check after a significant delay, if the application was deleted
        app_def.check_deleted(delay=420)

        # 9. Check minio, if the expected bucket exists and all the objects are included
        # in the main folder.
        minio_client = Minio(
            "localhost:9000",
            access_key="minio-user",
            secret_key="minio-user-super-secret",
            # Hardcoded insecure (http) connection
            secure=False,
        )
        assert (
            minio_client.bucket_exists("krake-ci-bucket") is True
        ), "The 'krake-ci-bucket' doesn't exist in this Minio instance."

        regex = re.compile(r"Accuracy:\s\d\d.\d\d\s%", re.MULTILINE)
        match = regex.search(logs)
        if match:
            print(match.group())

        # 10. Delete the added configmap on both clusters
        error_message = f"The configmap {configmap_name} could not be deleted."
        for i in [0, 1]:
            run(
                f"{kubectl_cmd(f'{CLUSTERS_CONFIGS}/{clusters[i]}')} "
                f"delete configmap {configmap_name}",
                condition=check_return_code(error_message),
            )
