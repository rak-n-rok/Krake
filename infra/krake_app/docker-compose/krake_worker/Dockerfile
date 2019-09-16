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
  keystoneauth1~=3.11.0 \
  kubernetes~=10.0.0a1 \
  mysql-connector-python~=8.0.15 \
  pika~=0.12.0 \
  pyOpenSSL~=18.0.0 \
  pytest \
  pytest-cov \
  python-magnumclient~=2.10.0 \
  retrying~=1.3.3


# Create user
RUN useradd -s /bin/bash -m krake

# Set user
USER krake

