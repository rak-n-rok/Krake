.. _admin-inventory:

=========
Inventory
=========

This sections describes the `Ansible <https://www.ansible.com/>`_ inventory of the Krake project.
Ansible works against multiple infrastructure hosts. Hosts are configured in an inventory
file **hosts.yml** which is a standard Ansible YAML inventory that uses `multiple groups <https://docs.ansible.com/ansible/latest/user_guide/intro_inventory.html#hosts-in-multiple-groups>`_ structure and a
custom **krake_inventory** plugin (see `auto plugin
<https://docs.ansible.com/ansible/latest/dev_guide/developing_inventory.html#the-auto-plugin>`_).


Inventory plugin
===================

The **krake_inventory** custom plugin loads the JSON file defined by variable
**hosts_file** and augments the host variables with dynamic variables
(e.g. public and private IP addresses) depending on host.
The location of JSON file which stores inferred information can be configured by
specifying the **hosts_file** variable in the **all** group .
If it is not specified it defaults to **.etc/<inventory-filestem>.json**.


Inventory structure
===================


Krake inventory file **hosts.yml** uses Ansible `multiple groups <https://docs.ansible.com/ansible/latest/user_guide/intro_inventory.html#hosts-in-multiple-groups>`_ structure
of inventory.

Global variables for all hosts are defined under the ``vars`` sub-section.
This sub-section defines following:

keypair
  OpenStack SSH key pair name of public ssh key which will be used for accessing the infrastructure to deploy hosts.
  Different keys could be defined directly for specific group or host.
key_file
  SSH private key file path on local computer for corresponding **keypair**. If **key_file** is set to null, the default SSH identity
  (~/.ssh/id_rsa) will be used.
gateway
  SSH jump host that is used to access the OpenStack instances. By
  default, no OpenStack server has a floating IP assigned except hosts in
  the **gateways** group. All other hosts use the **gateway** host variable to
  define a SSH jump host.

authorized_keys - optional
    List of additional authorized SSH keys, which can be used for accessing the hosts.

Each Krake infrastructure host is defined by corresponding host group sub-section in Krake inventory file.
The default parameters for every host group are defined in the **group_vars/**
directory where the filename matches the group name.
Krake inventory file defines following host groups and host variables:

gateways
 SSH jump host that is used to access the OpenStack instances.

    network
        Inventory name of the network on which this SSH jump host should be deployed
    vpn_cidr
        VPN Classless Inter-Domain Routing definition (e.g. 10.9.0.0/24)

networks
 Networks group define "virtual" hosts. These hosts exist purely for provisioning purpose. No machines are associated with them.

    subnet_name
        Subnet name
    subnet_cidr
        Subnet Classless Inter-Domain Routing definition (e.g. 192.168.0.0/24)
    public_network
        Public network type (e.g. shared-public-IPv4)
    router_name
        Router name
    common_secgroup_name
        Secure group name

central_idps
 Central IdP host group used for keystone federation of Krake infrastructure.

    network
        Inventory name of the network on which this IdP should be deployed

devstacks
 Devstack host group used for deployment of Krake devstack backends.

    id
        Unique DevStack ID. This ID is also used to define the IP network of the DevStack instance in the private network
    network
        Inventory name of the network on which this DevStack should be deployed
    idp
        Inventory name of the IdP that should be used for federation by this DevStack
    prometheus
        Inventory name of the Prometheus server that should be used for the monitoring of this DevStack backend

magnum_clusters
 Magnum cluster host group used for deployment of magnum clusters on underlying devstack backend.

    name
        Magnum cluster name
    devstack
        Inventory name of underlying devstack backend which hosted the magnum cluster deployment
    prometheus
        Inventory name of the Prometheus server that should be used for the monitoring of this magnum cluster
    use_keystone
        Enables keystone deployment on this magnum cluster

minikube_clusters
 Minikube cluster host group used for deployment of minikube clusters.

    name
        Minikube cluster name
    network
        Inventory name of the network on which this minikube cluster should be deployed
    idp
        Inventory name of the IdP that should be used for federation by this minikube
    use_keystone
        Enables keystone deployment on this minikube cluster

prometheus
 Prometheus host group used for deployment of Prometheus monitoring server.

    hostname
        Prometheus VM host name
    network
        Inventory name of the network on which this minikube cluster should be deployed

krake_apps
 Krake application host group used for deployment Krake infrastructure

    hostname
        Krake VM host name
    network
        Inventory name of the network on which this minikube cluster should be deployed
