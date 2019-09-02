import datetime
import logging
import os
import subprocess
import time

logging.basicConfig(level=logging.DEBUG)


def run(
    command,
    polling_interval=datetime.timedelta(seconds=1),
    shell=True,
    executable="/bin/bash",
):
    """Run a subprocess.
    Any subprocess output is emitted through the logging modules.
    Returns:
    output: A string containing the output.
    """
    logging.info("Running: %s \n", " ".join(command))

    env = os.environ

    process = subprocess.Popen(
        command,
        cwd=None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=shell,
        executable="/bin/bash",
    )

    output = []
    while process.poll() is None:
        process.stdout.flush()
        for line in iter(process.stdout.readline, b""):
            line = line.decode().strip()
            output.append(line)
            logging.info(line)

        time.sleep(polling_interval.total_seconds())

    process.stdout.flush()
    for line in iter(process.stdout.readline, b""):
        line = line.decode().strip()
    output.append(line)

    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            "cmd: {0} exited with code {1}".format(
                " ".join(command), process.returncode
            ),
            "\n".join(output),
        )

    return "\n".join(output)
