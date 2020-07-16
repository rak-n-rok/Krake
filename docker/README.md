# Docker

This directory is used to host a bundle to create various docker infrastructures.
Docker infrastructure bundle is organized in separate subdirectory and contains
several templates which have to be configured before use.

Currently supported infrastructure bundles:

- Krake
- Prometheus

## Prerequisites

 - [docker](https://www.docker.com/)
 - [docker-compose](https://docs.docker.com/compose/)
 - [Jinja2](https://pypi.org/project/Jinja2/) (optional)


## Configuration

Each defined docker infrastructure bundle in this directory contains standard jinja2
templates which have to be configured before use.
Configuration can be done by corresponding Ansible playbook (see ansible directory) or
by the script `docker/generate` in case of standalone docker installation.

### Standalone docker installation

- Python script `docker/generate` can be used to generate files from jinja2 templates
for defined docker infrastructure bundles.

  - [Jinja2](https://pypi.org/project/Jinja2/) is a prerequisite.

  - The `docker/docker.yaml` file defines the input variables for the `docker/generate`
    script to generate the `docker-compose` files for each bundle.

  - It can either be crafted by hand, using the `docker/docker.yaml.template` as a base
    example, or can be generated using the `krake_generate_config` script,
    which is used to generate all Krake configuration files.
      - The minimal recommended configuration is as follow:
      ```bash
      $ krake_generate_config --dst docker docker/docker.yaml.template --api-host krake-api --etcd-host krake-db
      ```

  - The `docker/generate` script also accepts using an alternative configuration file by
    passing the `--config` argument.

```bash
# Install Jinja2
$ pip3 install Jinja2

# Configure corresponding docker bundle
$ docker/generate --config docker.yaml [docker/krake] [docker/prometheus]
```

## Install

### Krake

Krake docker infrastructure bundle running Krake Api, Krake Controllers and Krake DB.

- Pre-built Krake image is a prerequisite for the compose file.

- The configuration files for all Krake components need to be generated, see krake/README.

  - The minimal recommended configuration is as follows:
  ```bash
  $ mkdir /etc/krake
  $ krake_generate_config --dst /etc/krake config/*.template rok.yaml.template --api-host krake-api --etcd-host krake-db
  ```

#### Build Krake image
```bash
# Get the latest version of Krake
$ git clone https://gitlab.com/rak-n-rok/krake
$ cd krake
# Build and tag the Krake image
$ docker build --tag krake:latest --file docker/krake/Dockerfile .
```

#### Run Krake infrastructure

```bash
$ docker-compose --file krake/docker-compose.yaml up --detach
```

### Prometheus

Prometheus server is deployed in minimal configuration suitable for end-to-end
testing of Krake infrastructure.
Simple metrics exporter server exposes heat demand metrics also in minimal
configuration suitable for end-to-end testing of Krake infrastructure.

Metrics exporter generates random heat demand metrics for multiple zones.
Default number of zones is 5: `heat_demand_zone_1` .. `heat_demand_zone_5`.
Random heat demand metric value is regenerated (each 10s) from interval :
     <`zone_number` - 1, `zone_number`)

#### Run Prometheus infrastructure

```bash
$ docker-compose --file prometheus/docker-compose.yaml up --detach
```

### Krake + Prometheus infrastructure

Multiple infrastructure bundles can be executed in one docker network

```bash
$ docker-compose --file krake/docker-compose.yaml --file prometheus/docker-compose.yaml up --detach
```

## Manage infrastructure containers

```bash
# Each container can be managed by standard docker-compose commands e.g.:
$ docker-compose --file krake/docker-compose.yaml stop krake-api
$ docker-compose --file krake/docker-compose.yaml restart krake-api
```
