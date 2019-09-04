import logging
import os
import subprocess
import time

logging.basicConfig(level=logging.DEBUG)


def run(command, shell=True, executable="/bin/bash", check=True, retry=0, interval=1):
    """Run a subprocess.
    Any subprocess output is emitted through the logging modules.
    Returns:
    output: A string containing the output.
    """
    logging.info("Running: %s \n", " ".join(command))

    env = os.environ

    while True:
        try:
            process = subprocess.run(
                command,
                cwd=None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=shell,
                check=check,
            )
            return process.stdout.decode()

        except subprocess.CalledProcessError as e:
            logging.info("Caught CalledProcessError")
            retry -= 1
            if retry <= 0:
                return e.stdout.decode()
            logging.info("Going to sleep... will retry")
            time.sleep(interval)
            continue
