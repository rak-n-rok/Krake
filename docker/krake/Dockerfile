# Dockerfile for assembling krake image from krake source directory.
# It is defined as a multi-stage builds where the first stage builds krake project
# and all its dependencies into the virtualenv and the second stage copies krake
# build into the final docker image.
#
# .. code:: bash
#
#     docker build --tag krake:latest --file docker/krake/Dockerfile .
#
# Dockerfile doesn't set the default command and parameters,
# for krake component runs. This should be set in command line
# when docker container runs or via docker-compose ``command`` directive.
#
# .. code:: bash
#
#     docker run --detach --tty --interactive \
#                --publish 8080:8080 --name krake-api \
#                krake:latest python3 -m krake.api
#
# The UID of the "krake" user inside the image can be set with the argument "krake_uid".

FROM python:3.6-slim AS base

FROM base as builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Generate the default configuration files
COPY ./krake/scripts /krake
COPY ./config /tmp/config
RUN mkdir -p /etc/krake && \
  python /krake/krake_generate_config --dst /etc/krake /tmp/config/*template

FROM base as runner

ARG krake_uid=17890

COPY --from=builder /etc/krake /etc/krake

# Install Krake
COPY ./krake/krake /krake/krake
COPY ./krake/scripts /krake/scripts
COPY ./krake/setup.py /krake
RUN pip install --upgrade pip && pip3 install /krake

RUN useradd --create-home --uid $krake_uid --shell /bin/bash krake

USER krake
WORKDIR /home/krake
