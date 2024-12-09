# Dockerfile for assembling the Krake image from krake source directory
# It is defined as a multi-stage build, where the first stage builds the Krake project
# and all its dependencies into the virtualenv. After that, the second stage copies the Krake build
# into the final docker image.
#
# .. code:: bash
#
#     docker build --tag krake:latest --file docker/krake/Dockerfile .
#
# The Dockerfile doesn't set the default command and parameters, that Krake components need to run.
# These parameters should be set in command line during the start of the Docker container,
# or via the docker-compose ``command`` directive.
# An example for the Krake API can be found below
#
# .. code:: bash
#
#     docker run --detach --tty --interactive \
#                --publish 8080:8080 --name krake-api \
#                krake:latest python3 -m krake.api
#
# Note: The UID of the "krake" user inside the image can be set with the argument "krake_uid".

FROM python:3.12-slim AS base

FROM base as builder

# Install essential build tools needed for the installation of some python
# dependencies (e.g., netifaces)
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

# Create a virtualenv with fresh pip and setuptools
RUN python3 -m venv /opt/krake
ENV PATH="/opt/krake/bin:${PATH}"
RUN pip install --upgrade pip setuptools

# Generate the default configuration files
COPY ./krake/scripts/krake_generate_config /opt/krake/bin
COPY ./templates/config /tmp/config
RUN mkdir -p /etc/krake && krake_generate_config --dst /etc/krake /tmp/config/*.template

# Install the pinned requirements, which must match the python version of the
# base image, into the virtualenv
COPY ./requirements/requirements-py310.txt /tmp/requirements.txt
RUN pip install --no-deps -r /tmp/requirements.txt

# Copy krake sources
COPY ./krake/krake /krake/krake
COPY ./krake/pyproject.toml /krake

# Install krake into the virtualenv
# Note:
# - We always use `pip install` with the `--no-deps` flag, which ensures that
#   we do no accidentally pull in dependencies which are not specified in the
#   requirements.txt file.
# - The final `pip check` tests if all dependencies are satisfied, i.e., it
#   will fail if our requirements.txt is incomplete or inconsistent.
RUN pip install --no-deps /krake && pip check

FROM base as runner

ARG krake_uid=17890

# Create a dedicated, non-root application user for krake
# TODO: why chmod 777? this is unsafe.
RUN useradd --create-home --uid $krake_uid --shell /bin/bash krake
RUN chown krake:krake /home/krake
RUN chmod 777 /home/krake
RUN install -d -o krake -g krake -m 777 /home/krake/logs

# Make the commands of the virtualenv available again
ENV PATH="/opt/krake/bin:${PATH}"

# Copy the generated configuration files
COPY --from=builder /etc/krake /etc/krake

# Copy the virtualenv with all installed packages
COPY --from=builder /opt/krake /opt/krake

# Finally, switch to the dedicated user
USER krake
WORKDIR /home/krake
