import pytest
import random
import time

from utils import run, check_return_code, create_cluster_info, get_other_cluster
from environment import Environment, create_magnum_cluster_environment
from resource_definitions import (
    ProjectDefinition,
    MagnumClusterDefinition,
    ResourceKind,
)

METRICS = [
    "heat_demand_zone_1",
    "heat_demand_zone_2",
    "heat_demand_zone_3",
    "heat_demand_zone_4",
    "heat_demand_zone_5",
]
CONSTRAINT_EXPRESSIONS = {
    True: [
        "location is DE",
        "location=DE",
        "location = DE",
        "location == DE",
        "location in (DE,)",
    ],
    False: ["location is not DE", "location != DE", "location not in (DE,)"],
}
_GC_DELAY = 3


def test_crud_project():
    """Test basic projects functionality over the rok cli.
    The test method performs the following tests for each type of project:

    1. Delete a non-existent project and expect failure
    2. Get a non-existent project and expect failure
    3. Update a non-existent project and expect failure
    4. Create a project
    5. Get the project and check the content
    6. Update the project
    7. Get the project and check the content
    8. Perform an empty update of the project and expect failure
    9. Create a project with the same name and expect failure
    10. Delete the project
    11. List the projects and verify that the deleted one is not present
    """
    new_url = "https://newurl:8083"

    # 1. Delete a non-existent project and expect failure
    name = "e2e_test_project_2b_deleted"
    error_message = f"The non-existent project {name} could be deleted."
    run(
        f"rok os project delete {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 2. Get a non-existent project and expect failure
    error_message = f"The non-existent project {name} could be retrieved."
    run(
        f"rok os project get {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 3. Update a non-existent project and expect failure
    error_message = f"The non-existent project {name} could be updated."
    run(
        f"rok os project update --auth-url {new_url} {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )

    # 4. Create a project
    name = "test-crud-project"
    application_credentials = ("mock_id", "mock_secret")
    auth_url = "mock_auth_url.com"
    template_uuid = "mock_template_uuid"
    environment = {
        10: [
            ProjectDefinition(
                name,
                auth_url,
                template_uuid,
                application_credentials=application_credentials,
            )
        ]
    }

    with Environment(environment) as env:
        project = env.resources[ResourceKind.PROJECT][0]

        # 5. Get the project and check the content
        project_json = project.get_resource()
        assert project_json["metadata"]["name"] == name
        assert project_json["spec"]["url"] == auth_url
        assert project_json["spec"]["template"] == template_uuid
        assert project_json["spec"]["auth"]["type"] == "application_credential"
        application_credential = project_json["spec"]["auth"]["application_credential"]
        assert application_credential["id"] == "mock_id"
        assert application_credential["secret"] == "mock_secret"

        # 6. Update the project
        project.update_resource(
            auth_url=new_url,
            password_credentials=("my_project_id", "my_user_id", "my_auth_password"),
            application_credentials=(),
        )

        # 7. Get the project and check the content
        project_json = project.get_resource()
        assert project_json["spec"]["url"] == new_url
        assert project_json["spec"]["auth"]["type"] == "password"
        password_credential = project_json["spec"]["auth"]["password"]
        assert password_credential["project"]["id"] == "my_project_id"
        assert password_credential["user"]["id"] == "my_user_id"
        assert password_credential["user"]["password"] == "my_auth_password"

        # 8. Perform an empty update of the project and expect failure
        error_message = f"The project {name} was successfully updated without change."
        run(
            f"rok os project update {name} --auth-url {new_url} -o json",
            condition=check_return_code(error_message, expected_code=1),
            retry=0,
        )

        # 9. Create a project with the same name and expect failure
        failing_project = ProjectDefinition(
            name, "url.com", "my_template", application_credentials=("my-id", "secret")
        )
        run(
            failing_project.creation_command(),
            condition=check_return_code(error_message, expected_code=1),
        )

        # 10. Delete the project
        # Done by exiting the Environment's context manager

    # 11. List the projects and verify that the deleted one is not present
    time.sleep(_GC_DELAY)
    error_message = "The projects could not be retrieved."
    projects = run(
        "rok os project list -o json",
        condition=check_return_code(error_message),
        retry=0,
    ).json
    err_msg_fmt = "The list of projects contains deleted ones: {name}"
    for project in projects:
        observed_name = project["metadata"]["name"]
        assert observed_name != name, err_msg_fmt.format(name=observed_name)


def test_crud_magnum_cluster(template_id, project_id, user_id, user_password, auth_url):
    """Test basic projects functionality over the rok cli.
    The test method performs the following tests for each type of project:

    1. Delete a non-existent magnum cluster and expect failure
    2. Get a non-existent magnum cluster and expect failure
    3. Update a non-existent magnum cluster and expect failure
    4. Create a magnum cluster
    5. Get the magnum cluster and check the content
    6. Update the magnum cluster
    7. Get the magnum cluster and check the content
    8. Perform an empty update of the magnum cluster and expect failure
    9. Create a magnum cluster with the same name and expect failure
    10. Delete the magnum cluster
    11. List the magnum clusters and verify that the deleted one is not present

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    # 1. Delete a non-existent magnum cluster and expect failure
    name = "e2e_test_magnum_cluster_2b_deleted"
    error_message = f"The non-existent magnum cluster {name} could be deleted."
    run(
        f"rok os cluster delete {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 2. Get a non-existent magnum cluster and expect failure
    error_message = f"The non-existent magnum cluster {name} could be retrieved."
    run(
        f"rok os cluster get {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )
    # 3. Update a non-existent magnum cluster and expect failure
    error_message = f"The non-existent magnum cluster {name} could be updated."
    run(
        f"rok os cluster update --node-count {2} {name}",
        condition=check_return_code(error_message, expected_code=1),
        retry=0,
    )

    # 4. Create a magnum cluster
    project_name = "test-crud_mgclust-project"
    cluster_name = "test-crud_mgclust-cluster"

    environment = create_magnum_cluster_environment(
        [project_name],
        cluster_name,
        template_id,
        project_id,
        user_id,
        user_password,
        auth_url,
    )
    with Environment(environment) as env:
        cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

        cluster.check_state("CREATING")

        # cluster.check_state("RUNNING", within=1800, after_delay=300, interval=30)

        # 5. Get the magnum cluster and check the content
        cluster_json = cluster.get_resource()
        assert cluster_json["metadata"]["labels"] == {}
        cluster_status = cluster_json["status"]
        assert cluster_status["project"]["name"] == project_name
        assert cluster_status["cluster_id"] is not None
        assert cluster_status["node_count"] is None
        assert cluster_status["template"] == template_id

        # 6. Update the magnum cluster
        cluster.update_resource(labels={"label1": "value1", "label2": "value2"})

        cluster_json = cluster.get_resource()
        assert cluster_json["metadata"]["labels"] == {
            "label1": "value1",
            "label2": "value2",
        }

        # 7. Get the magnum cluster and check the content
        cluster_json = cluster.get_resource()
        assert cluster_json["metadata"]["labels"] == {
            "label1": "value1",
            "label2": "value2",
        }
        cluster_status = cluster_json["status"]
        assert cluster_status["project"]["name"] == project_name
        assert cluster_status["cluster_id"] is not None
        assert cluster_status["node_count"] is None
        assert cluster_status["template"] == template_id

        # 8. Perform an empty update of the magnum cluster and expect failure
        error_message = (
            f"The magnum cluster {name} was successfully updated" f" without change."
        )
        run(
            f"rok os cluster update {name} -l label1=value1 -l label2=value2 -o json",
            condition=check_return_code(error_message, expected_code=1),
            retry=0,
        )

        # 9. Create a magnum cluster with the same name and expect failure
        failing_magnum_cluster = MagnumClusterDefinition(
            cluster_name, master_count=1, node_count=1
        )
        run(
            failing_magnum_cluster.creation_command(),
            condition=check_return_code(error_message, expected_code=1),
        )

        # 10. Delete the magnum cluster
        # Done by exiting the Environment's context manager

    # 11. List the magnum clusters and verify that the deleted one is not present
    time.sleep(_GC_DELAY)
    error_message = "The magnum clusters could not be retrieved."
    magnum_projects = run(
        "rok os cluster list -o json",
        condition=check_return_code(error_message),
        retry=0,
    ).json
    err_msg_fmt = "The list of magnum clusters contains deleted ones: {name}"
    for magnum_cluster in magnum_projects:
        observed_name = magnum_cluster["metadata"]["name"]
        assert observed_name != name, err_msg_fmt.format(name=observed_name)


@pytest.mark.skip(
    reason=(
        "The resize endpoint is not supported by the OpenStack infrastructure used"
        " by the end-to-end test."
    )
)
def test_cluster_resize():
    assert False


def test_scheduler_project_label_constraints(
    template_id, project_id, user_id, user_password, auth_url
):
    """Basic end-to-end testing of label constraints for the Magnum cluster resources.

    The test repeatedly creates an Magnum cluster and two projects with the
    labels `location=DE` and `location=IT` randomly assigned to the projects.
    Each time the Magnum cluster is created with a different project label
    constraint, thus creating an expectation as to which project it should be
    scheduled.

    The test iterates over the `CONSTRAINT_EXPRESSIONS` which contains the
    project label constraints for the Magnum cluster and a boolean indicating
    whether the Magnum cluster due to this constraint is expected to be scheduled
    to the project with `location=DE`.

    The work workflow for each iteration is as follows:

        1. Create two projects with the project labels `location=DE` and `location=IT`
           (in random order);
        2. Create an Magnum cluster with the project label constraint given by
           `CONSTRAINT_EXPRESSIONS`;
        3. Ensure that the Magnum cluster was scheduled to the requested project;

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    num_projects = 2
    countries = ["DE", "IT"]

    for match, constraints in CONSTRAINT_EXPRESSIONS.items():

        # We expect the cluster to be scheduled on the DE project if match and
        # otherwise on the IT project, so we remember this index into the
        # 'countries' list (and later also into the 'projects' list).
        expected_index = 0 if match else 1  # choose DE if match else IT

        for constraint in constraints:
            # The two projects used in this test (randomly ordered)
            project_names = ["test_e2e_scheduling_1", "test_e2e_scheduling_2"]
            projects = random.sample(project_names, num_projects)
            metric_names = random.sample(set(METRICS), num_projects)
            weights = [1] * num_projects

            # 1. Create two projects with the project labels `location=DE` and
            # `location=IT` (in random order);
            # 2. Create an Magnum Cluster with the project label constraint given by
            #     `CONSTRAINT_EXPRESSIONS`;
            cluster_name = "cluster-scheduling-test"
            project_labels = create_cluster_info(projects, "location", countries)
            metrics = create_cluster_info(projects, metric_names, weights)
            environment = create_magnum_cluster_environment(
                projects,
                cluster_name,
                template_id,
                project_id,
                user_id,
                user_password,
                auth_url,
                metrics=metrics,
                project_labels=project_labels,
                constraints=[constraint],
            )
            with Environment(environment) as env:
                cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

                # 3. Ensure that the Magnum cluster was scheduled to the requested
                # project;
                cluster.check_running_on(projects[expected_index])


def test_scheduler_projects_with_metrics(
    template_id, project_id, user_id, user_password, auth_url
):
    """Basic end-to-end testing of projects metrics

    Project metrics and metrics provider are tested multiple times (3) as follows:

        1. Create two projects with a randomly selected metric assigned to each project
        and a Magnum cluster.
        2. Ensure that the Magnum Cluster was scheduled to the expected project;

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    for _ in range(3):
        # The two projects and metrics used in this test (randomly ordered)
        num_projects = 2
        project_names = ["test_e2e_scheduling_1", "test_e2e_scheduling_2"]
        projects = random.sample(project_names, num_projects)
        metric_names = random.sample(set(METRICS), num_projects)
        weights = [1] * num_projects

        # Determine to which project we expect the Magnum cluster to be scheduled.
        # (Due to the implementation of the dummy metrics provider, the metric
        # with the highest suffix will have the highest value. Therefore
        # (and since the weights of the metrics will be the same
        # for all projects), the project with the highest metric name suffix
        # is expected to be chosen by the scheduler.)
        metric_max = max(metric_names, key=lambda x: int(x[-1]))
        max_index = next(
            i for i in range(num_projects) if metric_max == metric_names[i]
        )
        expected_project = projects[max_index]

        # 1. Create two projects with a randomly selected metric assigned to each
        # project and an Magnum cluster.
        metrics = create_cluster_info(projects, metric_names, weights)
        cluster_name = "cluster-scheduling-test"
        environment = create_magnum_cluster_environment(
            projects,
            cluster_name,
            template_id,
            project_id,
            user_id,
            user_password,
            auth_url,
            metrics=metrics,
        )
        with Environment(environment) as env:
            cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

            # 2. Ensure that the Magnum Cluster was scheduled to the expected project;
            cluster.check_running_on(expected_project)


def test_scheduler_projects_one_with_metrics(
    template_id, project_id, user_id, user_password, auth_url
):
    """Basic end-to-end testing of projects metrics

    Project metrics and metrics provider are tested multiple times (3) as follows:

        1. Create two projects with a randomly selected metric assigned only to one
            randomly selected project, and an Magnum cluster. The project with the
            metric is expected to be chosen by the scheduler.
        2. Ensure that the Magnum cluster was scheduled to the expected project;

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    for _ in range(3):

        # the two projects and one metric to be used in this test
        num_projects = 2
        project_names = ["test_e2e_scheduling_1", "test_e2e_scheduling_2"]
        projects = random.sample(project_names, num_projects)
        metric_names = [random.choice(METRICS)]
        weights = [1]

        # Determine to which project we expect the Magnum cluster to be scheduled.
        # (The project with the metric is expected to be chosen by the scheduler.)
        expected_project = project_names[0]

        # 1. Create two projects with a randomly selected metric assigned only to one
        #    randomly selected project, and an Magnum cluster.
        metrics_by_project = create_cluster_info(project_names, metric_names, weights)
        cluster_name = "cluster-scheduling-test"
        environment = create_magnum_cluster_environment(
            projects,
            cluster_name,
            template_id,
            project_id,
            user_id,
            user_password,
            auth_url,
            metrics=metrics_by_project,
        )
        with Environment(environment) as env:
            cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

            # 2. Ensure that the Magnum cluster was scheduled to the expected project;
            cluster.check_running_on(expected_project)


def test_scheduler_project_label_constraints_with_metrics(
    template_id, project_id, user_id, user_password, auth_url
):
    """Basic end-to-end testing of Magnum cluster project label constraints with
    metrics

    Test iterates over the `CONSTRAINT_EXPRESSIONS` and applies workflow as follows:

        1. Create an Magnum cluster (with a project label constraint given from
            `CONSTRAINT_EXPRESSIONS`) and two projects with project labels (randomly
             selected from: `location=DE`, `location=IT`) and randomly selected metrics.
        2. Ensure that the Magnum cluster was scheduled to the project, which the
            Magnum cluster selected through its project label constraints. The project
            label constraints have priority over the rank calculated from the metrics.

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    num_projects = 2
    countries = ["DE", "IT"]
    for match, constraints in CONSTRAINT_EXPRESSIONS.items():

        # We expect the app to be scheduled on the DE project if match and
        # otherwise on the IT project, so we remember this index into the
        # 'countries' list (and later also into the 'projects' list).
        expected_index = 0 if match else 1  # choose DE if match else IT

        for constraint in constraints:
            # The two projects, countries and metrics used in this test
            # (randomly ordered)
            project_names = ["test_e2e_scheduling_1", "test_e2e_scheduling_2"]
            projects = random.sample(project_names, num_projects)
            metric_names = random.sample(set(METRICS), num_projects)
            weights = [1] * num_projects

            # 1. Create an Magnum cluster (with a project label constraint given from
            #  `CONSTRAINT_EXPRESSIONS`) and two projects with project labels (randomly
            #   selected from: `location=DE`, `location=IT`) and randomly selected
            #   metrics.
            project_labels = create_cluster_info(projects, "location", countries)
            metrics_by_project = create_cluster_info(projects, metric_names, weights)
            cluster_name = "cluster-scheduling-test"
            environment = create_magnum_cluster_environment(
                projects,
                cluster_name,
                template_id,
                project_id,
                user_id,
                user_password,
                auth_url,
                metrics=metrics_by_project,
                project_labels=project_labels,
                constraints=[constraint],
            )
            with Environment(environment) as env:
                cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

                # 2. Ensure that the Magnum cluster was scheduled to the requested
                # project;
                cluster.check_running_on(projects[expected_index])


def test_one_unreachable_metrics_provider(
    template_id, project_id, user_id, user_password, auth_url
):
    """Basic end-to-end testing of unreachable metrics provider

    Test applies workflow as follows:

        1. Create one Magnum cluster, and two projects with metrics - one with
            metrics from a reachable metrics provider and one with
            the metrics from an unreachable provider.
        2. Ensure that the Magnum cluster was scheduled to the cluster with
            the metrics provided by the reachable metrics provider;
        3. Ensure that the cluster without failing metrics is online and not reporting
            any failing metrics.
        4. Ensure that the status of the cluster with failing metrics was updated to
            notify the user of the failing metrics (state changed and list of reasons
            added).

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    # The two projects and metrics used in this test (randomly ordered)
    num_projects = 2
    project_names = ["test_e2e_scheduling_1", "test_e2e_scheduling_2"]
    projects = random.sample(project_names, num_projects)
    metric_names = ["heat_demand_zone_unreachable"] * (num_projects - 1) + [
        random.choice(METRICS)
    ]
    weights = [1] * num_projects

    metrics_by_project = create_cluster_info(projects, metric_names, weights)

    # Determine to which project we expect the Magnum cluster to be scheduled.
    # (The project with the reachable metric is expected to be chosen by the scheduler.)
    expected_project = next(
        c
        for c in projects
        if "heat_demand_zone_unreachable" not in metrics_by_project[c]
    )

    # 1. Create one Magnum cluster, one project without metrics, and one with
    #     the metric `heat_demand_zone_unreachable`.
    cluster_name = "cluster-scheduling-test"
    environment = create_magnum_cluster_environment(
        projects,
        cluster_name,
        template_id,
        project_id,
        user_id,
        user_password,
        auth_url,
        metrics=metrics_by_project,
    )
    with Environment(environment, creation_delay=30) as env:
        cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

        cluster.check_state("CREATING")

        # 2. Ensure that the Magnum cluster was scheduled to the expected project;
        cluster.check_running_on(expected_project)

        # 3. Ensure that the project without failing metrics is online and not reporting
        # any failing metrics.
        expected_project_res = env.get_resource_definition(
            ResourceKind.PROJECT, expected_project
        )
        assert expected_project_res.get_state() == "ONLINE"
        assert expected_project_res.get_metrics_reasons() == {}

        # 4. Ensure that the status of the project with failing metrics was updated to
        # notify the user of the failing metrics (state changed and list of reasons
        # added).
        other_project_name = get_other_cluster(expected_project, projects)
        other_project_res = env.get_resource_definition(
            ResourceKind.PROJECT, other_project_name
        )

        assert other_project_res.get_state() == "FAILING_METRICS"
        metrics_reasons = other_project_res.get_metrics_reasons()
        assert "heat_demand_zone_unreachable" in metrics_reasons
        assert (
            metrics_reasons["heat_demand_zone_unreachable"]["code"]
            == "UNREACHABLE_METRICS_PROVIDER"
        )


def test_all_unreachable_metrics_provider(
    template_id, project_id, user_id, user_password, auth_url
):
    """Basic end to end testing of unreachable metrics provider

    Test applies workflow as follows:

        1. Create one Magnum cluster, one project without metrics, and one with
            the metric `heat_demand_zone_unreachable`.
            Any project might be chosen by the scheduler.
        2. Ensure that although all metrics providers are unreachable, the scheduler
            manages to schedule the Magnum cluster to one of the matching projects.
        3. Ensure that the status of the project with metrics was updated to notify
            the user of the failing metrics (state changed and list of reasons added).
        4. Ensure that the project without metrics is not reporting any failing metrics.

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    # The two projects and metrics used in this test (randomly ordered)
    num_projects = 2
    project_names = ["test_e2e_scheduling_1", "test_e2e_scheduling_2"]
    projects = random.sample(project_names, num_projects)
    metric_names = ["heat_demand_zone_unreachable"]
    weights = [1]

    metrics_by_project = create_cluster_info(projects, metric_names, weights)

    # 1. Create one Magnum cluster, one project without metrics, and one with
    #     the metric `heat_demand_zone_unreachable`.
    cluster_name = "cluster-scheduling-test"
    environment = create_magnum_cluster_environment(
        projects,
        cluster_name,
        template_id,
        project_id,
        user_id,
        user_password,
        auth_url,
        metrics=metrics_by_project,
    )
    with Environment(environment, creation_delay=20) as env:
        cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

        cluster.check_state("CREATING")

        # 2. Ensure that although all metrics providers are unreachable, the scheduler
        #    manages to schedule the Magnum cluster to one of the matching projects.
        # The Magnum cluster may run on any of the projects.
        running_on = cluster.get_running_on()
        assert running_on in projects

        # 3. Ensure that the status of the project with metrics was updated to notify
        # the user of the failing metrics (state changed and list of reasons added).
        project_with_metric = env.resources[ResourceKind.PROJECT][0]
        assert project_with_metric.get_state() == "FAILING_METRICS"
        metrics_reasons = project_with_metric.get_metrics_reasons()
        assert "heat_demand_zone_unreachable" in metrics_reasons
        assert (
            metrics_reasons["heat_demand_zone_unreachable"]["code"]
            == "UNREACHABLE_METRICS_PROVIDER"
        )

        # 4. Ensure that the project without metrics is not reporting any failing
        # metrics.
        project_wo_metric = env.resources[ResourceKind.PROJECT][1]
        assert project_wo_metric.get_state() == "ONLINE"
        assert project_wo_metric.get_metrics_reasons() == {}


def test_metric_not_in_database(
    template_id, project_id, user_id, user_password, auth_url
):
    """Basic end to end testing of project referencing a metric not found in the Krake
    database.

    Test applies workflow as follows:

        1. Create one Magnum cluster and one project with a reference to metric which is
            not present in the database.
        2. Ensure that even if the metrics fetching failed, the Magnum cluster is still
            deployed.
        3. Ensure that the status of the project with metrics was updated to notify
            the user of the failing metrics (state changed and list of reasons added).

    Args:
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.

    """
    # The two projects and metrics used in this test (randomly ordered)
    num_projects = 2
    project_names = ["test_e2e_scheduling_1", "test_e2e_scheduling_2"]
    chosen_project = random.sample(project_names, num_projects)[0]
    metric_names = ["non_existent_metric"]
    weights = [1]

    metrics_by_project = create_cluster_info([chosen_project], metric_names, weights)

    # 1. Create one Magnum cluster and one project with a reference to metric which is
    # not present in the database.
    cluster_name = "cluster-scheduling-test"
    environment = create_magnum_cluster_environment(
        [chosen_project],
        cluster_name,
        template_id,
        project_id,
        user_id,
        user_password,
        auth_url,
        metrics=metrics_by_project,
    )
    with Environment(environment, creation_delay=20) as env:
        cluster = env.resources[ResourceKind.MAGNUMCLUSTER][0]

        # 2. Ensure that even if the metrics fetching failed, the Magnum cluster is
        # still deployed.
        cluster.check_state("CREATING")
        running_on = cluster.get_running_on()
        assert running_on in chosen_project

        # 3. Ensure that the status of the project with metrics was updated to notify
        # the user of the failing metrics (state changed and list of reasons added).
        project = env.resources[ResourceKind.PROJECT][0]
        assert project.get_state() == "FAILING_METRICS"
        metrics_reasons = project.get_metrics_reasons()
        assert "non_existent_metric" in metrics_reasons
        assert metrics_reasons["non_existent_metric"]["code"] == "UNKNOWN_METRIC"
