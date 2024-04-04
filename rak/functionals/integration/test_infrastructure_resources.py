"""This module defines e2e integration tests for the infrastructure resources of
the Krake API:
- GlobalInfrastructureProvider
- InfrastructureProvider
- GlobalCloud
- Cloud

The tests are performed against the Krake API, via the rok CLI.
"""
import copy
import random
import pytest

from functionals.utils import (
    run,
    check_http_code_in_output,
    check_response_content,
    check_empty_list,
)
from functionals.environment import (
    Environment,
    create_default_environment,
)
from functionals.resource_definitions import ResourceKind
from functionals.resource_provider import provider


@pytest.mark.parametrize(
    "resource,ip_type",
    [
        ("GlobalInfrastructureProvider", "im"),
        ("InfrastructureProvider", "im"),
    ],
)
def test_infrastructure_provider_crudl(resource, ip_type):
    """Test basic infrastructure providers functionality over the rok CLI.

    The test method performs the following tests for each supported
    type of infrastructure provider (currently only: `im`) and for both
    `namespaced` and `global` (non-namespaced) infrastructure providers.

    The test has the following workflow:

    1. Delete a non-existent infrastructure provider and expect 404 response
    2. Get a non-existent infrastructure provider and expect 404 response
    3. Update a non-existent infrastructure provider and expect 404 response
    4. Register an infrastructure provider
    5. Get the infrastructure provider and check the content
    6. Update the infrastructure provider
    7. Get the infrastructure provider and check the content
    8. Perform an empty update of the infrastructure provider and expect 400 response
    9. Register an infrastructure provider with the same name and expect 409 response
    10. Delete the infrastructure provider
    11. List infrastructure providers and verify that the deleted one is not present

    Args:
        resource (str): Parametrize the test with the `namespaced` and
            `global` (non-namespaced) infrastructure provider resource.
        ip_type (str): Parametrize the test with the infrastructure provider
            type.
    """
    resource_name = f"{resource}_instance"
    expected_content_subset = {
        "api": "infrastructure",
        "kind": resource,
        "metadata": {
            "name": resource_name,
        },
        "spec": {
            "type": "im",
            "im": {
                "url": "http://im.example",
                "username": "user",
                "password": "pass",
                "token": None,
            },
        },
    }
    expected_content_updated = copy.deepcopy(expected_content_subset)
    expected_content_updated["spec"]["im"]["url"] = "http://updated.example"
    # 1. Delete a non-existent infrastructure provider and expect 404 response
    run(
        f"rok infra {resource.lower()} delete {resource_name}",
        condition=check_http_code_in_output(404),
        retry=0,
    )
    # 2. Get a non-existent infrastructure provider and expect 404 response
    run(
        f"rok infra {resource.lower()} get {resource_name}",
        condition=check_http_code_in_output(404),
        retry=0,
    )
    # 3. Update a non-existent infrastructure provider and expect 404 response
    run(
        f"rok infra {resource.lower()} update {resource_name}",
        condition=check_http_code_in_output(404),
        retry=0,
    )
    # 4. Register an infrastructure provider
    error_message = f"The {resource} {resource_name} could not be registered."
    run(
        f"rok infra {resource.lower()} register {resource_name}"
        f" --type {ip_type}"
        " --url http://im.example"
        " --username user"
        " --password pass"
        " -o json",
        condition=check_response_content(
            error_message,
            expected_content_subset,
        ),
        retry=0,
    )
    # 5. Get the infrastructure provider and check the content
    error_message = f"The {resource} {resource_name} could not be retrieved."
    run(
        f"rok infra {resource.lower()} get {resource_name} -o json",
        condition=check_response_content(
            error_message,
            expected_content_subset,
        ),
        retry=0,
    )
    # 6. Update the infrastructure provider
    error_message = f"The {resource} {resource_name} could not be updated."
    run(
        f"rok infra {resource.lower()} update {resource_name} "
        "--url http://updated.example -o json --password pass",
        condition=check_response_content(
            error_message,
            expected_content_updated,
        ),
        retry=0,
    )
    # 7. Get the infrastructure provider and check the content
    error_message = f"The {resource} {resource_name} could not be retrieved."
    run(
        f"rok infra {resource.lower()} get {resource_name} -o json",
        condition=check_response_content(
            error_message,
            expected_content_updated,
        ),
        retry=0,
    )
    # 8. Perform an empty update of the infrastructure provider and 400 response
    run(
        f"rok infra {resource.lower()} update {resource_name} "
        "--url http://updated.example -o json --password pass",
        condition=check_http_code_in_output(400),
        retry=0,
    )
    # 9. Register an infrastructure provider with the same name and expect 409 response
    run(
        f"rok infra {resource.lower()} register {resource_name}"
        f" --type {ip_type}"
        " --url http://im.example"
        " --username user"
        " --password pass"
        " -o json",
        condition=check_http_code_in_output(409),
        retry=0,
    )
    # 10. Delete the infrastructure provider
    error_message = f"The {resource} {resource_name} could not be deleted."
    run(
        f"rok infra {resource.lower()} delete {resource_name} -o json",
        condition=check_response_content(
            error_message,
            expected_content_updated,
        ),
        retry=0,
    )
    # 11. List infrastructure providers and verify that the deleted one is not present
    error_message = f"The list of {resource}s contains some items."
    run(
        f"rok infra {resource.lower()} list -o json",
        condition=check_empty_list(error_message),
    )


@pytest.mark.parametrize(
    "resource,cloud_type",
    [
        ("GlobalCloud", "openstack"),
        ("Cloud", "openstack"),
    ],
)
def test_cloud_crudl(resource, cloud_type):
    """Test basic clouds functionality over the rok CLI.

    The test method performs the following tests for each supported
    type of cloud (currently only: `openstack`) and for both
    `namespaced` and `global` (non-namespaced) clouds.

    The test has the following workflow:

    1. Delete a non-existent cloud and expect 404 response
    2. Get a non-existent cloud and expect 404 response
    3. Update a non-existent cloud and expect 404 response
    4. Register a cloud
    5. Get the cloud and check the content
    6. Update the cloud
    7. Get the cloud and check the content
    8. Perform an empty update of the cloud and expect 400 response
    9. Register a cloud with the same name and expect 409 response
    10. Delete the cloud
    11. List clouds and verify that the deleted one is not present

    Args:
        resource (str): Parametrize the test with the `namespaced` and
            `global` (non-namespaced) cloud resource.
        cloud_type (str): Parametrize the test with the cloud type.
    """
    resource_name = f"{resource}_instance"
    expected_content_subset = {
        "api": "infrastructure",
        "kind": resource,
        "metadata": {
            "name": resource_name,
        },
        "spec": {
            "type": "openstack",
            "openstack": {
                "auth": {
                    "type": "password",
                    "password": {
                        "project": {"domain_id": "default", "name": "project"},
                        "user": {
                            "domain_name": "Default",
                            "password": "pass",
                            "username": "user",
                        },
                    },
                },
                "infrastructure_provider": {"name": "im-provider"},
                "url": "http://keystone.example",
            },
        },
        "status": {"state": "ONLINE"},
    }
    expected_content_updated = copy.deepcopy(expected_content_subset)
    expected_content_updated["spec"]["openstack"]["url"] = "http://updated.example"
    # 1. Delete a non-existent cloud and expect 404 response
    run(
        f"rok infra {resource.lower()} delete {resource_name}",
        condition=check_http_code_in_output(404),
        retry=0,
    )
    # 2. Get a non-existent cloud and expect 404 response
    run(
        f"rok infra {resource.lower()} get {resource_name}",
        condition=check_http_code_in_output(404),
        retry=0,
    )
    # 3. Update a non-existent cloud and expect 404 response
    run(
        f"rok infra {resource.lower()} update {resource_name}",
        condition=check_http_code_in_output(404),
        retry=0,
    )
    # 4. Register a cloud
    error_message = f"The {resource} {resource_name} could not be registered."
    run(
        f"rok infra {resource.lower()} register {resource_name}"
        f" --type {cloud_type}"
        " --url http://keystone.example"
        " --project project"
        " --user user"
        " --password pass"
        " --global-infra-provider im-provider"
        " -o json",
        condition=check_response_content(
            error_message,
            expected_content_subset,
        ),
        retry=0,
    )
    # 5. Get the cloud and check the content
    error_message = f"The {resource} {resource_name} could not be retrieved."
    run(
        f"rok infra {resource.lower()} get {resource_name} -o json",
        condition=check_response_content(
            error_message,
            expected_content_subset,
        ),
        retry=0,
    )
    # 6. Update the cloud
    error_message = f"The {resource} {resource_name} could not be updated."
    run(
        f"rok infra {resource.lower()} update {resource_name} "
        "--url http://updated.example -o json --password pass",
        condition=check_response_content(
            error_message,
            expected_content_updated,
        ),
        retry=0,
    )
    # 7. Get the cloud and check the content
    error_message = f"The {resource} {resource_name} could not be retrieved."
    run(
        f"rok infra {resource.lower()} get {resource_name} -o json",
        condition=check_response_content(
            error_message,
            expected_content_updated,
        ),
        retry=0,
    )
    # 8. Perform an empty update of the cloud and 400 response
    run(
        f"rok infra {resource.lower()} update {resource_name} "
        "--url http://updated.example -o json --password pass",
        condition=check_http_code_in_output(400),
        retry=0,
    )
    # 9. Register a cloud with the same name and expect 409 response
    run(
        f"rok infra {resource.lower()} register {resource_name}"
        f" --type {cloud_type}"
        " --url http://keystone.example"
        " --project project"
        " --user user"
        " --password pass"
        " --global-infra-provider im-provider"
        " -o json",
        condition=check_http_code_in_output(409),
        retry=0,
    )
    # 10. Delete the cloud
    error_message = f"The {resource} {resource_name} could not be deleted."
    run(
        f"rok infra {resource.lower()} delete {resource_name} -o json",
        condition=check_response_content(
            error_message,
            expected_content_updated,
        ),
        retry=0,
    )
    # 11. List clouds and verify that the deleted one is not present
    error_message = f"The list of {resource}s contains some items."
    run(
        f"rok infra {resource.lower()} list -o json",
        condition=check_empty_list(error_message),
    )


@pytest.mark.skip(
    reason="This test is skipped for now, since it is unsafe to have a real username "
    "password combination in cleartext."
)
def test_scheduler_with_cloud(k8s_clusters):
    """E2e test for scheduling an application  to a cloud if the metric score is better

    Test applies workflow as follows:

        1. Create a cluster with specific metrics
        2. Create a cloud with a higher metric value
        3. Create an application with the 'automatic_cluster_creation' flag
        4. Ensure that the application is scheduled to a newly created cluster on the
           cloud.

    Args:
        k8s_clusters (list): Names of the Kubernetes backend.
    """
    # 1. Get Global Metrics (Provider)
    gmp = provider.get_global_static_metrics_provider()
    global_static_metric1 = gmp.get_valued_metrics()[0]
    global_static_metric2 = gmp.get_valued_metrics()[1]

    # --------------------------------
    resource_name = "global_cloud"
    expected_content_subset = {
        "api": "infrastructure",
        "kind": "GlobalCloud",
        "metadata": {
            "name": resource_name,
        },
        "spec": {
            "type": "openstack",
            "openstack": {
                "auth": {
                    "type": "password",
                    "password": {
                        "project": {"domain_id": "default", "name": "project"},
                        "user": {
                            "domain_name": "Default",
                            "password": "pass",
                            "username": "user",
                        },
                    },
                },
                "infrastructure_provider": {"name": "im-provider"},
                "url": "http://keystone.example",
            },
        },
        "status": {"state": "ONLINE"},
    }
    expected_content_updated = copy.deepcopy(expected_content_subset)
    expected_content_updated["spec"]["openstack"]["url"] = "http://updated.example"

    # 2. Register a cloud
    error_message = f"The global cloud {resource_name} could not be registered."
    run(
        f"rok infra gc register {resource_name}"
        f" --type openstack"
        " --url http://keystone.example"
        " --project project"
        " --user user"
        " --password pass"
        " --global-infra-provider im-provider"
        f" --global-metric {global_static_metric1.metric.mp_metric_name} 1"
        f" --global-metric {global_static_metric2.metric.mp_metric_name} 1.5"
        " -o json",
        condition=check_response_content(
            error_message,
            expected_content_subset,
        ),
        retry=0,
    )

    # 3. Register an infrastructure provider
    run(
        "rok infra ip register im-provider"
        " --type im"
        " --url http://localhost:8800"
        " --username test"
        " --password test",
        retry=0,
    )

    # 4. Create an application and check if it is scheduled to a cluster created
    # on the cloud
    cluster = random.choice(k8s_clusters)
    environment = create_default_environment([cluster], auto_cluster_create=True)

    with Environment(environment, creation_delay=10) as env:
        app = env.resources[ResourceKind.APPLICATION][0]

        cluster_details = run(
            "rok kube cluster get kind-cluster-1",
            retry=90,
            interval=10,
        )
        print(cluster_details.output)

        cluster_details = run(
            "rok kube cluster get kind-cluster-2",
            retry=90,
            interval=10,
        )
        print(cluster_details.output)

        ip_list = run(
            "rok infra ip list",
            retry=90,
            interval=10,
        )
        print(ip_list.output)
        gc_list = run(
            "rok infra gc list",
            retry=90,
            interval=10,
        )
        print(gc_list.output)

        app.check_running_on(cluster, after_delay=100)

        app_list = run(
            "rok kube app list",
            retry=90,
            interval=10,
        )
        print(app_list.output)
        app_details = run(
            "rok kube app get echo-demo",
            retry=90,
            interval=10,
        )
        print(app_details.output)

    # 4. Delete the cloud
    error_message = f"The global cloud {resource_name} could not be deleted."
    run(
        f"rok infra gc delete {resource_name} -o json",
        condition=check_response_content(
            error_message,
            expected_content_updated,
        ),
        retry=0,
    )

    # TODO - check if app is on cluster of cloud
    # - check if cluster is spawned
    # - delete cluster
    # - delete cloud

    # maybe write environment for clouds
