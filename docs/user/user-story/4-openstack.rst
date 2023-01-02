==================
OpenStack backends
==================

.. warning::

    Due to stability and development issues on the side of Magnum, this feature isn't actively developed anymore.


Goal: Demonstrate the use of an OpenStack project as a backend for Krake

.. note::

    Krake supports different kind of backends. In the previous example, we used a Kubernetes cluster (deployed in a single VM via Minikube). In this scenario, we register an existing OpenStack project.

Register an existing OpenStack project to Krake
===============================================

- Gather information about your OpenStack project, for example:

.. prompt:: bash ubuntu@myworkstation:~$ auto

    ubuntu@myworkstation:~$ openstack coe cluster template list # Get Template ID
    ubuntu@myworkstation:~$ openstack project show my_openstack_project # Get Project ID
    ubuntu@myworkstation:~$ openstack user show my_user # Get User ID
    ubuntu@myworkstation:~$ grep OS_AUTH_URL ~/openrc # Get Keystone auth URL

- Create a OpenStack ``Project`` resource in Krake:

.. prompt:: bash $ auto

    $ rok os project create --template 728f024e-8a88-4971-b79f-151da123f363 --project-id 5bc3bab620bd48b0b9b425ee492050ea --password "password" --user-id 737bbcd2ce264d2fa32fa306ac84e97d --auth-url https://identity.myopenstack.com:5000/v3 myproject

Create a ``MagnumCluster``
==========================

.. prompt:: bash $ auto

    $ rok os cluster list  # No Cluster resource is present
    $ rok os cluster create mycluster
    $ rok os cluster list  # One Cluster resource with name "mycluster"

.. note::

    The creation of the Magnum cluster can take up to 10 minutes to complete.

- Observe that one Kubernetes ``Cluster`` is created in association to the ``MagnumCluster``.

.. prompt:: bash $ auto

    $ rok kube cluster list

Spawn the demo application
==========================

- Create the demo Kubernetes ``Application`` and observe the resource status.

.. prompt:: bash $ auto

    $ rok kube app create -f git/krake/rak/functionals/echo-demo.yaml echo-demo
    $ rok kube app get echo-demo  # See "running_on"

Cleanup
=======

- Delete the ``echo-demo`` Kubernetes ``Application`` and the OpenStack ``Project``

.. prompt:: bash $ auto

    $ rok kube app delete echo-demo
    $ rok kube os cluster delete mycluster
    $ rok kube project delete myproject
