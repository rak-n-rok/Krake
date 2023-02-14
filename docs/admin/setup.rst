.. _admin-setup:

=========================
Set up Krake with Ansible
=========================

This sections describes prerequisites and deployment of a Krake infrastructure with `Ansible <https://www.ansible.com/>`_.


Prerequisites
===================

- `Ansible 2.9.x <https://docs.ansible.com/ansible/latest/roadmap/ROADMAP_2_9.html>`_ or superior using a Python 3 interpreter
- `The full Openstack client <https://pypi.org/project/openstackclient/>`_ python module
- `Docker <https://pypi.org/project/docker/>`_ Python module

It is suggested that Ansible is installed inside the virtualenv of Krake.

.. code::

    pip install --editable "krake/[ansible]"

Check the version and Python executable of the Ansible installation:

.. code::

    ansible --version

.. code::

  ansible 2.9.2
    config file = None
    configured module search path = ['/path/to/home/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
    ansible python module location = /path/to/virtualenv/lib/python3.6/site-packages/ansible
    executable location = /path/to/virtualenv/bin/ansible
    python version = 3.6.8 (default, Oct  7 2019, 12:59:55) [GCC 8.3.0]

Before any infrastructure can be deployed, the necessary Ansible collections need to be
installed first:

.. code::

    ansible-galaxy install -r ansible/requirements.yml



Krake infrastructure deployment
===============================

The Krake infrastructure is provisioned by a set of Ansible playbooks.
The infrastructure is split into multiple separate OpenStack Heat stacks.
Every Heat stack is provisioned by its own Ansible playbook. The complete infrastructure
can be created by the top-level **site.yml** playbook.

Krake YAML inventory file **hosts.yml** needs to be created. Use the example file and
adjust it. The only parameter that needs to be modified is the **keypair**
variable. It should name an existing OpenStack **keypair**. If the corresponding
key file is not **~/.ssh/id_rsa** specify it in the **key_file** parameter.

It is assumed that environmental variables for authentication
against OpenStack project exist. They can be set by sourcing the OpenStack RC
file.

.. code::

    cd ansible/
    cp hosts.yml.example hosts.yml
    # Get list of all existing OpenStack keypairs
    openstack keypair list

The complete infrastructure can be created by the top-level **site.yml** playbook.

.. code::

    ansible-playbook -i hosts.yml site.yml


Each infrastructure component can by created separately by corresponding
ansible playbook e.g. the Krake application infrastructure can be created by Krake playbook.

.. code::

    ansible-playbook -i hosts.yml krake.yml

Table of available playbooks:

+--------------------------------+----------------------+
| Krake Infrastructure component | Playbook name        |
+================================+======================+
| Top-level playbook             | site.yml             |
+--------------------------------+----------------------+
| Krake application              | krake.yml            |
+--------------------------------+----------------------+
| Central IdP instance           | central_idp.yml      |
+--------------------------------+----------------------+
| Devstack instance              | devstack.yml         |
+--------------------------------+----------------------+
| Gateway SSH jump host          | gateway.yml          |
+--------------------------------+----------------------+
| Network "virtual" host         | network.yml          |
+--------------------------------+----------------------+
| Prometheus server instance     | prometheus.yml       |
+--------------------------------+----------------------+
| Minikube cluster               | minikube_cluster.yml |
+--------------------------------+----------------------+
| Magnum cluster                 | magnum_cluster.yml   |
+--------------------------------+----------------------+


Krake Ansible directory structure
=================================
Ansible related-files are stored in the **ansible/** directory of the repository.
Each sub-directory groups files based on Ansible best practices recommendations.

+-----------------------+------------------------------------------------------+
| Sub-directory / File  | Description                                          |
+=======================+======================================================+
| ansible.cfg           | Local Ansible configuration                          |
+-----------------------+------------------------------------------------------+
| hosts.yml             | Krake YAML inventory file                            |
+-----------------------+------------------------------------------------------+
| plugins/              | Custom Ansible plugins                               |
+-----------------------+------------------------------------------------------+
| files/                | Heat stack templates and files                       |
+-----------------------+------------------------------------------------------+
| plugins/              | Custom Ansible plugins                               |
+-----------------------+------------------------------------------------------+
| group_vars/           | Ansible group variables used as default values       |
+-----------------------+------------------------------------------------------+
| roles/                | Files for reusable Ansible roles                     |
+-----------------------+------------------------------------------------------+
| utils/                | Krake Ansible helper scripts                         |
+-----------------------+------------------------------------------------------+


Access through the gateway
==========================

To compartmentalize the infrastructure, all machines deployed by Krake are present on
the same OpenStack private network. Only the gateway is associated with a floating IP
and can thus be accessed externally. All other machines can be reached through the
gateway.

To simplify this process, the wireguard_ VPN is installed on the gateway when deployed.
After the deployment, for each wireguard peer set for the gateway in the host file (see
:ref:`admin/inventory:Inventory structure`), a wireguard configuration file is created
in the etc directory where the inventory files are created (``ansible/.etc`` by
default). The files names have the following syntax: ``wg_<peer_name>.conf``.

To use this file you have to:

    0. install wireguard locally. If you are using Ubuntu, you can use the following command:

        .. code::

            $ sudo apt install wireguard

    1. generate a wireguard key:

        .. code::

            $ umask 077
            $ wg genkey > privatekey
            $ wg pubkey < privatekey > publickey


        2.1 open the ``wg_<peer_name>.conf`` and change the ``REPLACEME`` placeholder with the private key that corresponds to the peer.


        2.2 Use SSH to connect to the ``krake-gateway-server``. Check the gateway server and if necessary adjust to accommodate the correct wireguard keys. Replace the ``REPLACEME`` placeholder with the public key. You can find the public key in the directory under ``/etc/wireguard`` :

            .. code::

                [Interface]
                PrivateKey = <INSERT_PRIVATE_WIREGUARD_KEY>
                Address = 10.9.0.1

                [Peer]
                PublicKey = <INSERT_PUBLIC_KEY_FROM_GATEWAY_SERVER>

               Endpoint = 185.128.119.165:51820
               AllowedIPs = 10.9.0.0/24, 192.168.0.0/24



    3. bring the wireguard interface up by using:

        .. code::

            $ wg-quick up <path_to_file>/wg_<peer_name>.conf

            # Example:
            $ wg-quick up ansible/.etc/wg_my-peer.conf

    4. you can now SSH into the other machines on the private network:

        .. code::

            $ ssh ubuntu@<krake_VM_private_ip>


The wireguard interface can be brought down by using:

.. code:: bash

    $ wg-quick down <path_to_file>/wg_<peer_name>.conf

    # Example:
    $ wg-quick down ansible/.etc/wg_my-peer.conf


.. important::

    If several Krake deployments are managed from a single machine, the peer names
    should have a different value, to avoid conflicts with the wireguard network
    interfaces.

    If several network interfaces are up at the same time, then the Krake private
    networks should not overlap. So if one has for instance the CIDR ``192.168.0.0/24``,
    another deployment should use something independent, such as ``192.168.1.0/24``.


.. _wireguard: https://www.wireguard.com/
