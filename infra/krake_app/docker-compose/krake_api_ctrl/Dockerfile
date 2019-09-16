# This Dockerfile follows Best practices for writing Dockerfiles
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/

# Image
FROM python:3.6

# Install packages (ABC order)
RUN apt-get update && apt-get install -y \
  apt-utils \
  libcap-dev \
  libpcre3-dev \
  net-tools \
  python3-pip \
  supervisor \
  telnet \
  uuid-dev \
  uwsgi \
  uwsgi-src \
  vim

# Install Krake dependencies (ABC order)
RUN pip3 install \
  attrs~=18.2.0 \
  flake8 \
  flask~=1.0.2 \
  jsonschema~=2.6.0 \
  mysql-connector-python~=8.0.15 \
  mysqlclient~=1.4.2 \
  openstacksdk~=0.17.2 \
  pika~=0.12.0 \
  prometheus_client~=0.6.0 \
  pytest \
  pytest-cov \
  urllib3~=1.24.3 \
  requests~=2.20.1 \
  retrying~=1.3.3 \
  SQLAlchemy~=1.2.17

# Create user
RUN useradd -s /bin/bash -m krake

# Build python36 uWSGI plugin
RUN uwsgi --build-plugin "/usr/src/uwsgi/plugins/python python36"
RUN mv python36_plugin.so /usr/lib/uwsgi/plugins/python36_plugin.so
RUN chmod 644 /usr/lib/uwsgi/plugins/python36_plugin.so

# Launch init.sh
COPY init.sh /
RUN chmod +x /init.sh
ENTRYPOINT ["/init.sh"]
