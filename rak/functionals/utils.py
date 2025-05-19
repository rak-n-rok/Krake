import json
import logging
import os
import subprocess
import time
from dataclasses import MISSING

from deepdiff import DeepDiff

logger = logging.getLogger("krake.test_utils.run")

KRAKE_HOMEDIR = "/home/krake"
ROK_INSTALL_DIR = f"{KRAKE_HOMEDIR}/.local/bin"
STICKINESS_WEIGHT = 0.1
DEFAULT_NAMESPACE = "system:admin"


class Singleton(object):
    """Return a new instance of a class.

    Returns:
        object: class instance
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not isinstance(cls._instance, cls):
            cls._instance = object.__new__(cls, *args, **kwargs)
        return cls._instance


def kubectl_cmd(kubeconfig):
    """Build the kubectl command to communicate with the cluster that can be reached by
    the provided kubeconfig file.

    Args:
        kubeconfig (str): path to the kubeconfig file.

    Returns:
        str: the base kubectl command to use for communicating with the cluster.

    """
    return f"kubectl --kubeconfig {kubeconfig}"


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
        env_vars (dict[str, str], optional): key-value pairs of additional environment
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

    Raises:
        ValueError: if a KeyError or JSONDecodeError is caught
    """

    def validate(response):
        try:
            app_details = response.json
            assert app_details["status"]["state"] == state, error_message
            if reason:
                assert app_details["status"]["reason"]["code"] == reason, error_message
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(error_message) from e

    return validate


def check_cluster_created_and_up(error_message="", expected_state="ONLINE"):
    if not error_message:
        error_message = "Cluster was not up and running."

    err_msg_fmt = error_message + " Error: {details}"

    def validate(response):
        try:
            cluster_details = response.json
            observed_state = cluster_details["status"]["state"]

            details = (
                f"Unable to observe cluster in an {expected_state} state. "
                f"Observed: {observed_state}."
            )
            assert observed_state == expected_state, \
                err_msg_fmt.format(details=details) + "| " + json.dumps(cluster_details)

        except (KeyError, json.JSONDecodeError) as e:
            raise RuntimeError(err_msg_fmt % {"details": str(e)})

    return validate


def check_app_created_and_up(error_message="", expected_state="RUNNING"):
    if not error_message:
        error_message = "App was not up and running."

    err_msg_fmt = error_message + " Error: {details}"

    def validate(response):
        try:
            app_details = response.json
            observed_state = app_details["status"]["state"]
            observed_running_on = app_details["status"]["running_on"]
            observed_scheduled_to = app_details["status"]["scheduled_to"]

            details = (
                f"Unable to observe application in a {expected_state} state. "
                f"Observed: {observed_state}."
            )
            assert observed_state == expected_state, \
                err_msg_fmt.format(details=details) + " | " + json.dumps(app_details)

            if expected_state == "RUNNING":
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
            raise ValueError(err_msg_fmt % {"details": str(e)})

    return validate


def check_metrics_provider_content(error_message, name, type, type_details=None):
    """Create a callable to verify the content of a metrics provider in a response
    from the krake API.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the content of the metrics provider in the
    response is different from the given one.

    Args:
        error_message (str): the message that will be displayed if the check fails.
        name (str): the expected name of the metrics provider
        type (str): the expected type of the metrics provider
        type_details (str): the expected details of the metrics provider, i.e.,
            the value of spec.<type>.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        AssertionError: if the content of the metrics provider in the response is
            different from the given one.
    """
    assert type in ["prometheus", "static", "kafka"], (
        error_message + f" Invalid mp type '{type}'."
    )
    assert type_details, error_message + " No type_details were provided."
    expected_mp = {
        "api": "core",
        "kind": "GlobalMetricsProvider",
        "metadata": {"name": name},
        "spec": {"type": type, type: type_details},
    }

    def validate(response):
        observed_mp = response.json

        details = (
            f"\nExpected spec: {expected_mp['spec']}.\n"
            f"Observed: {observed_mp['spec']}."
        )
        assert observed_mp["spec"] == expected_mp["spec"], error_message + details

        details = (
            f"\nExpected name: {name}.\nObserved: {observed_mp['metadata']['name']}."
        )
        assert observed_mp["metadata"]["name"] == name, error_message + details

    return validate


def check_metric_content(error_message, name, mp_name, min, max, allowed_values=[], mp_metric_name=None):
    """Create a callable to verify the content of a metric in a response from the
    krake API.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the content of the metric in the response is different
    from the given one.

    Args:
        error_message (str): message that will be displayed if the check fails.
        name (str): expected name of the metric
        mp_name (str): expected name of the metric's metrics provider
        mp_metric_name (str): expected name of the metric's metrics provider's metric
        min (float): expected minimum value of the metric
        max (float): expected maximum value of the metric

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        AssertionError: if the content of the metric in the response is different
            from the given one.
    """

    if not mp_metric_name:
        mp_metric_name = name

    expected_metric = {
        "api": "core",
        "kind": "GlobalMetric",
        "metadata": {"name": name},
        "spec": {
            "allowed_values": allowed_values,
            "max": float(max),
            "min": float(min),
            "provider": {"metric": mp_metric_name, "name": mp_name},
        },
    }

    def validate(response):
        observed_metric = response.json

        details = (
            f"\nExpected spec: {expected_metric['spec']}.\n"
            f"Observed: {observed_metric['spec']}."
        )
        assert observed_metric["spec"] == expected_metric["spec"], (
            error_message + details
        )

        details = (
            f"\nExpected name: {name}."
            f"\nObserved: {observed_metric['metadata']['name']}."
        )
        assert observed_metric["metadata"]["name"] == name, error_message + details

    return validate


def check_response_content(error_message, content):
    """Create a callable to verify the content of a response from the
    krake API.

    To be used with the :func:`run`. The callable will raise an
    :class:`AssertionError` if the content of the response
    is not a **superset** of the given one.

    Args:
        error_message (str): message that will be displayed if the check fails.
        content (dict): expected content (subset) of the response.

    Returns:
        callable: a condition that will check the given content against the
            content from the response.

    Raises:
        AssertionError: if the content of the response is not a
            superset of the given one.
    """

    def validate(response):
        observed_content = response.json
        diff = DeepDiff(observed_content, content, ignore_order=True)
        # pop the diff items that are in the `observed_content` but not
        # in the `content` as the `content` could be a subset of `observed_content`
        diff.pop("dictionary_item_removed", None)

        assert not diff, error_message + "\n" + str(diff)

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

    Raises:
        AssertionError: if the return code doesn't equal the expected code
    """

    def validate(response):
        details = (
            f" Expected return code: {expected_code}."
            f" Observed return code: {response.returncode}."
        )
        assert response.returncode == expected_code, (
            str(response.output) + error_message + details
        )

    return validate


def check_status_code(response, expected_code=200):
    """Presents a function to validate the status code of a requests response object.

    Args:
        response (requests.Response): the response object, that will be checked.
        expected_code (int, optional): a http return code, to check against the one of
            the given response.

    Raises:
        AssertionError: if the status code doesn't equal the expected code
    """
    error_message = (
        f" Expected return code: {expected_code}."
        f" Observed return code: {response.status_code}."
    )
    assert response.status_code == expected_code, error_message


def check_empty_list(error_message):
    """Create a callable to verify that a response is empty.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the response is not an empty list.

    Args:
        error_message (str): the message that will be displayed if the check fails.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        ValueError: if a JSONDecodeError is caught
    """

    def validate(response):
        try:
            assert (
                response.json == []
            ), f"{error_message}\nList items: {str(response.json)}"
        except json.JSONDecodeError as e:
            raise ValueError(error_message) from e

    return validate


def check_resource_exists(error_message=""):
    """Create a callable to verify that a resource exists.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the chosen resource does not exist.

    The stdout using kubectl CLI against the kubernetes cluster contains
    `NotFound` string when the resource does not exist in kubernetes cluster.
    Krake API uses RFC7807 Problem representation of failures on the HTTP layer.
    The stdout using krakectl CLI against the krake API contains
    `NOT_FOUND_ERROR` string when the resource does not exist in krake.

    Args:
        error_message (str, optional): the message that will be displayed on failure.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        AssertionError: if the return code doesn't equal 0 or the response message
            contains 'not found'
    """

    def validate(response):
        assert response.returncode == 0
        assert not any(
            [msg in response.output for msg in ("NOT_FOUND_ERROR", "NotFound")]
        ), error_message

    return validate


def check_resource_deleted(error_message):
    """Create a callable to verify that a resource is deleted.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the chosen resource is shown as existing in the response
    given to the callable

    The stdout using kubectl CLI against the kubernetes cluster contains
    `NotFound` string when the resource does not exist in kubernetes cluster.
    Krake API uses RFC7807 Problem representation of failures on the HTTP layer.
    The stdout using krakectl CLI against the krake API contains
    `NOT_FOUND_ERROR` string when the resource does not exist in krake.

    Args:
        error_message (str): the message that will be displayed if the check fails.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        AssertionError: if the return code doesn't equal 1 or the response message
            contains 'not found'
    """

    def validate(response):
        # assert response.returncode == 1
        assert any(
            [msg in response.output for msg in ("NOT_FOUND_ERROR", "NotFound")]
        ), error_message + str(response.output)

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
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        ValueError: if a JSONDecodeError is caught or the image doesn't equal the
            expected image
    """

    def validate(response):
        try:
            image = response.json["spec"]["template"]["spec"]["containers"][0]["image"]
            assert image == expected_image, error_message
        except json.JSONDecodeError as e:
            raise ValueError(error_message) from e

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
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        ValueError: if a JSONDecodeError is caught or the replica doesn't equal the
            expected replica
    """

    def validate(response):
        try:
            replicas = response.json["spec"]["replicas"]
            assert replicas == expected_replicas, error_message
        except json.JSONDecodeError as e:
            raise ValueError(error_message) from e

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

    Raises:
        ValueError: if a KeyError or JSONDecodeError is caught or
            the cluster the app is running on doesn't equal the expected cluster
    """

    def validate(response):
        try:
            app_details = response.json
            running_on_dict = app_details["status"]["running_on"] or {}
            running_on = running_on_dict.get("name", None)
            scheduled_to_dict = app_details["status"]["scheduled_to"] or {}
            scheduled_to = scheduled_to_dict.get("name", None)
            msg = (
                error_message + f" App state: {app_details['status']['state']}, "
                f"App scheduled_to: {scheduled_to}, "
                f"App running_on: {running_on}"
            )
            assert running_on == expected_cluster, msg
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(error_message) from e

    return validate


def check_resource_container_health(container_health, error_message):
    """Create a callable to verify that the pod health of a resource is as expected.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the chosen resource has an unexpected pod health
    subresource

    Args:
        container_health (ContainerHealth):
        error_message (str): the message that will be displayed if the check fails.

    Returns:
        callable: a condition that will check its given response against the parameters
            of the current function.

    Raises:
        AssertionError: if the return code doesn't equal 1 or the response message
            contains 'not found'
    """

    def validate(response):
        try:
            assert container_health.desired_pods == \
                response.json["spec"]["replicas"]
            assert container_health.running_pods == \
                response.json["status"]["readyReplicas"]
        except Exception as e:
            assert False, error_message + " | Error: " + str(e)

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

    Raises:
        AssertionError: if the expected HTTP code doesn't match the response code
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


def get_scheduling_score(cluster, valued_metrics, cluster_metrics, scheduled_to=None):
    """Get the scheduling cluster score for the cluster (including stickiness).

    Args:
        cluster (str): cluster name
        valued_metrics (list[ValuedMetric]): list of the metrics and their values.
        cluster_metrics (dict[str, list[WeightedMetric]]): Dictionary of cluster
            weights. The keys are the names of the clusters and each value is a
            list with the weighted metrics of the cluster.
        scheduled_to (str): name of the cluster to which the application being
            scheduled has been scheduled.

    Returns:
        float: The score of the given cluster.

    """
    # Sanity check: Check that the metrics (i.e., the keys) are the same in both lists
    weighted_metrics = cluster_metrics[cluster]
    assert len(valued_metrics) == len(weighted_metrics)
    base_cluster_metrics = [
        weighted_metric.metric for weighted_metric in weighted_metrics
    ]
    assert all(
        valued_metric.metric in base_cluster_metrics for valued_metric in valued_metrics
    )

    position = 0
    for valued_metric in valued_metrics:
        # Find the weighted_metric with the same metric as the current valued_metric
        weighted_metric = next(
            weighted_metric
            for weighted_metric in weighted_metrics
            if weighted_metric.metric == valued_metric.metric
        )
        position += valued_metric.value * weighted_metric.weight

    norm = sum(weighted_metric.weight for weighted_metric in weighted_metrics)

    if scheduled_to == cluster:
        stickiness_value = 1
        position += STICKINESS_WEIGHT * stickiness_value
        norm += STICKINESS_WEIGHT
    return position / norm


def check_static_metrics(expected_metrics, error_message=""):
    """Create a callable to verify that the static provider response contains
    the expected values.

    To be used with the :meth:`run` function. The callable will raise an
    :class:`AssertionError` if the static metrics in the response are different
    from the given ones.

    Args:
        expected_metrics (dict[str, float]): Dictionary with the metrics names as
            keys and metric values as values.
        error_message (str): the message that will be displayed if the
            check fails.

    Returns:
        callable: a condition that will check its given response against
            the parameters of the current function.

    Raises:
        ValueError: if the observed metrics don't equal the expected metrics or
            another exception is caught
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
            raise ValueError(error_message + f"Error: {e}")

    return validate


def get_other_cluster(this_cluster, clusters):
    """Return the cluster in clusters, which is not this_cluster.

    Args:
        this_cluster (str): name of this_cluster
        clusters (list): list of two cluster names.

    Returns:
        the name of the other cluster.
    """
    return clusters[0] if clusters[1] == this_cluster else clusters[1]


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
        dict[str, dict] with same length as cluster_names.
            The first `len(values)` <key, value> pairs will be:
                cluster_names[i]: {sub_keys[i]: values[i]}
            The last `len(cluster_names) - len(values)` <key: value> pairs will be:
                cluster_names[i]: {}

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


def create_cluster_label_info(cluster_names, label, values):
    """
    Convenience method for preparing cluster label information.
    """
    return create_cluster_info(cluster_names, label, values)


def create_cluster_metric_info(cluster_names, sub_keys, values, namespaced):
    """
    Convenience method for preparing cluster metric information.
    """
    cluster_info = create_cluster_info(cluster_names, sub_keys, values)
    metric_info = dict.fromkeys(list(cluster_info.keys()), {})
    for c, info in cluster_info.items():
        for m, w in info.items():
            metric_info[c][m] = {"weight": w, "namespaced": namespaced}
    return metric_info
