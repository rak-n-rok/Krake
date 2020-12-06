from abc import ABC, abstractmethod
from enum import Enum
import itertools
import json
import logging
import os
import subprocess
import time
from collections import defaultdict

from dataclasses import MISSING

logger = logging.getLogger("krake.test_utils.run")

KRAKE_HOMEDIR = "/home/krake"
ROK_INSTALL_DIR = f"{KRAKE_HOMEDIR}/.local/bin"
STICKINESS_WEIGHT = 0.1

_ETCD_STATIC_PROVIDER_KEY = "/core/metricsprovider/static_provider"
_ETCDCTL_ENV = {"ETCDCTL_API": "3"}

GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}"
DEFAULT_MANIFEST = "echo-demo.yaml"
DEFAULT_KUBE_APP_NAME = "echo-demo"


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
        env_vars (dict[str: str], optional): key-value pairs of additional environment
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


def check_app_created_and_up(error_message=""):
    if not error_message:
        error_message = "App was not up and running."

    err_msg_fmt = error_message + " Error: {details}"

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
        details = (
            f" Expected return code: {expected_code}."
            f" Observed return code: {response.returncode}."
        )
        assert response.returncode == expected_code, error_message + details

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


def check_resource_exists(error_message=""):
    """Create a callable to verify that a resource exists.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the chosen resource does not exist.

    Args:
        error_message (str, optional): the message that will be displayed on failure.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    """

    def validate(response):
        assert response.returncode == 0
        assert "Error 404" not in response.output, error_message
        assert "not found" not in response.output, error_message

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


def check_http_code_in_output(http_code, error_message=None):
    """Create a callable to ensure that the given HTTP error code is present in the
    output of the response.

    Args:
        http_code (int): the HTTP error code to check.
        error_message (str, optional): the message that will be displayed if the check
            fails.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    """

    def validate(response):
        message = error_message
        if message is None:
            message = (
                f"The response got an HTTP code different"
                f"from {http_code}: {response.output}"
            )
        assert str(http_code) in response.output, message

    return validate


class ResourceKind(Enum):
    APPLICATION = "application"
    CLUSTER = "cluster"


class ResourceDefinition(ABC):
    """Definition of a resource for the test environment :class:`Environment`.

    Describes how to create, update and delete a resource with the rok utility.
    Also defines checks to perform to test whether these actions were successful.

    Args:
        name (str): name of the resource
        kind (ResourceKind): resource kind

    """

    def __init__(self, name, kind):
        assert name
        self.name = name
        self.kind = kind

    def create_resource(self):
        """Create the resource.
        """
        error_message = f"The {self.kind} resource {self.name} could not be created."
        run(self.creation_command(), condition=check_return_code(error_message))

    @abstractmethod
    def creation_command(self):
        """Get the command for creating the resource.

        Returns:
            list[str]: the command to create the resource, as a list of its parts.
        """
        pass

    def check_created(self, delay=10):
        """Run the command for checking if the resource has been created.

        Args:
            delay (int, optional): The number of seconds that should be allowed
                before giving up.
        """
        run(
            self.get_command(),
            condition=self.creation_acceptance_criteria(),
            interval=1,
            retry=delay,
        )

    @abstractmethod
    def creation_acceptance_criteria(self, error_message=None):
        """Verify that the resource has been properly created.

        Args:
            error_message (str, optional): error message to display in case of failure

        Raises:
            AssertionError: if the resource failed to be created properly
        """
        pass

    def delete_resource(self):
        """Delete the resource."""
        # The 404 HTTP code is allowed for the cases where the resource has been deleted
        # during the test.
        run(self.delete_command(), condition=allow_404)

    @abstractmethod
    def delete_command(self):
        """Get the command for deleting the resource.

        Returns:
            list[str]: the command to delete the resource, as a list of its parts.
        """
        pass

    def check_deleted(self, delay=10):
        """Run the command for checking if the resource has been deleted.

        Args:
            delay (int, optional): The number of seconds that should be allowed
                before giving up.
        """
        run(
            self.get_command(),
            condition=self.deletion_acceptance_criteria(),
            interval=1,
            retry=delay,
        )

    def deletion_acceptance_criteria(self, error_message=None):
        """Verify that the resource has been properly deleted.

        Args:
            error_message (str, optional): error message to display in case of failure

        Raises:
            AssertionError: if the resource failed to be deleted properly
        """
        if not error_message:
            error_message = (
                f"Unable to observe the {self.kind} resource {self.name} being deleted"
            )
        return check_resource_deleted(error_message=error_message)

    def get_resource(self):
        """Get the resource by executing the rok cli command.

        Returns:
            dict: the application as a dict built from the output of the
                executed command returned by self.get_command().
        """

        response = run(self.get_command())
        return response.json

    @abstractmethod
    def get_command(self):
        """Generate a command for getting the application.

        Returns:
            list[str]: the command to get the application, as a list of its parts.
        """
        pass

    def update_resource(self, **kwargs):
        """Update the resource with the provided information.

        Args:
            **kwargs: keyword arguments matching the arguments of update_command().
        """
        run(self.update_command(**kwargs))

    @abstractmethod
    def update_command(self, **kwargs):
        """Get a command for updating the application.

        Args:
            **kwargs: the arguments necessary to update the resource.

        Returns:
            list[str]: the command to update the resource, as a list of its parts.
        """
        pass

    @staticmethod
    def _get_label_options(labels):
        """
        Convenience method for generating label lists for rok cli commands.

        Example:
            If provided the argument labels={"label1": "value1", "label2": "value2"},
            this method will return the list
            ["-l", "label1=value1", "-l", "label2=value2"],
            which can be used when constructing a cli command like
            "rok kube app create -l label1=value1 -l label2=value2 ..."

        Args:
            labels (dict[str: str]): dict of resource labels and their values

        Returns:
            list[str]:
                ['-l', key_1=value_1, '-l', key_2=value_2, ..., '-l', key_n=value_n]
                for all n key, value pairs in labels.
        """
        labels = [k + "=" + v for k, v in labels.items()] if labels else []
        return ResourceDefinition._get_flag_str_options("-l", labels)

    @staticmethod
    def _get_flag_str_options(flag, values):
        """
        Convenience method for generating option lists for cli commands.

        Example:
            If provided the arguments flag="-L" and
            values=["location is not DE", "foo=bar"], this method will return
            the list ["-L", "location is not DE", "-L", "foo=bar"],
            which can be used when constructing a cli command like
            "rok kube app create -L location is not DE -L foo=bar ..."

        Args:
            flag (str): The cli argument flag. The same flag is used for all values.
            values (list[str]): The values of the cli arguments

        Returns:
            list[str]: [flag, val1, flag, val_2, ..., flag, val_n]
                for all n values in values.
        """
        if not values:
            return []
        return list(itertools.chain(*[[flag, val] for val in values]))


class ApplicationDefinition(ResourceDefinition):
    """Definition of an Application resource for the test environment
    :class:`Environment`.

    Args:
        name (str): name of the application
        manifest_path (str): path to the manifest file to use for the creation.
        constraints (list[str]): optional list of cluster label constraints
            to use for the creation of the application.
        labels (dict[str: str]): dict of application labels and their values
        migration (bool): optional migration flag indicating whether the
            application should be able to migrate.
    """

    def __init__(
        self, name, manifest_path, constraints=None, labels=None, migration=None
    ):
        super().__init__(name=name, kind=ResourceKind.APPLICATION)
        assert os.path.isfile(manifest_path)
        self.manifest_path = manifest_path
        self.constraints = constraints or []
        self.labels = labels or {}
        self.migration = migration

    def creation_command(self):
        cmd = f"rok kube app create -f {self.manifest_path} {self.name}".split()
        cmd += self._get_cluster_label_constraint_options(self.constraints)
        cmd += self._get_label_options(self.labels)
        if self.migration is not None:
            cmd += [self._get_migration_flag(self.migration)]
        return cmd

    @staticmethod
    def _get_migration_flag(migration):
        """
        Determines the migration cli option for a 'rok kube app create'
        or 'rok kube app update' command, based on the value of the flag 'migration'.

        Depending on the value of 'migration', the cli option is determined as such:
            True: "--enable-migration"
            False: "--disable-migration"
            None: ""

        Args:
            migration (bool, optional): Flag indicating the desired migration cli option

        Returns:
            str: The migration cli option.

        """
        if migration is False:
            migration_flag = "--disable-migration"
        elif migration is True:
            migration_flag = "--enable-migration"
        elif migration is None:
            migration_flag = ""
        else:
            raise RuntimeError("migration must be None, False or True.")
        return migration_flag

    def creation_acceptance_criteria(self, error_message=None):
        return check_app_created_and_up(error_message=error_message)

    def delete_command(self):
        return f"rok kube app delete {self.name}".split()

    def update_command(self, cluster_labels=None, migration=None, labels=None):
        """Get a command for updating the application.

        Args:
            cluster_labels (list[str]): optional list of cluster label constraints
                to give the application, e.g. ['location=DE']
            migration (bool, optional): Flag indicating which migration flag should
                be given to the update command.
                    True: --enable-migration
                    False: --disable-migration
                    None: (No flag)
            labels (dict[str: str]): dict of labels with which to update the app.

        Returns:
            list[str]: the command to update the application, as a list of its parts.
        """
        cmd = f"rok kube app update {self.name}".split()
        cmd += self._get_cluster_label_constraint_options(cluster_labels)
        cmd += self._get_label_options(labels)
        if migration is not None:
            cmd += [self._get_migration_flag(migration)]
        return cmd

    def _get_cluster_label_constraint_options(self, cluster_label_constraints):
        """
        Convenience method for generating cluster label constraints lists for
        rok cli commands.

        Example:
            If provided the argument labels=["constraint1", "constraint2"},
            this method will return the list ["-L", "constraint1", "-L", "constraint2"],
            which can be used when constructing a cli command like
            "rok kube app create -L constraint1 -L constraint2 ..."

        Args:
            cluster_label_constraints (list[str]): list of cluster label constraints
                to give the application, e.g. ['location is DE']

        Returns:
            list[str]: ['-L', constr_1, '-L', constr_2, ..., '-L', constr_n]
                for all n constraints in cluster_label_constraints.

        """
        return self._get_flag_str_options("-L", cluster_label_constraints)

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

    def get_command(self):
        return f"rok kube app get {self.name} -o json".split()

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
        app_dict = self.get_resource()
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
        app_dict = self.get_resource()
        return app_dict["status"]["scheduled_to"]["name"]

    def get_state(self):
        """Run the command for getting the application and return its state.

        Returns:
            str: the current state of the application
        """
        app_dict = self.get_resource()
        return app_dict["status"]["state"]


class ClusterDefinition(ResourceDefinition):
    """Definition of a cluster resource for the test environment :class:`Environment`.

    Args:
        name (str): name of the cluster
        kubeconfig_path (str): path to the kubeconfig file to use for the creation.
        labels (dict[str: str], optional): dict of cluster labels and their values
            to use for the creation.
        metrics (dict[str: float], optional): dict of metrics and their weights
            to use for the creation.
    """

    def __init__(self, name, kubeconfig_path, labels=None, metrics=None):
        super().__init__(name=name, kind=ResourceKind.CLUSTER)
        assert os.path.isfile(kubeconfig_path)
        self.kubeconfig_path = kubeconfig_path
        self.labels = labels or {}
        self.metrics = metrics or {}

    def creation_command(self):
        cmd = "rok kube cluster create".split()
        cmd += self._get_label_options(self.labels)
        cmd += self._get_metrics_options(self.metrics)
        cmd += [self.kubeconfig_path]
        return cmd

    @staticmethod
    def _get_metrics_options(metrics):
        """Convenience method for generating metric lists for rok cli commands.

        Example:
            If provided the argument
            metrics={"metric_name1": 1.0, "metric_name2": 2.0},
            this method will return the list
            ["-m", "metric_name1", "1.0", "-m", "metric_name2", "2.0"],
            which can be used when constructing a cli command like
            rok kube cluster create -m metric_name1 1.0 -m metric_name2 2.0 ...

        Args:
            metrics (dict[str: float]): dict of metrics names and their weights

        Returns:
            list[str]:
                ['-m', 'key_1', 'value_1', '-m', 'key_2', 'value_2', ...,
                '-m', 'key_n', 'value_n']
                for all n key, value pairs in metrics.
        """
        metrics_options = []
        for metric, weight in metrics.items():
            metrics_options += ["-m", metric, str(weight)]
        return metrics_options

    def creation_acceptance_criteria(self, error_message=None):
        if not error_message:
            error_message = f"The cluster {self.name} was not properly created."
        return check_resource_exists(error_message=error_message)

    def delete_command(self):
        return f"rok kube cluster delete {self.name}".split()

    def update_command(self, labels=None, metrics=None):
        """Get a command for updating the cluster.

        Args:
            labels (dict[str: str], optional): dict of labels and their values to
                give the cluster, e.g. {'location': 'DE'}
            metrics (dict[str: float]): optional dict with metrics and their weights
                to give the cluster.

        Returns:
             list[str]: the command to update the application, as a list of its parts.

        """
        if not (labels or metrics):
            msg = (
                "Either labels or metrics must be present in a "
                "cluster update command."
            )
            raise AssertionError(msg)

        cmd = f"rok kube cluster update {self.name}".split()
        cmd += self._get_label_options(labels)
        cmd += self._get_metrics_options(metrics)
        return cmd

    def get_command(self):
        return f"rok kube cluster get {self.name} -o json".split()


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
        creation_delay (int, optional): The number of seconds that should
            be allowed before concluding that a resource could not be created.

    """

    def __init__(
        self, resources, before_handlers=None, after_handlers=None, creation_delay=10
    ):
        # Dictionary: "priority: list of resources to create"
        self.res_to_create = resources
        self.resources = defaultdict(list)
        self.creation_delay = creation_delay

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
                resource.check_created(delay=self.creation_delay)

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
    def get_resource_definition(cls, resources, kind, name):
        """
        If there exists exactly one resource in 'resources' of kind 'kind'
        with name 'name', return it. Otherwise raise AssertionError.
        Args:
            resources (list[ResourceDefinition]): list of ResourceDefinition's
                to look through
            kind (ResourceKind): the kind of resource which is sought.
            name (str): the name of the resource that is sought.

        Returns:
            ResourceDefinition: If found, the sought resource.
                if kind == ResourceKind.CLUSTER: ClusterDefinition
                If kind == ResourceKind.APPLICATION: ApplicationDefinition

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
                msg += f" They were: {', '.join(str(rd) for rd in found)}"
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
        cluster_labels (dict[str: dict[str: str]], optional): mapping between
            Cluster names and labels for the corresponding Cluster to create.
            The labels are given as a dictionary with the label names as keys
            and the label values as values.
        metrics (dict[str: dict[str: float]], optional): mapping between
            Cluster names and metrics for the corresponding Cluster to create.
            The metrics are given as a dictionary with the metric names as keys
            and the values of the metrics as values.
        app_name (str, optional): name of the Application to create.
        manifest_path (PathLike, optional): path to the manifest file that
            should be used to create the Application.
        app_cluster_constraints (List[str], optional): list of cluster constraints
            for the Application to create.
        app_migration (bool, optional): migration flag indicating whether the
            application should be able to migrate.

    Returns:
        dict[int: List[ResourceDefinition]]: an environment definition to use to create
            a test environment.

    """
    if not cluster_labels:
        cluster_labels = {cn: {} for cn in kubeconfig_paths}
    if not metrics:
        metrics = {cn: {} for cn in kubeconfig_paths}
    if not app_cluster_constraints:
        app_cluster_constraints = []

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


def create_default_environment(
    cluster_names,
    metrics=None,
    cluster_labels=None,
    app_cluster_constraints=None,
    app_migration=None,
):
    """Create and return a test environment definition with one application and
    len(cluster_names) clusters using default kubeconfig and manifest files.

    This method is a convenience method wrapping
    `create_multiple_cluster_environment()`.

    The kubeconfig file that will be used for `cluster_name` in `cluster_names`
    is given by get_default_kubeconfig_path(). This file is assumed to exist.

    The manifest file that will be used for the application is
    `MANIFEST_PATH/DEFAULT_MANIFEST`. This file is assumed to exist.

    Args:
        cluster_names (list[str]): cluster names
        metrics (dict[str: dict[str: float]], optional):
            Cluster names and their metrics.
            keys: the same names as in `cluster_names`
            values: dict of metrics
                keys: metric names
                values: weight of the metrics
        cluster_labels (dict[str: dict[str: str]], optional):
            Cluster names and their cluster labels.
            keys: the same names as in `cluster_names`
            values: dict of cluster labels
                keys: cluster labels
                values: value of the cluster labels
        app_cluster_constraints (list[str], optional):
            list of cluster constraints, e.g. ["location != DE"]
        app_migration (bool, optional): migration flag indicating whether the
            application should be able to migrate. If not provided, none is
            provided when creating the application.

    Returns:
        dict: an environment definition to use to create a test environment.

    """
    kubeconfig_paths = {c: get_default_kubeconfig_path(c) for c in cluster_names}
    manifest_path = os.path.join(MANIFEST_PATH, DEFAULT_MANIFEST)
    return create_multiple_cluster_environment(
        kubeconfig_paths=kubeconfig_paths,
        metrics=metrics,
        cluster_labels=cluster_labels,
        app_name=DEFAULT_KUBE_APP_NAME,
        manifest_path=manifest_path,
        app_cluster_constraints=app_cluster_constraints,
        app_migration=app_migration,
    )


def get_default_kubeconfig_path(cluster_name):
    """Return the default kubeconfig_path for the given cluster.

    Args:
        cluster_name (str): The name of a cluster

    Returns:
        str: The default path for the clusters kubeconfig file.

    """
    return os.path.join(CLUSTERS_CONFIGS, cluster_name)


def create_cluster_info(cluster_names, sub_keys, values):
    """
    Convenience method for preparing the input parameters cluster_labels and metrics
    of `create_default_environment()`.

    The sub-keys can for example be thought of as
    metric names (and `values` their weights) or
    cluster label names (and `values` their values).

    Example:
        Sample input:
            cluster_names = ["cluster1", "cluster2", "cluster3"]
            sub_keys = ["m1", "m2"]
            values = [3, 4]
        Return value:
            {
                "cluster1": {
                    "m1": 3,
                },
                "cluster2": {
                    "m2": 4,
                },
                "cluster3": {},
            }

    If sub_keys is not a list, the list will be constructed as follows:
        sub_keys = [sub_keys] * len(values)
    This is useful when the sub-key should be the same for all clusters.

    The ith cluster will get the ith sub-key with the ith value.
    Caveat: If there are fewer sub-keys and values than clusters,
    the last cluster(s) will not become any <sub-key, value> pairs at all.

    Limitation:
        Each cluster can only have one <sub-key, value> pair using this method.

    Args:
        cluster_names (list[str]): The keys in the return dict.
        sub_keys: The keys in the second level dicts in the return dict.
            If type(sub_keys) isn't list, a list will be created as such:
                sub_keys = [sub_keys] * len(values)
        values (list): The values in the second level dicts in the return dict.

    Returns:
        dict[str: dict] with same length as cluster_names.
            The first `len(values)` <key, value> pairs will be:
                cluster_names[i]: {sub_keys[i]: values[i]}
            The last `len(cluster_names) - len(values)` <key: value> pairs will be:
                top_level_keys[i]: {}

    Asserts:
        len(cluster_names) >= len(values)
        len(sub_keys) == len(values) if type(sub_keys) is list

    """
    if not type(sub_keys) is list:
        sub_keys = [sub_keys] * len(values)

    assert len(cluster_names) >= len(values)
    assert len(sub_keys) == len(values)

    cluster_dicts = [{sub_keys[i]: values[i]} for i in range(len(values))]
    cluster_dicts += [{}] * (len(cluster_names) - len(values))

    return dict(zip(cluster_names, cluster_dicts))
