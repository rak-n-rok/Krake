=====
TOSCA
=====

This section describes TOSCA integration to Krake.


Introduction
============

TOSCA_ is an OASIS standard language to describe a topology of cloud-based web services,
their components, relationships, and the processes that manage them.

TOSCA uses the concept of service templates to describe services.
TOSCA further provides a type system of types to describe the possible building blocks for
constructing service templates and relationship types to describe possible kinds of relations.
It is possible to create custom TOSCA types for building custom TOSCA templates.

Krake allows end-users to orchestrate Kubernetes applications by TOSCA. It is required
to use custom TOSCA templates for them. Krake supports Cloud Service
Archive (CSAR_) as well. CSAR_ is a container file using the ZIP file format_,
that includes all artifacts required to manage the lifecycle of the corresponding
cloud application using TOSCA language.

.. note::

  TOSCA technical committee has decided that any profile (template base)
  development should best be left to the community. It means, that there are not any
  "de facto standard" on how to describe e.g. Kubernetes applications by TOSCA.
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

    Krake uses tosca-parser_ library as an underlying TOSCA parser and validator.
    Currently, tosca-parser_ supports TOSCA-Simple-Profile-YAML_ ``v1.0`` or ``v1.2``,
    which reflects what is supported by Krake.


Another prerequisite (besides the TOSCA version) is a TOSCA profile (custom type).
Krake supports and can manage only Kubernetes application that is described by
``tosca.nodes.indigo.KubernetesObject`` custom type.

``tosca.nodes.indigo.KubernetesObject`` custom type has been defined by
Grycap_ research group. It could be imported as an external document using ``imports``
directive in the template or could be directly declared as a custom
data type within the ``data_types`` template section.

For import use the following reference to the Grycap's `custom types`_:

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

Cloud Service Archive
---------------------

CSAR_ should be in a defined format_. The specification allows to create CSAR with or without
the ``TOSCA.meta`` file. So let's create an example with TOSCA meta.
The ``TOSCA.meta`` file structure follows the exact same syntax as defined in the TOSCA 1.0 specification.
It is required to store this file in the ``TOSCA-Metadata`` directory. It is also required to
include the ``Entry-Definitions`` keyword pointing to a valid TOSCA definitions YAML file
that a TOSCA orchestrator should use as entry for parsing the contents of the overall CSAR file (let's use
the above ``tosca-example.yaml`` file in this example).


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


TOSCA Workflow
==============

The TOSCA template should be composed on the client side. Then the client sends the request
for the creation or updating application together with the TOSCA template or CSAR file. Krake API parses,
validates, and translates the TOSCA template or CSAR file (using Tosca Parser) to the plain Kubernetes manifests.
Those manifests are stored in the Krake DB together with the TOSCA template or CSAR filename.
Later, only the Kubernetes manifests are used when the application proceeds to the
other Krake's components like Scheduler or Kubernetes Application Controller.
The workflow of this process can be seen in the following figure:

.. figure:: /img/tosca_workflow.png

    TOSCA workflow in Krake


Examples
========

Prerequisites
-------------

Krake repository contains a bunch of useful examples. Clone it first as follows:

.. code:: bash

    git clone https://gitlab.com/rak-n-rok/krake.git
    cd krake

TOSCA template examples are located in ``rak/functionals`` directory. Visit the following TOSCA templates:

.. code:: bash

    $ cat rak/functionals/echo-demo-tosca.yaml
    $ cat rak/functionals/echo-demo-update-tosca.yaml


If you interested in CSAR, use the pre-defined ``TOSCA.meta`` file and create a CSAR file as follows:

.. code:: bash

    cd rak/functionals/
    zip echo-demo.csar -r TOSCA-Metadata/ echo-demo-tosca.yaml


Rok
~~~~

TOSCA template file or CSAR should be applied the same as Kubernetes manifest file
using the rok CLI, see :ref:`user/rok-documentation:Rok documentation`.

- Create an application described by the TOSCA template:

.. code:: bash

    rok kube app create -f rak/functionals/echo-demo-tosca.yaml echo-demo


- Alternatively, create an application described by the CSAR file:

.. code:: bash

    rok kube app create -f rak/functionals/echo-demo.csar echo-demo


- Update an application described by the TOSCA template:

.. code:: bash

    rok kube app update -f rak/functionals/echo-demo-update-tosca.yaml echo-demo

.. tip::

    Krake allows the creation of an application using e.g. plain Kubernetes manifest
    and then updating it using TOSCA or even updating it using CSAR. The same works
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
