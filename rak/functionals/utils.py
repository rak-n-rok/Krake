import json
import logging
import os
import subprocess
import time
from collections import defaultdict
from typing import NamedTuple

from dataclasses import MISSING

logger = logging.getLogger("krake.test_utils.run")

KRAKE_HOMEDIR = "/home/krake"
ROK_INSTALL_DIR = f"{KRAKE_HOMEDIR}/.local/bin"


class Response(object):
    """The response of a command

    Attributes:
        output (str): Output of the command
        returncode (int): Return code of the command
    """

    def __init__(self, output, returncode):
        self.output = output
        self.returncode = returncode
        self._json = MISSING  # Cache parsed JSON output

    @property
    def json(self):
        """str: Deserialized JSON of the command's output"""
        if self._json is MISSING:
            self._json = json.loads(self.output)
        return self._json


def run(command, retry=10, interval=1, condition=None, input=None):
    """Runs a subprocess

    This function runs the provided ``command`` in a subprocess.

    Tests are typically subjects to race conditions. We frequently have to
    wait for an object to reach a certain state (RUNNING, DELETED, ...)

    Therefore, this function implements a retry logic:

    - The ``condition`` callable takes the command's response as argument and
      checks if it suits a certain format.
    - The ``retry`` and ``interval`` arguments control respectively the number
      of retries the function should attempt before raising an
      `AssertionError`, and the number of seconds to wait between each retry.

    The signature of ``condition`` is:

    .. function:: my_condition(response)

        :param Response response: The command response.
        :raises AssertionError: Raised when the condition is not met.

    Note that is doesn't make sense to provide a ``condition`` without a
    ``retry``. One should rather test this condition in the calling function.

    Args:
        command (list): The command to run
        retry (int, optional): Number of retry to perform. Defaults to 10
        interval (int, optional): Interval in seconds between two retries
        condition (callable, optional): Condition that has to be met.
        input (str, optional): input given through stdin to the command.

    Returns:
        Response: The output and return code of the provided command

    Raises:
        AssertionError: Raise an exception if the ``condition`` is not met.

    Example:
        .. code:: python

            import util

            # This condition will check if the command has a null return
            # value
            def check_return_code(error_message):

                def validate(response):
                    assert response.returncode == 0, error_message

                return validate

            # This command has a risk of race condition
            some_command = "..."

            # The command will be retried 10 time until the command is
            # successful or will raise an AssertionError
            util.run(
                some_command,
                condition=check_return_code("error message"),
                retry=10,
                interval=1,
            )

    """
    if isinstance(command, str):
        command = command.split()

    logger.debug(f"Running: {command}")

    env = os.environ.copy()
    env["PATH"] = f"{ROK_INSTALL_DIR}:{env['PATH']}"

    while True:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            input=input,
        )

        response = Response(process.stdout.decode(), process.returncode)

        # If no condition has been given to check, simply return the response
        if condition is None:
            logger.debug(f"Response from the command: \n{response.output}")
            return response

        try:
            condition(response)
            # If condition is met, return the response
            logger.debug(f"Response from the command: \n{response.output}")
            return response
        except AssertionError:
            # If condition is not met, decrease the amount of retries and sleep
            logger.debug("Provided condition is not met")
            retry -= 1
            if retry <= 0:
                # All retries have failed
                raise
            logger.debug("Going to sleep... will retry")
            time.sleep(interval)


def check_app_state(state, error_message, reason=None):
    """Create a callable to verify the state of an Application obtained as response.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the state of the Application is different from the given
    one.

    Args:
        state (str): the state of the answered Application will be compared with this
            one.
        error_message (str): the message that will be displayed if the check fails.
        reason (str): if given, the reason of the Application (in case of FAILED state)
            will be compared to this one.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    """

    def validate(response):
        try:
            app_details = response.json
            assert app_details["status"]["state"] == state, error_message
            if reason:
                assert app_details["status"]["reason"]["code"] == reason, error_message
        except (KeyError, json.JSONDecodeError):
            raise AssertionError(error_message)

    return validate


def check_return_code(error_message, expected_code=0):
    """Create a callable to verify the return code of a response.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the return code of the response is different from the
    given one.

    Args:
        error_message (str): the message that will be displayed if the check fails.
        expected_code (int, optional): a bash return code, to check against the one of
            the given response.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    """

    def validate(response):
        assert response.returncode == expected_code, error_message

    return validate


def check_empty_list(error_message):
    """Create a callable to verify that a response is empty.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the response is not an empty list.

    Args:
        error_message (str): the message that will be displayed if the check fails.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    """

    def validate(response):
        try:
            assert response.json == [], error_message
        except json.JSONDecodeError:
            raise AssertionError(error_message)

    return validate


def check_resource_deleted(error_message):
    """Create a callable to verify that a resource is deleted.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the chosen resource is shown as existing in the response
    given to the callable

    Args:
        error_message (str): the message that will be displayed if the check fails.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    """

    def validate(response):
        assert "not found" in response.output, error_message
        assert response.returncode == 1

    return validate


def check_spec_container_image(expected_image, error_message):
    """Create a callable to verify that a resource has the right container image.

    To be used with the :meth:`run` function and a kubectl request. The callable will
    raise an :class:`AssertionError` if the response's image is not the given one. This
    image corresponds to the image name of the first container of the spec of the
    template of a deployment.

    Args:
        expected_image (str): name of the image that should be defined in the response.
        error_message (str): the message that will be displayed if the check fails.

    Returns:

    """

    def validate(response):
        try:
            image = response.json["spec"]["template"]["spec"]["containers"][0]["image"]
            assert image == expected_image, error_message
        except json.JSONDecodeError:
            raise AssertionError(error_message)

    return validate


def check_spec_replicas(expected_replicas, error_message):
    """Create a callable to verify that a resource has the correct number of replicas.

    To be used with the :meth:`run` function and a kubectl request. The callable will
    raise an :class:`AssertionError` if the response's number of replicas is not
    the given one. The number of replicas corresponds to the replicas in the spec
    of the deployment.

    Args:
        expected_replicas (int): number of replicas expected to be defined in the
            response.
        error_message (str): the message that will be displayed if the check fails.

    Returns:

    """

    def validate(response):
        try:
            replicas = response.json["spec"]["replicas"]
            assert replicas == expected_replicas, error_message
        except json.JSONDecodeError:
            raise AssertionError(error_message)

    return validate


def check_app_running_on(expected_cluster, error_message):
    """Create a callable to verify the cluster on which an Application is
    running obtained as a response.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the state of the Application is different
    from the given one.

    Args:
        expected_cluster (str): the name of the cluster on which the
            Application is expected to be running.
        error_message (str): the message that will be displayed if the
            check fails.

    Returns:
        callable: a condition that will check its given response against
            the parameters of the current function.

    """

    def validate(response):
        try:
            app_details = response.json
            observed_cluster = app_details["status"]["running_on"]["name"]
            assert observed_cluster == expected_cluster, error_message
        except json.JSONDecodeError:
            raise AssertionError(error_message)

    return validate


class ApplicationDefinition(NamedTuple):
    """Definition of an Application resource for the test environment
    :class:`Environment`.

    Describes how to create and delete an Application with the rok utility. Also defines
    the checks to perform to test if these two actions were successful.

    Args:
        name (str): name of the Application to create.
        manifest_path (str): path to the manifest file to use for the creation.
        constraints (list(str)): optional list of cluster label constraints
            to use for the creation of the application.
        migration (bool): optional migration flag indicating whether the
            application should be able to migrate.

    """

    name: str
    manifest_path: str
    constraints: list = []
    migration: bool = None
    kind: str = "Application"

    def creation_command(self):
        """Generate a command for creating an Application.

        Returns:
            str: the command to create an Application.

        """
        migration_flag = self._get_migration_flag(self.migration)
        constraints = " ".join(f"-L {constraint}" for constraint in self.constraints)
        return (
            f"rok kube app create {migration_flag} {constraints} "
            f"-f {self.manifest_path} {self.name}"
        )

    @staticmethod
    def _get_migration_flag(migration):
        if migration is False:
            migration_flag = "--disable-migration"
        elif migration is True:
            migration_flag = "--enable-migration"
        elif migration is None:
            migration_flag = ""
        else:
            raise RuntimeError("migration must be None, False or True.")
        return migration_flag

    def check_created(self):
        """Run the command for checking if the Application has been created.
        """
        error_message = (
            f"Unable to observe the application {self.name} in a RUNNING state"
        )
        run(
            f"rok kube app get {self.name} -f json",
            condition=check_app_state("RUNNING", error_message),
        )

    def delete_command(self):
        """Generate a command for deleting an Application.

        Returns:
            str: the command to delete an Application.

        """
        return f"rok kube app delete {self.name}"

    def check_deleted(self):
        """Run the command for checking if the Application has been deleted.
        """
        error_message = f"Unable to observe the application {self.name} deleted"
        run(
            f"rok kube app get {self.name}",
            condition=check_resource_deleted(error_message),
        )

    def update_command(self, cluster_labels=None, migration=None):
        """Generate a command for updating an application

        Args:
            cluster_labels (list(str)): optional list of cluster label constraints
            migration (bool): optional migration flag indicating whether the
                application should be able to migrate.

        Returns:
            str: the command to update the Application.

        """
        migration_flag = self._get_migration_flag(migration)
        clc_options = (
            " ".join(f"-L {constraint}" for constraint in cluster_labels)
            if cluster_labels
            else ""
        )
        return f"rok kube app update {clc_options} {migration_flag} {self.name}"

    def check_running_on(self, cluster_name):
        """Run the command for checking that the application is running on the
        specified cluster.

        Args:
            cluster_name (str): Name of the cluster on which the application is
                expected to run.
        """
        error_message = (
            f"Unable to observe that the application {self.name} "
            f"is running on cluster {cluster_name}."
        )
        run(
            f"rok kube app get {self.name} -f json",
            condition=check_app_running_on(cluster_name, error_message),
        )


class ClusterDefinition(NamedTuple):
    """Definition of a cluster resource for the test environment :class:`Environment`.

    Describes how to create and delete a cluster with the rok utility. Also defines
    the checks to perform to test if the deletion was successful.

    Args:
        name (str): name of the Application to create.
        kubeconfig_path (str): path to the kubeconfig file to use for the creation.
        labels (list(str)): list of cluster labels to use for the creation.

    """

    name: str
    kubeconfig_path: str
    labels: list = []
    kind: str = "Cluster"

    def creation_command(self):
        """Generate a command for creating a cluster.

        Returns:
            str: the command to create a cluster.

        """
        label_flags = " ".join(f"-l {label}" for label in self.labels)
        return f"rok kube cluster create {label_flags} {self.kubeconfig_path}"

    def delete_command(self):
        """Generate a command for deleting a cluster.

        Returns:
            str: the command to delete a cluster.

        """
        return f"rok kube cluster delete {self.name}"

    def check_deleted(self):
        """Run the command for checking if the Cluster has been deleted.
        """
        error_message = f"Unable to observe the cluster {self.name} deleted"
        run(
            f"rok kube cluster get {self.name}",
            condition=check_resource_deleted(error_message),
        )


class Environment(object):
    """Context manager to use for starting tests on a specific test environment. This
    environment will create the requested resources in the requested order when started.
    Actions can then be performed on the environment. Finally, all resources created are
    deleted in the reverse order of their creation.

    The structure of the environment is given using the ``resources`` parameter. This
    parameter should be a dict with the following syntax:

    {
        <priority 0>: [<resource A>, <resource_B>...],
        <priority 1>: [<resource C>, <resource_D>...],
    }

    priority:
        Priorities are integer. All resources with the highest priority (higher number)
        will be created first.

    resource lists:
        The resource lists are composed of instances of resource definitions (e.g
        :class:`ClusterDefinition`). All resources with the same priority will be
        created "at the same time", i.e. not concurrently, but between the ones with
        higher and the ones with lower priority.

        Note that the resources in these list do not need to have the same kind.

    To ensure that a resource is actually created or deleted, methods can be added to
    the resources definition, respectively ``check_created`` and ``check_deleted``.
    These methods are not meant to test the behavior of Krake, but simply to block the
    environment. When entering the context created by the :class:`Environment`, these
    checks ensure that the actual resources are created before handing over to the
    actual test in the test environment.

    The ``check_created`` and ``check_deleted`` do not take any parameter and do not
    return anything. However, if the resource is not respectively created or deleted
    after a certain time, they should raise an exception.

    Example:
        .. code:: python

            {
                10: [ClusterDefinition(...), ClusterDefinition(...)],
                0: [
                        ApplicationDefinition(...),
                        ApplicationDefinition(...),
                        ApplicationDefinition(...),
                    ],
            }

    Args:
        resources (dict): a dictionary that describes the resources to create, with
            their priority.

    """

    def __init__(self, resources):
        # Dictionary: "priority: list of resources to create"
        self.res_to_create = resources
        self.resources = defaultdict(list)

    def __enter__(self):
        """Create all given resources and check that they have been actually created.

        Returns:
            dict: all resources that have been created in the environment, with their
                kind as string as key.
        """
        # Create resources with highest priority first
        for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
            for resource in resource_list:
                self.resources[resource.kind] += [resource]
                # FIXME because rok returns an error code of "1" even if the resource
                #  was created, there are no check done here. It should be added as soon
                #  as rok has been refactored.
                run(resource.creation_command())

        # Check for each resource if it has been created
        for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
            for resource in resource_list:
                if hasattr(resource, "check_created"):
                    resource.check_created()

        return self.resources

    def __exit__(self, *exceptions):
        """Delete all given resources and check that they have been actually deleted.
        """
        # Delete resources with lowest priority first
        for _, resource_list in sorted(self.res_to_create.items()):
            for resource in resource_list:
                # FIXME because rok returns an error code of "1" even if the resource
                #  was deleted, there are no check done here. It should be added as soon
                #  as rok has been refactored.
                run(resource.delete_command())

        # Check for each resource if it has been deleted
        for _, resource_list in sorted(self.res_to_create.items()):
            for resource in resource_list:
                if hasattr(resource, "check_deleted"):
                    resource.check_deleted()


def create_simple_environment(cluster_name, kubeconfig_path, app_name, manifest_path):
    """Create the resource definitions for a test environment with one Cluster and one
    Application. The Cluster should be created first, and is thus given a higher
    priority.

    Args:
        cluster_name (PathLike): name of the kubernetes cluster that will be created
        kubeconfig_path (PathLike): path to the kubeconfig file for the cluster to
            create.
        app_name (PathLike): name of the Application to create.
        manifest_path (PathLike): path to the manifest file that should be used to
            create the Application.

    Returns:
        dict: an environment definition to use to create a test environment.

    """
    return {
        10: [ClusterDefinition(name=cluster_name, kubeconfig_path=kubeconfig_path)],
        0: [ApplicationDefinition(name=app_name, manifest_path=manifest_path)],
    }


def create_multiple_cluster_environment(
    kubeconfig_paths,
    cluster_labels=None,
    app_name=None,
    manifest_path=None,
    app_cluster_constraints=None,
    app_migration=None,
):
    """Create the resource definitions for a test environment with
    one Application and multiple Clusters.

    Args:
        kubeconfig_paths (dict of PathLike: PathLike): mapping between Cluster
            names and path to the kubeconfig file for the corresponding Cluster
            to create.
        cluster_labels (dict of PathLike: List(str)): optional mapping between
            Cluster names and labels for the corresponding Cluster to create.
        app_name (PathLike): optional name of the Application to create.
        manifest_path (PathLike): optional path to the manifest file that
            should be used to create the Application.
        app_cluster_constraints (List(str)): optional list of cluster constraints
            for the Application to create.
        app_migration (bool): optional migration flag indicating whether the
            application should be able to migrate.

    Returns:
        dict: an environment definition to use to create a test environment.

    """
    if not cluster_labels:
        cluster_labels = {cn: [] for cn in kubeconfig_paths}
    env = {
        10: [
            ClusterDefinition(name=cn, kubeconfig_path=kcp, labels=cluster_labels[cn])
            for cn, kcp in kubeconfig_paths.items()
        ]
    }
    if app_name:
        env[0] = [
            ApplicationDefinition(
                name=app_name,
                manifest_path=manifest_path,
                constraints=app_cluster_constraints,
                migration=app_migration,
            )
        ]
    return env
