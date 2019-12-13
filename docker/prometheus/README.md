# Prometheus and metric exporter Docker

This subdirectory is used to host a bundle to create a docker
infrastructure running Prometheus and metric exporter.

Prometheus server is deployed in minimal configuration suitable for end-to-end
testing of Krake infrastructure.
Simple metrics exporter server exposes heat demand metrics also in minimal
configuration suitable for end-to-end testing of Krake infrastructure.

Metrics exporter generates random heat demand metrics for multiple zones.
Default number of zones is 5: `heat_demand_zone_1` .. `heat_demand_zone_5`.
Random heat demand metric value is regenerated (each 10s) from interval :
     <`zone_number` - 1, `zone_number`)

## Prerequisites

 - [docker](https://www.docker.com/)
 - [Jinja2 compiler](https://github.com/filwaitman/jinja2-standalone-compiler)


## Install

- Compose file defines and runs docker containers for provisioning of
Prometheus and metric exporter infrastructure.

- Generate `.env` file (from `.env.j2` template) to set up compose file.
Insert custom variables, if any (optional), see more in `.env.j2`.
- Generate `prometheus.yml` file (from `prometheus.yml.j2` template) to set up prometheus configuration setting.
Insert custom variables, if any (optional), see more in `prometheus.yml.j2`.

```bash
$ cd docker/prometheus

# Generate `.env` file from `.env.j2` template.
$ pip install jinja2_standalone_compiler
$ vim jinja2_standalone_config  # Insert custom variables, if any (optional)
$ jinja2_standalone_compiler -s jinja2_standalone_config --path .env.j2
$ jinja2_standalone_compiler -s jinja2_standalone_config --path config/prometheus.yml.j2
```

- Run docker compose

```bash
$ docker-compose up --detach
```
