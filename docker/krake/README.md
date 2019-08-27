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
$ jinja2_standalone_compiler -s jinja2_standalone_config --path .

# Run docker compose
$ docker-compose up --detach
```

## Environment Variables Explanations

| Environment Variable                             | Default Value                      | Description                                                                               |
|--------------------------------------------------|------------------------------------|-------------------------------------------------------------------------------------------|
| ETCD_HOST                                        | 127.0.0.1                          | Krake [etcdv3](https://github.com/etcd-io/etcd/releases/) database address                |
| ETCD_PORT                                        | 2379                               | Krake [etcdv3](https://github.com/etcd-io/etcd/releases/) database port                   |
| TLS_ENABLED                                      | false                              | Enables TLS on Krake Api                                                                  |
| TLS_CERT                                         | tmp/pki/system:api-server.pem      | Krake Api certificate file path                                                           |
| TLS_KEY                                          | tmp/pki/system:api-server-key.pem  | Krake Api private-key file path                                                           |
| TLS_CLIENT_CA                                    | tmp/pki/ca.pem                     | Krake Api client certificate authentication file path - contains certificate authorities  |
| AUTHENTICATION_ALLOW_ANONYMOUS                   | true                               | Enables anonymous request                                                                 |
| AUTHENTICATION_STRATEGY_KEYSTONE_ENABLED         | false                              | Enables Keystone authentication                                                           |
| AUTHENTICATION_STRATEGY_KEYSTONE_ENDPOINT        | http://localhost:5000/v3           | Keystone authentication endpoint                                                          |
| AUTHENTICATION_STRATEGY_STATIC_ENABLED           | true                               | Enables Static authentication (requests are authenticated by user-name)                   |
| AUTHENTICATION_STRATEGY_STATIC_NAME              | system                             | Static authentication user-name                                                           |
| AUTHORIZATION                                    | always-allow                       | Authorization mode: RBAC;always-allow;always-deny                                         |
| CONTROLLERS_KUBERNETES_CLUSTER_API_ENDPOINT      | http://localhost:8080              | Krake Api endpoint for Krake kubernetes controller                                        |
| CONTROLLERS_KUBERNETES_CLUSTER_WORKER_COUNT      | 5                                  | Krake kubernetes controller workers count                                                 |
| CONTROLLERS_KUBERNETES_APPLICATION_API_ENDPOINT  | http://localhost:8080              | Krake Api endpoint for Krake kubernetes controller                                        |
| CONTROLLERS_KUBERNETES_APPLICATION_WORKER_COUNT  | 5                                  | Krake kubernetes controller workers count                                                 |
| CONTROLLERS_SCHEDULER_API_ENDPOINT               | http://localhost:8080              | Krake Api endpoint for Krake scheduler controller                                         |
| CONTROLLERS_SCHEDULER_WORKER_COUNT               | 5                                  | Krake scheduler controller workers count                                                  |
| LOG_LEVEL                                        | INFO                               | Krake logging level                                                                       |
