========================
Infrastructure providers
========================

Goal: Demonstrate the use of an OpenStack based cloud backend for Krake. Krake uses the IM_ (Infrastructure Manager) provider as a backend for spawning a Kubernetes cluster. A Kubernetes cluster is then automatically registered in Krake and could be used for the application deployment.

This is an advanced user scenario where the user should register the existing infrastructure provider backend (IM)
as well as an existing IaaS cloud deployment (OpenStack) before the actual cluster creation. The user is navigated to
register those resources to Krake. Please read the brief overview of Krake’s infrastructure provider and cloud
resources below:

Krake resources called **GlobalInfrastructureProvider** and **InfrastructureProvider** correspond
to an infrastructure provider backend, that is able to deploy infrastructures (e.g. Virtual machines,
Kubernetes clusters, etc.) on IaaS cloud deployments (e.g. OpenStack, AWS, etc.).
Krake currently supports IM_ (Infrastructure Manager) as an infrastructure provider backend.

Krake resources called **GlobalCloud** and **Cloud** correspond
to an IaaS cloud deployment (e.g. OpenStack, AWS, etc.) that will be managed
by the infrastructure provider backend. GlobalCloud and Cloud resources
could contain also metrics and labels, that could be used in Cluster scheduling.
Krake currently supports OpenStack_ as a GlobalCloud or Cloud backend.

.. note::

    The `global` resource (e.g. GlobalInfrastructureProvider, GlobalCloud) is a
    non-namespaced resource that could be used by any (even namespaced) Krake
    resource. For example, the GlobalCloud resource could be used by any Cluster
    which needs to be scheduled to some cloud.


.. note::

    Note that file paths mentioned in this tutorial are relative to the root of the Krake repository.


Preparation
===========

Launch the IM_ infrastructure provider instance using the support script.
Please note that the IM_ instance is launched in the docker environment, therefore it is mandatory to install docker_ beforehand.

.. prompt:: bash $ auto

    support/im

.. warning::

    The above support script launches the IM_ as is described in the `IM quick start`_ tutorial, hence with the default
    configuration and in a non-productive way. Please visit the `IM documentation`_ for further information about how to
    configure, launch and interact with the IM_ software.


Register an existing infrastructure provider to Krake
=====================================================

IM_ service ``username`` and ``password`` could be arbitrary.
The ``username`` and ``password`` are used for userspace definition.
It means, that anyone can talk with IM_ but can see only their own userspace.

.. prompt:: bash $ auto

    krakectl infra provider register --type im --url http://localhost:8800 --username test --password test im-provider


Register an existing OpenStack based cloud to Krake
===================================================

Gather information about your OpenStack project from ``openrc`` file:

  - Insert the ``OS_AUTH_URL`` value (without path) to the ``--url`` argument, e.g. `https://identity.cloud.com:5000`
  - Insert the ``OS_PROJECT_NAME`` value to the ``--project`` argument
  - Insert the ``OS_USERNAME`` value to the ``--username`` argument
  - Insert the ``OS_PASSWORD`` value to the ``--password`` argument

Use the already registered infrastructure provider called ``im-provider`` as an infrastructure provider for your OpenStack cloud.

.. note::

    If you want to use the C&H F1A OpenStack cloud, please note that it does not assign public IPs to the VMs. C&H F1A requires a private network for all VMs.
    This private network is connected to the public one via a router. The router should be created beforehand as the IM
    provider is not able to do this. You can create the requested router in your C&H F1A OpenStack cloud project as follows:

    .. prompt:: bash $ auto

        openstack router create --external-gateway shared-public-IPv4 public_router


.. prompt:: bash $ auto

    krakectl infra cloud register --type openstack --url <os-auth-url> --project <os-project-name> --username <os-username> --password <os-password> --infra-provider im-provider os-cloud


Create a Cluster
================

.. prompt:: bash $ auto

    krakectl kube cluster list  # No Cluster resource is present
    krakectl kube cluster create -f rak/functionals/im-cluster.yaml my-cluster
    krakectl kube cluster list  # One Cluster resource with name "my-cluster"

The creation of the cluster can take up to 15 minutes to complete. Observe that Kubernetes Cluster is created.

.. prompt:: bash $ auto

    krakectl kube cluster list

Spawn the demo application
==========================

Create the demo Kubernetes Application and observe the resource status.

.. prompt:: bash $ auto

    krakectl kube app create -f templates/applications/k8s/echo-demo.yaml echo-demo
    krakectl kube app get echo-demo  # See "running_on"

Cleanup
=======

Delete the Cluster, the Cloud and the InfrastructureProvider:

.. prompt:: bash $ auto

    krakectl kube cluster delete my-cluster
    krakectl infra cloud delete os-cloud
    krakectl infra provider delete im-provider


.. _IM: https://github.com/grycap/im
.. _IM quick start: https://imdocs.readthedocs.io/en/latest/gstarted.html
.. _IM documentation: https://imdocs.readthedocs.io/en/latest/
.. _OpenStack: https://www.openstack.org/
.. _docker: https://docs.docker.com/get-docker/
