=====
TOSCA
=====

This section describes TOSCA integration to Krake.


Introduction
============

TOSCA_ is an OASIS standard language to describe a topology of cloud-based web services,
their components, relationships, and the processes that manage them.

TOSCA uses the concept of service templates to describe services.
TOSCA further provides a system of types to describe the possible building blocks for
constructing service templates and relationship types to describe possible kinds of relations.
It is possible to create custom TOSCA types for building custom TOSCA templates.

Krake allows end-users to orchestrate Kubernetes applications with TOSCA. It is required
to use custom TOSCA templates for them. Krake supports Cloud Service
Archive (CSAR_) files as well. CSAR_ is a container file using the ZIP file format_,
that includes all artifacts required to manage the lifecycle of the corresponding
cloud application using the TOSCA language.

.. note::

  The TOSCA technical committee has decided that any profile (template base)
  development should be left to the community. It means, that there are not any
  "de facto standard" on how to describe e.g. Kubernetes applications with TOSCA.
  Each orchestrator that supports TOSCA is its own product with its own design paradigms
  and may have different assumptions and requirements for modeling applications.


TOSCA Template
==============

Krake is able to manage Kubernetes applications that are described by the TOSCA YAML custom
template file. Kubernetes application should be described by
TOSCA-Simple-Profile-YAML_ ``v1.0`` or ``v1.2`` as Krake only supports those versions.

Krake supports Cloud Service Archives (CSAR_) as well. The CSAR should contain
TOSCA-Simple-Profile-YAML_ ``v1.0`` or ``v1.2`` and should be in defined format_.

.. note::

  Krake uses the tosca-parser_ library as its underlying TOSCA parser and validator.
  Currently, tosca-parser_ supports the TOSCA-Simple-Profile-YAML_ ``v1.0`` or ``v1.2``,
  which reflects what is supported by Krake.

.. note::

  The Krake API could process TOSCA templates in two formats. It can receive
  the TOSCA template as serialized JSON or the API could receive a **URL** that points
  to some remote location, that provides a TOSCA template.
  In the case of providing a URL, the underlying tosca-parser_ library is able
  to (synchronously) download the TOSCA template from the defined URL
  and then parse and validate it.

Another prerequisite (besides the TOSCA version) is a TOSCA profile (custom type).
Krake supports and can manage only Kubernetes application that is described by the
``tosca.nodes.indigo.KubernetesObject`` custom type.

The ``tosca.nodes.indigo.KubernetesObject`` custom type has been defined by the
Grycap_ research group. It could be imported as an external document using the ``imports``
directive in the template or it can be directly declared as a custom
data type within the ``data_types`` template section.

For import use the following reference to Grycap's `custom types`_:

.. code:: yaml

    imports:
    - ec3_custom_types: https://raw.githubusercontent.com/grycap/ec3/tosca/tosca/custom_types.yaml

For direct definition use the following (minimal) data type:

.. code:: yaml

    data_types:
      tosca.nodes.indigo.KubernetesObject:
        derived_from: tosca.nodes.Root
        properties:
          spec:
            type: string
            description: The YAML description of the K8s object
            required: true

The ``spec`` of ``tosca.nodes.indigo.KubernetesObject`` custom type should contain
Kubernetes manifest as a string. It is possible to applied subset of supported `TOSCA functions`_
like:

  - get_property
  - get_input

The ``spec`` of the ``tosca.nodes.indigo.KubernetesObject`` custom type should contain a Kubernetes 
manifest as a string. It is possible to apply a subset of supported `TOSCA functions`_ like:

  - get_property
  - get_input
  - concat

Then, the example of TOSCA template for a single Kubernetes Pod could be designed as follows:

.. code:: yaml

    tosca_definitions_version: tosca_simple_yaml_1_0

    imports:
      - ec3_custom_types: https://raw.githubusercontent.com/grycap/ec3/tosca/tosca/custom_types.yaml

    description: TOSCA template for launching an example Pod by Krake

    topology_template:
      inputs:
        container_port:
          type: integer
          description: Container port
          default: 80
      node_templates:
        example-pod:
          type: tosca.nodes.indigo.KubernetesObject
          properties:
            spec:
              concat:
                - |-
                  apiVersion: v1
                  kind: Pod
                  metadata:
                    name: nginx
                  spec:
                    containers:
                    - name: nginx
                      image: nginx:1.14.2
                      ports:
                      - containerPort:
                - get_input: container_port

Let's save the definition above to the ``tosca-example.yaml`` file.

If you want to expose a created TOSCA template in your localhost, you can use a simple python HTTP server as follows:

.. code:: bash

    # TOSCA template will then be exposed on URL: `http://127.0.0.1:8000/tosca-example.yaml`
    python3 -m http.server 8000


Cloud Service Archive
---------------------

CSAR_ should be in a defined format_. The specification allows to create CSAR with or without
the ``TOSCA.meta`` file.
The ``TOSCA.meta`` file structure follows the exact same syntax as defined in the TOSCA 1.0 specification.
It is required to store this file in the ``TOSCA-Metadata`` directory. It is also required to
include the ``Entry-Definitions`` keyword pointing to a valid TOSCA definitions YAML file,
which should be used by a TOSCA orchestrator as an entrypoint for parsing the contents of the overall CSAR file 
(the previously created ``tosca-example.yaml`` file will be used in this example).

.. note::

  The Krake API can process CSAR files **only**, if they're defined as an **URL**.
  It means, that CSAR should be created and then exposed in some remote location.
  Then, the underlying tosca-parser_ library is able to (synchronously)
  download the CSAR archive from the defined URL and afterwards parse and validate it.

.. code:: bash

  # Create TOSCA-Metadata directory
  mkdir TOSCA-Metadata
  # Create and fill TOSCA.meta file
  echo "TOSCA-Meta-File-Version: 1.0" >> TOSCA-Metadata/TOSCA.meta
  echo "CSAR-Version: 1.1" >> TOSCA-Metadata/TOSCA.meta
  echo "Created-By: Krake" >> TOSCA-Metadata/TOSCA.meta
  echo "Entry-Definitions: tosca-example.yaml" >> TOSCA-Metadata/TOSCA.meta
  # Create CSAR
  zip example.csar -r TOSCA-Metadata/ tosca-example.yaml

  # Expose the created CSAR by simple HTTP python server
  # CSAR will be then exposed on URL: `http://127.0.0.1:8000/example.csar`
  # Expose the created CSAR file with a simple HTTP python server
  # CSAR will then be exposed on URL: `http://127.0.0.1:8000/example.csar`
  python3 -m http.server 8000


TOSCA Workflow
==============

The TOSCA template or CSAR archive should be composed on the client side. Then the client sends the request
for the creation or update of an application together with the TOSCA template (YAML file or URL) or CSAR URL.
The Krake API validates the TOSCA template or CSAR file suffixes depending on the used URL.
When the TOSCA template is defined with a YAML file, parsing and validation are performed by Krake API 
(using the tosca-parser_).
After validation, the life cycle of the application is the same as a regular one (defined by Kubernetes
manifest) except for the translation of the TOSCA template or CSAR archive into a Kubernetes manifest 
inside of the Kubernetes Application Controller.
The controller is responsible for the translation of TOSCA/CSAR to Kubernetes manifests. 
During this process, the application will in the **TRANSLATING** state.

The workflow of this process can be seen in the following figure:

.. figure:: /img/tosca_workflow.png

    TOSCA/CSAR workflow in Krake


Examples
========

Prerequisites
-------------

The Krake repository contains a bunch of useful examples. Clone it first with the following commands:

.. code:: bash

    git clone https://gitlab.com/rak-n-rok/krake.git
    cd krake

TOSCA template examples are located in the ``rak/functionals`` directory. View these TOSCA templates for example:

.. code:: bash

    $ cat rak/functionals/echo-demo-tosca.yaml
    $ cat rak/functionals/echo-demo-update-tosca.yaml

If you want to expose a created TOSCA template via some URL, you can use a simple python HTTP server as follows:

.. code:: bash

    cd rak/functionals/
    # Expose the TOSCA template examples with a simple HTTP python server
    # TOSCA template examples will then be exposed on URLs:
    # - `http://127.0.0.1:8000/echo-demo-tosca.yaml`
    # - `http://127.0.0.1:8000/echo-demo-update-tosca.yaml`
    python3 -m http.server 8000


If you are interested in CSAR, use the pre-defined ``TOSCA.meta`` file and create and expose CSAR archive as follows:

.. code:: bash

    cd rak/functionals/
    zip echo-demo.csar -r TOSCA-Metadata/ echo-demo-tosca.yaml
    # Expose the created CSAR by simple HTTP python server
    # CSAR will be then exposed on URL: `http://127.0.0.1:8000/example.csar`
    python3 -m http.server 8000


Rok
~~~

A TOSCA template YAML file should be applied the same way as a Kubernetes manifest file
using the rok CLI, see :ref:`user/rok-documentation:Rok documentation`.

- Create an application described by a TOSCA template YAML file:

.. code:: bash

    rok kube app create --file rak/functionals/echo-demo-tosca.yaml echo-demo

- Update an application described by a TOSCA template:

.. code:: bash

    rok kube app update --file rak/functionals/echo-demo-update-tosca.yaml echo-demo

A TOSCA template URL or CSAR archive URL should be defined after the optional `--url` argument
using the rok CLI, see :ref:`user/rok-documentation:Rok documentation`.

- Create an application described by a TOSCA template URL:

.. code:: bash

    rok kube app create --url http://127.0.0.1:8000/echo-demo-tosca.yaml echo-demo

- Update an application described by a TOSCA template URL:

.. code:: bash

    rok kube app update --url http://127.0.0.1:8000/echo-demo-update-tosca.yaml echo-demo

- Alternatively, create an application described by a CSAR URL:

.. code:: bash

    rok kube app create --url http://127.0.0.1:8000/example.csar echo-demo

.. tip::

  Krake allows the creation of an application using e.g. a plain Kubernetes manifest
  and then updating it with a TOSCA or even CSAR file. The same works
  vice-versa. It means, that the application could be created and then updated by
  any supported format (Kubernetes manifest, TOSCA, CSAR).


.. _TOSCA: https://www.oasis-open.org/committees/tc_home.php?wg_abbrev=tosca
.. _custom types: https://raw.githubusercontent.com/grycap/ec3/tosca/tosca/custom_types.yaml
.. _Grycap: https://github.com/grycap
.. _CSAR: https://www.oasis-open.org/committees/download.php/46057/CSAR%20V0-1.docx
.. _format: https://docs.oasis-open.org/tosca/TOSCA-Simple-Profile-YAML/v1.2/os/TOSCA-Simple-Profile-YAML-v1.2-os.html#_Toc528072959
.. _TOSCA-Simple-Profile-YAML: https://docs.oasis-open.org/tosca/TOSCA-Simple-Profile-YAML/
.. _tosca-parser: https://github.com/openstack/tosca-parser
.. _TOSCA functions: http://docs.oasis-open.org/tosca/TOSCA-Simple-Profile-YAML/v1.0/csd05/TOSCA-Simple-Profile-YAML-v1.0-csd05.html
