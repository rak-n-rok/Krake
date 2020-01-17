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

FROM python:3.6-slim AS base

FROM base as builder

RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  gcc

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ./krake /krake
COPY ./config /tmp/config

RUN pip3 install /krake

RUN mkdir -p /etc/krake && \
  krake_generate_config --dst /etc/krake /tmp/config/*template

FROM base as runner

COPY --from=builder /etc/krake /etc/krake
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"
