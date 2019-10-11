import json
import logging
import subprocess
import time
from dataclasses import MISSING

logger = logging.getLogger(__name__)


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


def run(command, retry=0, interval=1, condition=None, error_message=""):
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

    .. function:: my_condition(response, error_message)

        :param Response response: The command response.
        :param string error_message: The error message to include in the
            ``AssertionError`` if raised.
        :raises AssertionError: Raised when the condition is not met.

    Note that is doesn't make sense to provide a ``condition`` without a
    ``retry``. One should rather test this condition in the calling function.

    Args:
        command (str): The command to run
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

            import util

            # This condition will check if the command has a null return
            # value
            def check_return_code(response, error_message)
                if response.returncode != 0
                    raise AssertionError

            # This command has a risk of race condition
            some_command = "..."

            # The command will be retried 10 time until the command is
            # successul or will raise an AssertionError
            util.run(
                some_command,
                condition=check_return_code,
                error_message="Unable to open my_file",
                retry=10,
                interval=1,
            )
            error_message="Unable to open my_file", retry=10, interval=1)

    """
    logger.debug(f"Running: {command}")

    while True:
        process = subprocess.run(
            command.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

        response = Response(process.stdout.decode(), process.returncode)

        # If no condition has been given to check, simply return the response
        if condition is None:
            return response

        try:
            condition(response, error_message)
            # If condition is met, return the response
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
