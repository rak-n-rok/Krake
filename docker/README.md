# Docker

This directory is used to host a bundle to create various docker infrastructures.
Docker infrastructure bundle is organized in separate subdirectory and contains
several templates which have to be configured before use.

Currently supported infrastructure bundles:

- Krake
- [Prometheus](https://prometheus.io/)
- [Infrastructure Manager](https://github.com/grycap/im) (IM)

## Prerequisites

- [docker](https://www.docker.com/)
- [docker-compose](https://docs.docker.com/compose/)
- [Jinja2](https://pypi.org/project/Jinja2/)

## Generate configuration files

Each defined docker infrastructure bundle in this directory contains standard jinja2
templates which have to be configured/generated before use.

Python script `docker/generate` can be used to generate files from jinja2 templates
for defined docker infrastructure bundle. Alternatively, this can be done by the
corresponding Ansible playbook (see ansible directory).

Please note that the [Jinja2](https://pypi.org/project/Jinja2/) python library
is a prerequisite here. Install it as follows:
```bash
pip install Jinja2
```

The `docker/generate` script expects configuration file for the docker infrastructure
bundle. This configuration file is required and should be passed via the script's
``--config`` argument. The configuration file could be crafted by hand,
using the `docker/docker.yaml.template` as a base example, or can be generated
using the `krake_generate_config` script, which is used to generate all Krake
configuration files.

You can generate the minimal recommended configuration as follows:

```bash
krake_generate_config --dst docker docker/docker.yaml.template --api-host krake-api --etcd-host krake-db
```

The above command generates the `docker/docker.yaml` configuration file.
Let's apply it and (finally) generate the docker bundle for a target infrastructure as follows:

```bash
# Configure corresponding docker bundle
docker/generate --config docker/docker.yaml [docker/krake] [docker/prometheus] [docker/im]
```

The above command generates files needed for a target infrastructure launching
in the Docker environment. At least, you should find the corresponding `docker-compose.yaml` file
inside the `docker/<infrastructure>` directory.


## Launch the infrastructure bundles

This section describes how you can apply the generated docker infrastructure bundles.

### Krake

Krake infrastructure bundle launching the Krake Api, multiple Krake Controllers and Krake DB in the
Docker environment.

#### Prerequisites

- Pre-built Krake image is a prerequisite for the docker-compose file. You can build it as follows:
  ```bash
  # Get the latest version of Krake
  git clone https://gitlab.com/rak-n-rok/krake
  cd krake
  # Build and tag the Krake image
  docker build --tag krake:latest --file docker/krake/Dockerfile .
  ```

- The configuration files for all Krake components need to be pre-generated as well, see krake/README.
  You can generate the minimal recommended configuration as follows:
  ```bash
  sudo mkdir /etc/krake
  sudo $(id -u):$(id -g) /etc/krake/
  krake_generate_config --dst /etc/krake config/*.template rok.yaml.template \
    --api-host krake-api --etcd-host krake-db --allow-anonymous \
    --static-authentication-enabled
  ```

  Note: This tutorial wants to be in sync with an Ansible playbook (see ansible directory) that
  can be used for launching the Krake infrastructure as well. Therefore, the `/etc` directory is
  used here, and if you use the standard Linux distro, you have to set the correct permissions.

#### Launch the Krake infrastructure

Finally, launch the Krake infrastructure in the Docker environment as follows:

```bash
docker-compose --file docker/krake/docker-compose.yaml up --detach
```

Test it and get the Krake API version as follows:

```bash
curl -s http://localhost:8080 | jq
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

#### Launch the Prometheus infrastructure

Launch the Prometheus infrastructure in the Docker environment as follows:

```bash
docker-compose --file docker/prometheus/docker-compose.yaml up --detach
```

Test it and query the current `heat_demand_zone_3` value as follows:

```bash
curl -s http://localhost:9090/api/v1/query?query=heat_demand_zone_3 | jq
```


## Infrastructure Manager

Infrastructure Manager server is deployed in minimal configuration suitable for end-to-end
testing of Krake infrastructure.

#### Launch the Infrastructure Manager server

Launch the Infrastructure Manager server in the Docker environment as follows:

```bash
docker-compose --file docker/im/docker-compose.yaml up --detach
```

Test it and get the IM API version as follows:

```bash
curl -s http://localhost:8800/version
```


### Launch all currently supported (Krake, Prometheus, IM) infrastructures

Multiple infrastructure bundles can be executed in one docker network.
This allows that e.g. Krake scheduler could communicate with the Prometheus
instance using the `localhost` network.
Launch the Krake, Prometheus and IM infrastructures in the Docker environment as follows:

```bash
docker-compose --file docker/krake/docker-compose.yaml \
  --file docker/prometheus/docker-compose.yaml up \
  --file docker/im/docker-compose.yaml up \
  --detach
```
