"""This module defines E2e integration tests for the core resources of
the Krake API:

    Role
    RoleBinding
    GlobalMetricsProvider
    GlobalMetric

The tests are performed against the Krake API, via the rok cli or a sessions request
instance, in case of no available implementation in rok.
"""
import time
import requests

from enum import Enum
from urllib.parse import urljoin
from datetime import datetime, timezone

from utils import (
    run,
    check_return_code,
    check_status_code,
    check_metric_content,
    check_metrics_provider_content,
)


class _MetricsProviderType(Enum):
    PROMETHEUS = "prometheus"
    STATIC = "static"
    KAFKA = "kafka"


_GC_DELAY = 3

# FIXME: Change with a rok implementation of Role and RoleBinding
# In succession with the conftest.py, test_roles_crud and test_rolebindings_crud need
# to be changed, if a rok implementation for roles and rolebindings is available.

def test_roles_crud(session):
    """Test basic role functionality with the session library.
    Rok cli can't be used here, because it doesn't implement role calls (yet).
    The test method performs the following tests for roles:

    1. Delete a non-existent role and expect failure
    2. Get a non-existent role and expect failure
    3. Update a non-existent role and expect failure
    4. Create a role
    5. Get the role and check the content
    6. Update the role
    7. Get the role and check the content
    8. Perform an empty update of the role and expect failure
    9. Create a role with the same name and expect failure
    10. Delete the role created earlier
    11. List the roles and verify that the deleted one is not present
    """

    base_url = session.base_url
    name = "e2e_test_role_2b_deleted"
    url = "/core/roles"
    req_url = urljoin(urljoin(base_url, url) + "/", name)

    # 1. Delete a non-existent role and expect failure
    try:
        session.delete(req_url)
    except requests.HTTPError as e:
        check_status_code(e.response, 404)
        pass

    # 2. Get a non-existent role and expect failure
    try:
        session.get(req_url)
    except requests.HTTPError as e:
        check_status_code(e.response, 404)
        pass

    # 3. Update a non-existent role and expect failure
    data = {
        "rules": [],
        "metadata": {
            "uid": "",
            "name": name,
            "created": "2021-09-09T08:18:50.856741+00:00",
            "modified": "2021-09-09T08:18:50.856741+00:00",
            "labels": {},
        },
    }
    try:
        session.put(req_url, json=data)
    except requests.HTTPError as e:
        check_status_code(e.response, 404)
        pass

    # 4. Create a role
    before_creation = datetime.now(timezone.utc)
    resp = session.post(
        urljoin(base_url, url), json={"metadata": {"name": name}, "rules": []}
    )
    check_status_code(resp, 200)

    # 5. Get the role and check the content
    resp = session.get(req_url)
    check_status_code(resp, 200)
    resp_data = resp.json()
    assert resp_data["rules"] == []
    assert resp_data["metadata"]["uid"] != ""
    assert resp_data["metadata"]["name"] == name
    assert (
        before_creation
        < datetime.strptime(resp_data["metadata"]["created"], "%Y-%m-%dT%H:%M:%S.%f%z")
        < datetime.now(timezone.utc)
    )

    # 6. Update the role
    before_update = datetime.now(timezone.utc)

    data = {
        "rules": [],
        "metadata": {
            "uid": resp_data["metadata"]["uid"],
            "name": name,
            "created": resp_data["metadata"]["created"],
            "modified": resp_data["metadata"]["modified"],
            "labels": {"Testlabel": "Testlabel"},
        },
    }
    resp = session.put(req_url, json=data)
    check_status_code(resp, 200)

    # 7. Get the role and check the updated content
    resp = session.get(req_url)
    check_status_code(resp, 200)
    resp_data = resp.json()
    assert resp_data["rules"] == []
    assert resp_data["metadata"]["uid"] != ""
    assert resp_data["metadata"]["name"] == name
    assert (
        before_update
        < datetime.strptime(resp_data["metadata"]["modified"], "%Y-%m-%dT%H:%M:%S.%f%z")
        < datetime.now(timezone.utc)
    )
    assert resp_data["metadata"]["labels"] == {"Testlabel": "Testlabel"}

    # 8. Update the role with an empty update and expect failure
    try:
        session.put(req_url, json={})
    except requests.HTTPError as e:
        check_status_code(e.response, 422)
        pass

    # 9. Create a role with the same name and expect failure
    try:
        session.post(
            urljoin(base_url, url), json={"metadata": {"name": name}, "rules": []}
        )
    except requests.HTTPError as e:
        check_status_code(e.response, 409)
        pass

    # 10. Delete the role created earlier
    resp = session.delete(req_url)
    check_status_code(resp, 200)

    # 11. List the roles and verify that the deleted one is not present
    resp = session.get(urljoin(base_url, url))
    check_status_code(resp, 200)
    resp_data = resp.json()
    for item in resp_data["items"]:
        if item["metadata"]["deleted"] is not None:
            assert item["metadata"]["name"] == name
        else:
            assert item["metadata"]["name"] != name


def test_rolebindings_crud(session):
    """Test basic rolebinding functionality with the session library.
    Rok cli can't be used here, because it doesn't implement rolebinding calls (yet).
    The test method performs the following tests for rolebindings:

    1. Delete a non-existent rolebinding and expect failure
    2. Get a non-existent rolebinding and expect failure
    3. Update a non-existent rolebinding and expect failure
    4. Create a rolebinding
    5. Get the rolebinding and check the content
    6. Update the rolebinding
    7. Get the rolebinding and check the content
    8. Perform an empty update of the rolebinding and expect failure
    9. Create a rolebinding with the same name and expect failure
    10. Delete the rolebinding created earlier
    11. List the rolebindings and verify that the deleted one is not present
    """

    base_url = session.base_url
    name = "e2e_test_rolebinding_2b_deleted"
    url = "/core/rolebindings"
    req_url = urljoin(urljoin(base_url, url) + "/", name)

    # 1. Delete a non-existent rolebinding and expect failure
    try:
        session.delete(req_url)
    except requests.HTTPError as e:
        check_status_code(e.response, 404)
        pass

    # 2. Get a non-existent rolebinding and expect failure
    try:
        session.get(req_url)
    except requests.HTTPError as e:
        check_status_code(e.response, 404)
        pass

    # 3. Update a non-existent rolebinding and expect failure
    data = {
        "users": [],
        "roles": [],
        "metadata": {
            "uid": "",
            "name": name,
            "created": "2021-09-09T08:18:50.856741+00:00",
            "modified": "2021-09-09T08:18:50.856741+00:00",
            "labels": {},
        },
    }
    try:
        session.put(req_url, json=data)
    except requests.HTTPError as e:
        check_status_code(e.response, 404)
        pass

    # 4. Create a rolebinding
    before_creation = datetime.now(timezone.utc)
    resp = session.post(
        urljoin(base_url, url),
        json={"metadata": {"name": name}, "users": [], "roles": []},
    )
    check_status_code(resp, 200)

    # 5. Get the rolebinding and check the content
    resp = session.get(req_url)
    check_status_code(resp, 200)
    resp_data = resp.json()
    assert resp_data["users"] == []
    assert resp_data["roles"] == []
    assert resp_data["metadata"]["uid"] != ""
    assert resp_data["metadata"]["name"] == name
    assert (
        before_creation
        < datetime.strptime(resp_data["metadata"]["created"], "%Y-%m-%dT%H:%M:%S.%f%z")
        < datetime.now(timezone.utc)
    )

    # 6. Update the rolebinding
    before_update = datetime.now(timezone.utc)

    data = {
        "users": [],
        "roles": [],
        "metadata": {
            "uid": resp_data["metadata"]["uid"],
            "name": name,
            "created": resp_data["metadata"]["created"],
            "modified": resp_data["metadata"]["modified"],
            "labels": {"Testlabel": "Testlabel"},
        },
    }
    resp = session.put(req_url, json=data)
    check_status_code(resp, 200)

    # 7. Get the rolebinding and check the updated content
    resp = session.get(req_url)
    check_status_code(resp, 200)
    resp_data = resp.json()
    assert resp_data["users"] == []
    assert resp_data["roles"] == []
    assert resp_data["metadata"]["uid"] != ""
    assert resp_data["metadata"]["name"] == name
    assert (
        before_update
        < datetime.strptime(resp_data["metadata"]["modified"], "%Y-%m-%dT%H:%M:%S.%f%z")
        < datetime.now(timezone.utc)
    )
    assert resp_data["metadata"]["labels"] == {"Testlabel": "Testlabel"}

    # 8. Update the rolebinding with an empty update and expect failure
    try:
        session.put(req_url, json={})
    except requests.HTTPError as e:
        check_status_code(e.response, 422)
        pass

    # 9. Create a rolebinding with the same name and expect failure
    try:
        session.post(
            urljoin(base_url, url),
            json={"metadata": {"name": name}, "users": [], "roles": []},
        )
    except requests.HTTPError as e:
        check_status_code(e.response, 409)
        pass

    # 10. Delete the rolebinding created earlier
    resp = session.delete(req_url)
    check_status_code(resp, 200)

    # 11. List the rolebindings and verify that the deleted one is not present
    resp = session.get(urljoin(base_url, url))
    check_status_code(resp, 200)
    resp_data = resp.json()
    for item in resp_data["items"]:
        if item["metadata"]["deleted"] is not None:
            assert item["metadata"]["name"] == name
        else:
            assert item["metadata"]["name"] != name


def test_gmp_crud():
    """Test basic metrics providers functionality over the rok cli.
    The test method performs the following tests for each type of metrics provider:

    1. Delete a non-existent metrics provider and expect failure
    2. Get a non-existent metrics provider and expect failure
    3. Update a non-existent metrics provider and expect failure
    4. Create a metrics provider
    5. Get the metrics provider and check the content
    6. Update the metrics provider
    7. Get the metrics provider and check the content
    8. Perform an empty update of the metrics provider and expect failure
    9. Create a metrics provider with the same name and expect failure
    10. Delete the metrics provider
    11. List the metrics providers and verify that the deleted one is not present
    """
    # Set up the input parameters based on the metrics provider type
    # The values for the creation:
    prom_type_details = {"url": "http://firstprometheusurl:8081"}
    stat_type_details = {"metrics": {"m1": 1, "m2": 2}}
    kafka_type_details = {
        "url": "http://firstkafkaurl:8180",
        "comparison_column": "compcol",
        "value_column": "valcol",
        "table": "table_name",
    }
    # The values for the update:
    new_url = "https://newurl:8083"
    new_metrics = {"m3": 3}
    new_table = "new_table_name"
    # Save them in a dict:
    type_details = {
        _MetricsProviderType.PROMETHEUS: {
            "create": prom_type_details,
            "update": {**prom_type_details, "url": new_url},
        },
        _MetricsProviderType.STATIC: {
            "create": stat_type_details,
            "update": {**stat_type_details, "metrics": new_metrics},
        },
        _MetricsProviderType.KAFKA: {
            "create": kafka_type_details,
            "update": {**kafka_type_details, "table": new_table},
        },
    }
    # Prepare the argument strings for create:
    create_args = {
        _MetricsProviderType.PROMETHEUS: f"--url {prom_type_details['url']}",
        _MetricsProviderType.STATIC: " ".join(
            f"-m {m} {v}" for m, v in stat_type_details["metrics"].items()
        ),
        _MetricsProviderType.KAFKA: (
            f"--comparison-column {kafka_type_details['comparison_column']} "
            f"--value-column {kafka_type_details['value_column']} "
            f"--table {kafka_type_details['table']} "
            f"--url {kafka_type_details['url']}"
        ),
    }
    # Prepare the argument strings for update:
    update_args = {
        _MetricsProviderType.PROMETHEUS: f"--url {new_url}",
        _MetricsProviderType.STATIC: " ".join(
            f"-m {m} {v}" for m, v in new_metrics.items()
        ),
        _MetricsProviderType.KAFKA: f"--table {new_table}",
    }
    for mp_type in _MetricsProviderType:
        # 1. Delete a non-existent metrics provider and expect failure
        name = f"e2e_test_{mp_type.value}_gmp_2b_deleted"
        error_message = f"The non-existent metrics provider {name} could be deleted."
        run(
            f"rok core gmp delete {name}",
            condition=check_return_code(error_message, expected_code=1),
            retry=0,
        )
        # 2. Get a non-existent metrics provider and expect failure
        error_message = f"The non-existent metrics provider {name} could be retrieved."
        run(
            f"rok core gmp get {name}",
            condition=check_return_code(error_message, expected_code=1),
            retry=0,
        )
        # 3. Update a non-existent metrics provider and expect failure
        error_message = f"The non-existent metrics provider {name} could be updated."
        run(
            f"rok core gmp update --url {new_url} {name}",
            condition=check_return_code(error_message, expected_code=1),
            retry=0,
        )
        # 4. Create a metrics provider
        error_message = f"The metrics provider {name} could not be created."
        expected_type_details = type_details[mp_type]["create"]
        run(
            f"rok core gmp create --name {name} --type {mp_type.value} "
            f"{create_args[mp_type]} -o json",
            condition=check_metrics_provider_content(
                error_message,
                name=name,
                type=mp_type.value,
                type_details=expected_type_details,
            ),
            retry=0,
        )
        # 5. Get the metrics provider and check the content
        error_message = f"The metrics provider {name} could not be retrieved."
        run(
            f"rok core gmp get {name} -o json",
            condition=check_metrics_provider_content(
                error_message,
                name=name,
                type=mp_type.value,
                type_details=expected_type_details,
            ),
            retry=0,
        )
        # 6. Update the metrics provider
        error_message = f"The metrics provider {name} could not be updated."
        expected_type_details = type_details[mp_type]["update"]
        run(
            f"rok core gmp update {name} {update_args[mp_type]} -o json",
            condition=check_metrics_provider_content(
                error_message,
                name=name,
                type=mp_type.value,
                type_details=expected_type_details,
            ),
            retry=0,
        )
        # 7. Get the metrics provider and check the content
        error_message = f"The metrics provider {name} could not be retrieved."
        run(
            f"rok core gmp get {name} -o json",
            condition=check_metrics_provider_content(
                error_message,
                name=name,
                type=mp_type.value,
                type_details=expected_type_details,
            ),
            retry=0,
        )
        # 8. Perform an empty update of the metrics provider and expect failure
        error_message = (
            f"The metrics provider {name} was successfully updated without change."
        )
        run(
            f"rok core gmp update {name} {update_args[mp_type]} -o json",
            condition=check_return_code(error_message, expected_code=1),
            retry=0,
        )
        # 9. Create a metrics provider with the same name and expect failure
        error_message = f"The existing metrics provider {name} could be created."
        other_mp_type = (
            _MetricsProviderType.STATIC
            if mp_type == _MetricsProviderType.PROMETHEUS
            else _MetricsProviderType.PROMETHEUS
        )
        run(
            f"rok core gmp create --name {name} --type {other_mp_type.value} "
            f"{create_args[other_mp_type]} -o json",
            condition=check_return_code(error_message, expected_code=1),
            retry=0,
        )
        # 10. Delete the metrics provider
        error_message = f"The metrics provider {name} could not be deleted."
        run(
            f"rok core gmp delete {name}",
            condition=check_return_code(error_message),
            retry=0,
        )
        # 11. List the metrics providers and verify that the deleted one is not present
        time.sleep(_GC_DELAY)
        error_message = "The metrics providers could not be retrieved."
        gmps = run(
            "rok core gmp list -o json",
            condition=check_return_code(error_message),
            retry=0,
        ).json
        err_msg_fmt = "The list of metrics providers contains deleted ones: {name}"
        for gmp in gmps:
            observed_name = gmp["metadata"]["name"]
            assert observed_name != name, err_msg_fmt.format(name=observed_name)


def test_global_metric_crud():
    """Test basic metric functionality over the rok cli.

    1. Delete a non-existent metric and expect failure
    2. Get a non-existent metric and expect failure
    3. Update a non-existent metric and expect failure
    4. Create a metric
    5. Get the metric and check the content
    6. Update the metric
    7. Get the metric and check the content
    8. Perform an empty update of the metric and expect failure
    9. Create a metric with the same name and expect failure
    10. Delete the metric
    11. List the metrics and verify that the deleted metrics aren't present
    """
    # 1. Delete a non-existent metric and expect failure
    name = "e2e_test_metric_2_be_deleted"
    error_message = f"The non-existent global metric {name} could be deleted."
    run(
        f"rok core globalmetric delete {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 2. Get a non-existent metric and expect failure
    error_message = f"The non-existent global metric {name} could be retrieved."
    run(
        f"rok core globalmetric get {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 3. Update a non-existent metric and expect failure
    error_message = f"The non-existent global metric {name} could be updated."
    run(
        f"rok core globalmetric update --max 30 {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 4. Create a metric
    mp_name = "non-existent-gmp-name"
    mmin = 5
    mmax = 6
    error_message = f"The global metric {name} could not be created."
    run(
        f"rok core globalmetric create --name {name} --gmp-name {mp_name} "
        f"--min {mmin} --max {mmax} -o json",
        condition=check_metric_content(
            error_message, name=name, mp_name=mp_name, min=mmin, max=mmax
        ),
        retry=0,
    )
    # 5. Get the metric and check the content
    error_message = f"The global metric {name} could not be retrieved."
    run(
        f"rok core globalmetric get {name} -o json",
        condition=check_metric_content(
            error_message, name=name, mp_name=mp_name, min=mmin, max=mmax
        ),
        retry=0,
    )
    # 6. Update the metric
    error_message = f"The global metric {name} could not be updated."
    new_min = -2
    new_max = -1
    run(
        f"rok core globalmetric update {name} --min {new_min} --max {new_max} -o json",
        condition=check_metric_content(
            error_message,
            name=name,
            mp_name=mp_name,
            min=new_min,
            max=new_max,
        ),
        retry=0,
    )
    # 7. Get the metric and check the content
    error_message = f"The global metric {name} could not be retrieved."
    run(
        f"rok core globalmetric get {name} -o json",
        condition=check_metric_content(
            error_message,
            name=name,
            mp_name=mp_name,
            min=new_min,
            max=new_max,
        ),
        retry=0,
    )
    # 8. Perform an empty update of the metric and expect failure
    error_message = f"The global metric {name} was updated despite no change."
    run(
        f"rok core globalmetric update {name} --min {new_min} -o json",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 9. Create a metric with the same name and expect failure
    error_message = f"The existing global metric {name} could be created."
    new_mp_name = "other-non-existent-gmp"
    run(
        f"rok core globalmetric create --name {name} --gmp-name {new_mp_name} "
        f"--min {mmin} --max {mmax} -o json",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 10. Delete the metric
    error_message = f"The global metric {name} could not be deleted."
    run(
        f"rok core globalmetric delete {name}",
        condition=check_return_code(error_message),
        retry=0,
    )
    # 11. List the metrics and verify that the deleted metric is not present
    time.sleep(_GC_DELAY)
    error_message = "The global metrics could not be retrieved."
    metrics = run(
        "rok core globalmetric list -o json",
        condition=check_return_code(error_message),
        retry=0,
    ).json
    err_msg_fmt = "The list of global metrics contains deleted ones: {name}"
    for metric in metrics:
        observed_name = metric["metadata"]["name"]
        assert observed_name != name, err_msg_fmt.format(name=name)
