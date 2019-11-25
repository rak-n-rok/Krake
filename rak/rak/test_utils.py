import json
import logging
import time
import subprocess
from dataclasses import MISSING

logger = logging.getLogger("krake.test_utils.run")


class Response(object):
    """The response of a command

    Attributes:
        result (testinfra.CommandResult): Result of the remove command
    """

    def __init__(self, result):
        self._result = result
        self._json = MISSING  # Cache parsed JSON output

    def __getattr__(self, key):
        return getattr(self._result, key)

    @property
    def json(self):
        """str: Deserialized JSON of the command's stdout"""
        if self._json is MISSING:
            self._json = json.loads(self.stdout)
        return self._json

    def __repr__(self):
        return (
            f"Response(command={self.command!r}, "
            f"exit_status={self.exit_status}, "
            f"stdout={self._stdout or self._stdout_bytes!r}, "
            f"stderr={self._stderr or self._stderr_bytes!r})"
        )


def run(command, host, retry=0, interval=1, condition=None, error_message=""):
    """Runs a command on a remote host

    Tests are typically subjects to race conditions. We frequently have to
    wait for an object to reach a certain state (RUNNING, DELETED, ...)

    Therefore, this function implements a retry logic:

    - The ``condition`` callable takes the command's response as argument and
      checks if it suits a certain format.
    - The ``retry`` and ``interval`` arguments control respectively the number
      of retries the function should attempt before raising an
      `AssertionError`, and the number of seconds to wait between each retry.

    The signature of ``condition`` is:

    .. function:: my_condition(response, error_message)

        :param Response response: The command response.
        :param string error_message: The error message to include in the
            ``AssertionError`` if raised.
        :raises AssertionError: Raised when the condition is not met.

    Note that is doesn't make sense to provide a ``condition`` without a
    ``retry``. One should rather test this condition in the calling function.

    Args:
        command (str): The command to run
        host (testinfra.Host): Host on which this command should be executed
        retry (int, optional): Number of retry to perform
        interval (int, optional): Interval in seconds between two retries
        condition (callable, optional): Condition that has to be met.
        error_message (str, optional): Error message to return if the
            specified condition is not met

    Returns:
        Response: The output and return code of the provided command

    Raises:
        AssertionError: Raise an exception if the ``condition`` is not met.

    Example:
        .. code:: python

            from rak.test_utils import run

            # This condition will check if the command has a null return
            # value
            def check_return_code(response, error_message):
                assert response.returncode == 0, error_message

            # This command has a risk of race condition
            some_command = "..."

            # The command will be retried 10 time until the command is
            # successful or will raise an AssertionError
            run(
                some_command,
                host=host,
                condition=check_return_code,
                error_message="Unable to run the command successfully",
                retry=10,
                interval=1,
            )

    """
    logger.debug(f"Running: {command}")

    while True:
        result = host.run(command, stderr=subprocess.STDOUT)
        response = Response(result)

        # If no condition has been given to check, simply return the response
        if condition is None:
            logger.debug("%s", response)
            assert (
                response.rc == 0
            ), f"Unexpected exit code {response.rc} for {response}"
            return response

        try:
            condition(response, error_message)
            # If condition is met, return the response
            logger.debug("%s", response)
            return response
        except AssertionError:
            # If condition is not met, decrease the amount of retries and
            # sleep
            retry -= 1
            if retry <= 0:
                # All retries have failed
                raise
            logger.debug("Retry in %s seconds", interval)
            time.sleep(interval)
