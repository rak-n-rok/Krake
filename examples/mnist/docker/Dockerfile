FROM python:3.8.3-slim AS base
FROM base as builder

ARG DEBIAN_FRONTEND=/tmp/pki/

RUN apt-get update && \
    apt-get install -y procps

WORKDIR /mnist
RUN mkdir -p ./checkpoint
COPY mnist_training.py .
COPY _minio.py .

RUN pip3 install tensorflow==2.4.3 keras==2.4.3 boto3 loguru minio

ENTRYPOINT python ./mnist_training.py
