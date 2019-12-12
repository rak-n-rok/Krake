# Krake Docker

This subdirectory is used to host a bundle to create a docker
infrastructure (based on Python 3.6) running Krake Api, Krake Controllers
and Krake DB.

## Prerequisites

 - [docker](https://www.docker.com/)
 - [Jinja2 compiler](https://github.com/filwaitman/jinja2-standalone-compiler) (optional) - to generate custom `.env` file


## Krake Docker infrastructure

### Build Krake docker image using Dockerfile

```bash
# Get the latest version of Krake
$ git clone https://gitlab.com/rak-n-rok/krake
$ cd krake
$ docker build --tag krake:latest --file docker/krake/Dockerfile .
```

### Run Krake infrastructure using docker run

- Dockerfile doesn't set the default command and parameters,
for krake component runs. This should be set in command line.
- Use `--env` option to overwrite default configuration setting,
see more in Environment Variables Explanations

#### Run Krake API

```bash
$ docker run --detach --tty --interactive \
             --env ETCD_HOST=etcd-host --publish 8080:8080 --name krake-api \
             krake:latest python3 -m krake.api
```

#### Run Krake Controller Kubernetes

```bash
$ docker run --detach --tty --interactive \
             --env KRAKE_HOST=krake-api --name krake-ctrl-kubernetes \
             krake:latest python3 -m krake.controller.kubernetes
```

#### Run Krake Controller Scheduler

```bash
$ docker run --detach --tty --interactive \
             --env KRAKE_HOST=krake-api --name krake-ctrl-scheduler \
             krake:latest python3 -m krake.controller.scheduler
```

### Run Krake infrastructure using docker-compose

- Compose file defines and runs docker containers for provisioning of the Krake Api,
Krake Controllers and Krake DB infrastructure.
- Pre-built krake image is a prerequisite for this compose file.
- Use `--env` option or generate custom `.env` file (from `.env.j2` template)
 to overwrite default Krake configuration setting, see more in Environment Variables Explanations

```bash
$ cd docker/krake

# Generate custom `.env` file from `.env.j2` template (optional)
$ pip install jinja2_standalone_compiler
$ vim jinja2_standalone_config  # Insert custom Krake variables, if any
$ jinja2_standalone_compiler -s jinja2_standalone_config --path .env.j2

# Create minimal configuration for the Krake components
$ config/generate --dst /etc/krake/ config/*template --host krake-api --etcd-host krake-db

# Run docker compose
$ docker-compose up --detach
```

## Environment Variables Explanations

These variables need to be set in the `.env` file, or can be automatically added by Ansible in the `.env.j2` template.

| Environment Variable | Default Value | Description                                                                                                    |
|----------------------|---------------|----------------------------------------------------------------------------------------------------------------|
| ETCD_HOST            | krake-db      | Krake [etcdv3](https://github.com/etcd-io/etcd/releases/) database address (only used internally, not exposed) |
| ETCD_PORT            | 2379          | Krake [etcdv3](https://github.com/etcd-io/etcd/releases/) database port (only used internally, not exposed)    |
| ETCD_PEER_PORT       | 2380          | Krake [etcdv3](https://github.com/etcd-io/etcd/releases/) database port for peers listening                    |
| API_HOST             | krake-api     | Address of the Krake API endpoint (only used internally, not exposed)                                          |
| API_PORT             | 8080          | Port of the Krake API endpoint                                                                                 |
