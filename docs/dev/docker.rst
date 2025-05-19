======
Docker
======

It is possible to use Docker containers for the development of Krake. Docker provides
a separation layer for Krake, which helps locate problems and separate components during development.
It also enables the usage of `docker-compose`, which enable rapid deployment and teardown
of a complete Krake infrastructure on the spot.
The `docker` directory is used to host a bundle to create various docker infrastructures.
The Docker infrastructure bundle can be found inside the Krake project directory, and is organized in separate
subdirectories containing several templates, which have to be configured before use.

Currently, the following infrastructure bundles are supported besides Krake:

- Krake
- Prometheus_
- InfrastructureManager_ (IM)

Use an online Docker image
==========================

Krake already provides prebuilt docker images, which can be downloaded in order to run
a Krake instance or if it is not necessary to built a local image.
These docker images can be found in the following registries:

* registry.gitlab.com

Images are named `krake:<TAG>`, whereas `<TAG>` can be either `latest` or some version number, which should correspond to a version tag inside the Gitlab repository.

Create a local Docker image
===========================

If there is either no Krake docker image on the local machine, or if changes were made to the code base,
it would be necessary to create a new docker image.
The necessary `Dockerfile` for this task can be found in the krake subdirectory of the docker directory.

The Dockerfile is defined as a multi-stage build, where the first stage builds the Krake project
and all its dependencies into the virtualenv. After that, the second stage copies the Krake build
into the final docker image.
The image can be created with

.. code:: bash

     docker build --tag krake:latest --file docker/krake/Dockerfile .

The Dockerfile doesn't set the default command and parameters, that Krake components need to run.
These parameters should be set in command line during the start of the Docker container,
or via the docker-compose ``command`` directive.
An example for the Krake API can be found below

.. code:: bash

     docker run --detach --tty --interactive \
                --publish 8080:8080 --name krake-api \
                krake:latest python3 -m krake.api

Note: The UID of the `krake` user inside the image can be set with the argument `krake_uid` during the image creation step.

Prerequisites for Infrastructure bundles
========================================

Before using any of infrastructure bundles, the following prerequisites need to be installed:
- docker_
- dockercompose_
- Jinja2_

Generate configuration files
----------------------------

Each defined docker infrastructure bundle in this directory contains standardized jinja2
templates, which have to be configured/generated before using the respective bundle.

The included Python script `docker/generate` can be used to generate files from jinja2 templates
for defined docker infrastructure bundle. Alternatively, this can be done with the
corresponding Ansible playbook (see ansible directory).

Please note, that the Jinja2_ python library is a prerequisite here, which can be installed as follows:

.. code:: bash

    pip install Jinja2


The `docker/generate` script expects configuration file for the docker infrastructure
bundles. These configuration files are required and should be passed via the script's
``--config`` argument. The configuration file could be crafted by hand,
using the `docker/docker.yaml.template` as a base example, or it can be generated
using the `krake/scripts/krake_generate_config` script, which is used to generate all
Krake configuration files.

You can generate the minimal recommended configuration as follows:

.. code:: bash

    krake/scripts/krake_generate_config --dst docker docker/docker.yaml.template --api-host krake-api --etcd-host krake-db

The above command generates the `docker/docker.yaml` configuration file.
By applying it with the following command, the docker bundle for the target infrastructure will
be generated:

.. code:: bash

    # Configure corresponding docker bundle
    docker/generate --config docker/docker.yaml [docker/krake] [docker/prometheus] [docker/im]

The above command generates files needed for a target infrastructure launching
in the Docker environment. The result should at least be a `docker-compose.yaml` inside the
`docker/<infrastructure>` directory the previous commands were executed for.


Launch the infrastructure bundles
=================================

This section describes how you can apply the generated docker infrastructure bundles.
In order to launch the previously created infrastructure bundles, the following information need to be considered.

Krake
-----

The provided Krake infrastructure bundle launches the Krake DB and Krake API as well as all actively
maintained controllers. If you want to use any other controllers or don't want to actively use specific ones,
it is necessary to edit to previously created `docker-compose.yaml`.

Prerequisites
~~~~~~~~~~~~~

It is necessary, to provide a pre-built Krake image for the docker-compose file. You can build it as follows:

.. code:: bash

    # Get the latest version of Krake
    git clone https://gitlab.com/rak-n-rok/krake
    cd krake
    # Build and tag the Krake image
    docker build --tag krake:latest --file docker/krake/Dockerfile .

The configuration files for all Krake components need to be pre-generated as well, see `krake/README`.
You can generate the minimal recommended configuration as follows:

.. code:: bash

    sudo mkdir /etc/krake
    sudo $(id -u):$(id -g) /etc/krake/
    krake/scripts/krake_generate_config --dst /etc/krake templates/config/*.template templates/config/krakectl.yaml.template \
      --api-host krake-api --etcd-host krake-db --allow-anonymous \
      --static-authentication-enabled

Note: This documentation wants to be in sync with an Ansible playbook (see ansible directory) that
can be used for launching the Krake infrastructure as well. Therefore, the `/etc` directory is
used here, and if you use the standard Linux distro, you have to set the correct permissions.

Launch the Krake infrastructure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After generating the container image as well as the necessary configuration files, the infrastructure
can be launched as follows:

.. code:: bash

    docker-compose --file docker/krake/docker-compose.yaml up --detach

In order to test the new deployment, the Krake API should be tested.

.. code:: bash

    curl -s http://localhost:8080 | jq


Prometheus
----------

The Prometheus server is deployed in a minimal configuration suitable mostly for end-to-end testing
with the Krake infrastructure. The simple metrics exporter server exposes example heat demand metrics
in a minimal configuration, which can easily be incorporated into the Krake infrastructure.

The Metrics exporter generates random heat demand metrics for multiple zones;
the Default number of zones is 5: `heat_demand_zone_1` .. `heat_demand_zone_5`.
Random heat demand metric value is regenerated (each 10s) from an interval : <`zone_number` - 1, `zone_number`)

Launch the Prometheus infrastructure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Prometheus infrastructure can be launched as follows:

.. code:: bash

    docker-compose --file docker/prometheus/docker-compose.yaml up --detach

In order to test the new Prometheus server, a random provided value can be
queried. In this example, we go with `heat_demand_zone_3`:

.. code:: bash

    curl -s http://localhost:9090/api/v1/query?query=heat_demand_zone_3 | jq



Infrastructure Manager
======================

The Infrastructure Manager server is deployed in a minimal configuration suitable mostly for
end-to-end testing with the Krake infrastructure.

Launch the Infrastructure Manager server
----------------------------------------

The Infrastructure Manager can be launched as follows:

.. code:: bash

    docker-compose --file docker/im/docker-compose.yaml up --detach

To test it, it should be enough to retrieve the IM API version.

.. code:: bash

    curl -s http://localhost:8800/version


Launch all currently supported (Krake, Prometheus, IM) infrastructures
----------------------------------------------------------------------

Multiple infrastructure bundles can be executed in one docker network.
This allows for e.g. the Krake scheduler to communicate with the Prometheus
instance using the `localhost` network.
All infrastructures can be launched as follows:

.. code:: bash

    docker-compose --file docker/krake/docker-compose.yaml --file docker/prometheus/docker-compose.yaml up --file docker/im/docker-compose.yaml up --detach

.. _JINJA2: https://pypi.org/project/Jinja2/
.. _Prometheus: https://prometheus.io/
.. _InfrastructureManager: https://github.com/grycap/im
.. _docker: https://www.docker.com/
.. _dockercompose: https://docs.docker.com/compose/
