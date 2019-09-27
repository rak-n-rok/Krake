.. _admin-setup:

=========================
Set up Krake with Ansible
=========================

This sections describes prerequisites and deployment of a Krake infrastructure with `Ansible <https://www.ansible.com/>`_.


Prerequisites
===================

- `Ansible 2.7.x <https://docs.ansible.com/ansible/latest/roadmap/ROADMAP_2_7.html>`_ using a Python 3 interpreter
- `Docker <https://pypi.org/project/docker/>`_ Python module

It is suggested that Ansible is installed inside the virtualenv of Krake.

.. code::

	pip install ansible~=2.7.0 docker

Check the version and Python executable of the Ansible installation:

.. code::

	ansible --version

.. code::

  ansible 2.7.10
    config file = None
    configured module search path = ['/path/to/home/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
    ansible python module location = /path/to/virtualenv/lib/python3.6/site-packages/ansible
    executable location = /path/to/virtualenv/bin/ansible
    python version = 3.6.7 (default, Oct 22 2018, 11:32:17) [GCC 8.2.0]


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
