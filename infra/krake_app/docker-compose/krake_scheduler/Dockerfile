# This Dockerfile follows Best practices for writing Dockerfiles
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/

# Image
FROM python:3.6

# Install packages (ABC order)
RUN apt-get update && apt-get install -y \
  apt-utils \
  net-tools \
  python3-pip \
  telnet \
  vim

# Install Krake dependencies (ABC order)
RUN pip3 install \
  attrs~=18.2.0 \
  flake8 \
  jsonschema~=2.6.0 \
  pika~=0.12.0 \
  pytest \
  pytest-cov \
  urllib3~=1.24.3 \
  requests~=2.20.1 \
  retrying~=1.3.3

# Create user
RUN useradd -s /bin/bash -m krake

# Set user
USER krake
