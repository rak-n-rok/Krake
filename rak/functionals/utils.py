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
STICKINESS_WEIGHT = 0.1

_ETCD_STATIC_PROVIDER_KEY = "/core/metricsprovider/static_provider"
_ETCDCTL_ENV = {"ETCDCTL_API": "3"}


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


def run(command, retry=10, interval=1, condition=None, input=None, env_vars=None):
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
        env_vars (dict, optional): key-value pairs of additional environment
            variables that need to be set. ROK_INSTALL_DIR will always be added
            to the PATH.

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
    if env_vars:
        env.update(env_vars)
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


def check_app_created_and_up():
    err_msg_fmt = "App was not up and running. Error: {details}"

    def validate(response):
        try:
            app_details = response.json
            expected_state = "RUNNING"
            observed_state = app_details["status"]["state"]
            observed_running_on = app_details["status"]["running_on"]
            observed_scheduled_to = app_details["status"]["scheduled_to"]

            details = (
                f"Unable to observe application in a {expected_state} state. "
                f"Observed: {observed_state}."
            )
            assert observed_state == expected_state, err_msg_fmt.format(details=details)

            details = (
                f"App was in {expected_state} state but its running_on "
                f"was {observed_running_on}."
            )
            assert observed_running_on, err_msg_fmt % {"details": details}

            details = (
                f"App was in {expected_state} state but its scheduled_to "
                f"was {observed_scheduled_to}."
            )
            assert observed_scheduled_to, err_msg_fmt % {"details": details}

        except (KeyError, json.JSONDecodeError) as e:
            raise AssertionError(err_msg_fmt % {"details": str(e)})

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
            observed_cluster = app_details["status"]["running_on"].get("name", None)
            scheduled_to = app_details["status"]["scheduled_to"].get("name", None)
            msg = (
                error_message + f" App state: {app_details['status']['state']}, "
                f"App scheduled_to: {scheduled_to}, "
                f"Observed cluster: {observed_cluster}"
            )
            assert observed_cluster == expected_cluster, msg
        except (KeyError, json.JSONDecodeError):
            raise AssertionError(error_message)

    return validate


def allow_404(response):
    """Check that the response given succeeded, or if it did not succeed, that the
    output shows a "404" HTTP error.

    Args:
        response (Response): the response to check

    Raises:
        AssertionError: if the response failed, but not from a "404" error.

    """
    error_message = (
        f"The response got an error code different from 404: {response.output}"
    )
    if response.returncode != 0:
        assert "404" in response.output, error_message


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

    def create_resource(self):
        """Create the application.
        """
        error_message = f"The Application {self.name} could not be created."
        run(self.creation_command(), condition=check_return_code(error_message))

    def creation_command(self):
        """Generate a command for creating the Application.

        Returns:
            str: the command to create the Application.

        """
        migration_flag = self._get_migration_flag(self.migration)
        constraints = (
            " ".join(f"-L {constraint}" for constraint in self.constraints)
            if self.constraints
            else ""
        )
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
        """Run the command for checking if the Application has been created."""
        run(
            self.get_command(), condition=check_app_created_and_up(),
        )

    def delete_resource(self):
        """Delete the actual Application."""
        # The 404 HTTP code is allowed for the cases where the resource has been deleted
        # during the test.
        run(self.delete_command(), condition=allow_404)

    def delete_command(self):
        """Generate a command for deleting the application.

        Returns:
            str: the command to delete the application.

        """
        return f"rok kube app delete {self.name}"

    def check_deleted(self):
        """Run the command for checking if the Application has been deleted."""
        error_message = f"Unable to observe the application {self.name} deleted"
        run(
            self.get_command(), condition=check_resource_deleted(error_message),
        )

    def update(self, cluster_labels=None, migration=None, labels=None):
        """Update the application with the provided information.

        Args:
            cluster_labels (list(str)): optional list of cluster label constraints
                to give the application, e.g. ['location=DE']
            migration (bool): Optional flag indicating which migration flag should
                be given to the update command.
                    True: --enable-migration
                    False: --disable-migration
                    None: (No flag)
            labels (dict[str: str]): dict of labels with which to update the app.

        """
        run(
            self.update_command(
                cluster_labels=cluster_labels, migration=migration, labels=labels
            )
        )

    def update_command(self, cluster_labels=None, migration=None, labels=None):
        """Generate a command for updating the application.

        Args:
            cluster_labels (list(str)): optional list of cluster label constraints
                to give the application, e.g. ['location=DE']
            migration (bool): Optional flag indicating which migration flag should
                be given to the update command.
                    True: --enable-migration
                    False: --disable-migration
                    None: (No flag)
            labels (dict[str: str]): dict of labels with which to update the app.

        Returns:
            str: the command to update the Application.

        """
        migration_flag = self._get_migration_flag(migration)
        clc_options = (
            " ".join(f"-L {constraint}" for constraint in cluster_labels)
            if cluster_labels
            else ""
        )
        label_options = (
            " ".join(f"-l {label}={value}" for label, value in labels.items())
            if labels
            else ""
        )
        return (
            f"rok kube app update "
            f"{clc_options} {migration_flag} {label_options} {self.name}"
        )

    def check_running_on(
        self, cluster_name, within=10, after_delay=0, error_message=""
    ):
        """Run the command for checking that the application is running on the
        specified cluster.

        The first check occurs after `after_delay` seconds, and rechecks for
        `within` seconds every
        second until the application was observed to run on the cluster
        `cluster_name`.

        An AssertionError is raised if the application is not running on cluster
        `cluster_name` within `within` seconds of the first check.

        Args:
            cluster_name (str): Name of the cluster on which the application is
                expected to run.
            within (int): number of seconds it is allowed to take until the app
                is running on the cluster `cluster_name`.
            after_delay (int): number of seconds to delay before checking.
            error_message (str): displayed error message in case of error.
        """
        if not error_message:
            error_message = (
                f"Unable to observe that the application {self.name} "
                f"is running on cluster {cluster_name}."
            )
        if after_delay:
            time.sleep(after_delay)
        run(
            self.get_command(),
            retry=within,
            interval=1,
            condition=check_app_running_on(cluster_name, error_message),
        )

    def get(self):
        """Get the application by executing the 'rok kube app get' command.

        Returns:
            dict: the application as a dict built from the output of the
                executed command.
        """

        response = run(self.get_command())
        return response.json

    def get_command(self):
        """Generate a command for getting the application.

        Returns:
            str: the command to get the application
        """
        return f"rok kube app get {self.name} -o json"

    def get_running_on(self, strict=False):
        """Run the command for getting the application and return the name of
        the cluster it is running on.

        Args:
            strict (bool): Flag signaling whether to be strict and only return
            running_on if it is equal to scheduled_to.

        Returns:
            str: the name of the cluster the application is running on or None
            if scheduled_to != running_on
        """
        app_dict = self.get()
        running_on = app_dict["status"]["running_on"]["name"]
        if strict:
            scheduled_to = app_dict["status"]["scheduled_to"]["name"]
            if scheduled_to != running_on:
                # We cannot be sure where it is running right now...
                return None
        return running_on

    def get_scheduled_to(self):
        """Run the command for getting the application and return the name of
        the cluster it is scheduled to.

        Returns:
            str: the name of the cluster the application is scheduled to
        """
        app_dict = self.get()
        return app_dict["status"]["scheduled_to"]["name"]

    def get_state(self):
        """Run the command for getting the application and return its state.

        Returns:
            str: the current state of the application
        """
        app_dict = self.get()
        return app_dict["status"]["state"]


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
    metrics: dict = {}

    def create_resource(self):
        """Create the Cluster."""

        error_message = f"The Cluster {self.name}"
        run(self.creation_command(), condition=check_return_code(error_message))

    def creation_command(self):
        """Generate a command for creating the cluster.

        Returns:
            str: the command to create the cluster.

        """
        label_flags = " ".join(f"-l {label}" for label in self.labels)
        metric_flags = " ".join(
            f"-m {metric} {weight}" for metric, weight in self.metrics.items()
        )
        return (
            f"rok kube cluster create {label_flags} {metric_flags} "
            f"{self.kubeconfig_path}"
        )

    def delete_resource(self):
        """Delete the actual Cluster."""
        # The 404 HTTP code is allowed for the cases where the resource has been deleted
        # during the test.
        run(self.delete_command(), condition=allow_404)

    def delete_command(self):
        """Generate a command for deleting the cluster.

        Returns:
            str: the command to delete the cluster."""
        return f"rok kube cluster delete {self.name}"

    def check_deleted(self):
        """Run the command for checking if the Cluster has been deleted."""
        error_message = f"Unable to observe the cluster {self.name} deleted"
        run(
            f"rok kube cluster get {self.name}",
            condition=check_resource_deleted(error_message),
        )

    def update(self, labels=None, metrics=None):
        """Update the cluster with the provided information.

        Args:
            labels (list(str)): optional list of labels
                to give the cluster, e.g. ['location=DE']
            metrics (dict[str: float]): optional dict with metrics and their weights
                to give the cluster

        """
        run(self.update_command(labels=labels, metrics=metrics))

    def update_command(self, labels=None, metrics=None):
        """Generate a command for updating the cluster.

        Args:
            labels (list(str)): optional list of labels
                to give the cluster, e.g. ['location=DE']
            metrics (dict[str: float]): optional dict with metrics and their weights
                to give the cluster.

        Returns:
            str: the command to update the cluster.

        """
        if not (labels or metrics):
            msg = (
                "Either labels or metrics must be present in a "
                "cluster update command."
            )
            raise AssertionError(msg)

        metric_opts = (
            " ".join(f"-m {metric} {weight}" for metric, weight in metrics.items())
            if metrics
            else ""
        )
        label_opts = " ".join(f"-l {label}" for label in labels) if labels else ""
        return f"rok kube cluster update {label_opts} {metric_opts} {self.name}"


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
        before_handlers (list): this list of functions will be called one after the
            other in the given order before all Krake resources have been created. Their
            signature should be "handler(dict) -> void". The given dict contains the
            definition of all resources managed by the Environment.
        after_handlers (list): this list of functions will be called one after the other
            in the given order after all Krake resources have been deleted. Their
            signature should be "handler(dict) -> void". The given dict contains the
            definition of all resources managed by the Environment.

    """

    def __init__(self, resources, before_handlers=None, after_handlers=None):
        # Dictionary: "priority: list of resources to create"
        self.res_to_create = resources
        self.resources = defaultdict(list)

        self.before_handlers = before_handlers if before_handlers else []
        self.after_handlers = after_handlers if after_handlers else []

    def __enter__(self):
        """Create all given resources and check that they have been actually created.

        Returns:
            dict: all resources that have been created in the environment, with their
                kind as string as key.
        """
        for handler in self.before_handlers:
            handler(self.resources)

        # Create resources with highest priority first
        for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
            for resource in resource_list:
                self.resources[resource.kind] += [resource]
                resource.create_resource()

        # Check for each resource if it has been created
        for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
            for resource in resource_list:
                if hasattr(resource, "check_created"):
                    resource.check_created()

        return self.resources

    def __exit__(self, *exceptions):
        """Delete all given resources and check that they have been actually deleted."""
        # Delete resources with lowest priority first
        for _, resource_list in sorted(self.res_to_create.items()):
            for resource in resource_list:
                resource.delete_resource()

        # Check for each resource if it has been deleted
        for _, resource_list in sorted(self.res_to_create.items()):
            for resource in resource_list:
                if hasattr(resource, "check_deleted"):
                    resource.check_deleted()

        for handler in self.after_handlers:
            handler(self.resources)

    @classmethod
    def get_resource(cls, resources, kind, name):
        """
        If there exists exactly one resource in 'resources' of kind 'kind'
        with name 'name', return it. Otherwise raise AssertionError.
        Args:
            resources (list): list of ClusterDefinition and ApplicationDefinition
                objects.
            kind (str): 'Cluster' or 'Application' depending on which kind of resource
                is sought.
            name (str): the name of the resource that is sought.

        Returns:
            If found, the sought resource
            (either of type ClusterDefinition or ApplicationDefinition).
        Raises:
            AssertionError if not exactly one resource was found.

        """
        found = [r for r in resources if r.kind == kind and r.name == name]
        if len(found) != 1:
            msg = (
                f"Found {len(found)} resources of kind {kind} with name {name} "
                f"(expected one)."
            )
            if len(found) != 0:
                msg += f" They were: {', '.join(found)}"
            raise AssertionError(msg)
        return found[0]


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
    metrics=None,
    app_name=None,
    manifest_path=None,
    app_cluster_constraints=None,
    app_migration=None,
):
    """Create the resource definitions for a test environment with
    one Application and multiple Clusters.

    Args:
        kubeconfig_paths (dict[str: PathLike]): mapping between Cluster
            names and path to the kubeconfig file for the corresponding Cluster
            to create.
        cluster_labels (dict[str: List[str]], optional): mapping between
            Cluster names and labels for the corresponding Cluster to create.
        metrics (dict[str: List[str]], optional): mapping between
            Cluster names and metrics for the corresponding Cluster to create.
        app_name (str, optional): name of the Application to create.
        manifest_path (PathLike, optional): path to the manifest file that
            should be used to create the Application.
        app_cluster_constraints (List[str], optional): list of cluster constraints
            for the Application to create.
        app_migration (bool, optional): migration flag indicating whether the
            application should be able to migrate.

    Returns:
        dict[int: List[NamedTuple]]: an environment definition to use to create
            a test environment.

    """
    if not cluster_labels:
        cluster_labels = {cn: [] for cn in kubeconfig_paths}
    if not metrics:
        metrics = {cn: {} for cn in kubeconfig_paths}

    env = {
        10: [
            ClusterDefinition(
                name=cn,
                kubeconfig_path=kcp,
                labels=cluster_labels[cn],
                metrics=metrics[cn],
            )
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


def get_scheduling_score(cluster, values, weights, scheduled_to=None):
    """Get the scheduling cluster score for the cluster (including stickiness).

    Args:
        cluster (str): cluster name
        values (dict[str: float]): Dictionary of the metric values. The dictionary keys
            are the names of the metrics and the dictionary values the metric values.
        weights (dict[str: dict[str: float]]): Dictionary of cluster weights.
            The keys are the names of the clusters and each value is a dictionary in
            itself, with the metric names as keys and the cluster's weights as values.
        scheduled_to (str): name of the cluster to which the application being
            scheduled has been scheduled.

    Returns:
        float: The score of the given cluster.

    """
    # Sanity check: Check that the metrics (i.e., the keys) are the same in both lists
    assert len(values) == len(weights[cluster])
    assert all(metric in weights[cluster] for metric in values)

    rank = sum(values[metric] * weights[cluster][metric] for metric in values)
    norm = sum(weights[cluster][metric] for metric in weights[cluster])
    if scheduled_to == cluster:
        stickiness_value = 1
        rank += STICKINESS_WEIGHT * stickiness_value
        norm += STICKINESS_WEIGHT
    return rank / norm


def _put_etcd_entry(data, key):
    """Put `data` as the value of the key `key` in the etcd store.

    Args:
        data (object): The data to put
        key (str): the key to update.

    """
    data_str = json.dumps(data)
    put_cmd = ["etcdctl", "put", key, "--", data_str]
    run(command=put_cmd, env_vars=_ETCDCTL_ENV)


def _get_etcd_entry(key, condition=None):
    """Retrieve the value of the key `key` from the etcd store.
    This method calls run to perform the actual command.

    Args:
        key (str): the key to retrieve from the db.
        condition (callable, optional): a callable. This will be passed to run()
            as its `condition` parameter.

    Returns:
        object: Value of the key `key` in the etcd database, parsed by json.
    """
    get_cmd = ["etcdctl", "get", key, "--print-value-only"]
    resp = run(command=get_cmd, condition=condition, env_vars=_ETCDCTL_ENV)
    try:
        return resp.json
    except Exception as e:
        msg = f"Failed to load response '{resp}'. Error: {e}"
        raise AssertionError(msg)


def get_static_metrics():
    """Retrieve metrics from the etcd database.

    Returns:
         dict[str: float]
            Dict with the metrics names as keys and metric values as values.

    """
    static_provider = _get_etcd_entry(_ETCD_STATIC_PROVIDER_KEY)
    return static_provider["spec"]["static"]["metrics"]


def set_static_metrics(values):
    """Modify the database entry for the static metrics provider by setting its
     values to the provided metrics.

    Args:
        values (dict[str: float]): Dictionary with the metrics names as keys and
            metric values as values.

    """
    static_provider = _get_etcd_entry(_ETCD_STATIC_PROVIDER_KEY)

    # sanity check that we are only modifying existing metrics
    old_metrics = static_provider["spec"]["static"]["metrics"]
    assert all([metric in old_metrics for metric in values])

    # set the new values
    static_provider["spec"]["static"]["metrics"].update(values)

    # update database with the updated static_provider
    _put_etcd_entry(static_provider, key=_ETCD_STATIC_PROVIDER_KEY)

    # make sure the changing of the values took place
    _get_etcd_entry(_ETCD_STATIC_PROVIDER_KEY, condition=check_static_metrics(values))


def check_static_metrics(expected_metrics, error_message=""):
    """Create a callable to verify that the static provider response contains
    the expected values.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the static metrics in the response are different
    from the given ones.

    Args:
        expected_metrics (dict[str: float]): Dictionary with the metrics names as
            keys and metric values as values.
        error_message (str): the message that will be displayed if the
            check fails.

    Returns:
        callable: a condition that will check its given response against
            the parameters of the current function.

    """
    if not error_message:
        error_message = (
            f"The static provider did not provide the expected "
            f"metrics. Expected metrics: {expected_metrics}"
        )

    def validate(response):
        try:
            observed_metrics = response.json["spec"]["static"]["metrics"]
            msg = error_message + f" Provided metrics: {observed_metrics}"
            for m, val in expected_metrics.items():
                assert val == observed_metrics.get(m), msg
        except Exception as e:
            raise AssertionError(error_message + f"Error: {e}")

    return validate
