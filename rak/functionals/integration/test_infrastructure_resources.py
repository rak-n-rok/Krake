"""This module defines e2e integration tests for the infrastructure resources of
the Krake API:
- GlobalInfrastructureProvider
- InfrastructureProvider
- GlobalCloud
- Cloud

The tests are performed against the Krake API, via the rok CLI.
"""
import copy

import pytest

from functionals.utils import (
    run,
    check_http_code_in_output,
    check_response_content,
    check_empty_list,
)


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
