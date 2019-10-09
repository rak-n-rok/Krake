import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def run(command, check=True, retry=0, interval=1, condition=None, error_message=""):

    """Runs a subprocess

    This function implements a retry logic. A number of retries can be
    specified through the ``retry`` argument. The condition for a retry to
    occur can be either a ``check`` of the command exit value, or a specific
    ``condition``, or both.

    Args:
        command (str): The command to run
        check (bool, optional): If True, checks the return value of the
            specified command. This can be retried with specifying the retry
            option
        retry (int, optional): Number of retry to perform
        interval (int, optional): Interval in seconds between two retries
        condition (callable, optional): Additional condition that has to be
            met. This is a callable taking the command response as argument.
        error_message (str, optional): Error message to return if the
            specified condition is not met

    Returns:
        output: The output of the command, or if the provided condition is not
            met, the provided error message.

    """
    logger.debug(f"Running: {command}")

    while True:
        try:
            process = subprocess.run(
                command.split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=check,
            )
        except subprocess.CalledProcessError as e:
            logger.debug(
                "Caught CalledProcessError: command exited with a non-zero exit code"
            )
            retry -= 1
            if retry <= 0:
                return e.stdout.decode()
            logger.debug("Going to sleep... will retry")
            time.sleep(interval)
            continue

        response = process.stdout.decode()

        # If no condition has been given to check, simply return the response
        if condition is None:
            return response

        # If condition is met, return the response
        if condition(response):
            return response

        # If condition is not met, decrease the amount of retries and sleep
        logger.debug("Provided condition is not met")
        retry -= 1
        if retry <= 0:
            return error_message
        logger.debug("Going to sleep... will retry")
        time.sleep(interval)
