.. _admin-variables:

=========
Variables
=========

This sections describes Krake Ansible variables definition. Variables are stored
in the **group_vars/** directory or directly in the inventory file **hosts.yml**.
Inventory file defines variables on global level or on a host group level (see :ref:`admin-inventory`).


Variables definition
====================

Krake Ansible variables stored in **group_vars/** directory are structured into files
where the filename matches the inventory host group name. Global variables common for
all inventory host groups are defined in **all.yml** variable file.
Following section describes files and variables used by Krake Ansible playbooks.

all.yml
    etc_dir
        The directory of JSON files which store inferred information from hosts by **krake_inventory** plugin

central_idps.yml
    keystone_port
        Central IdP keystone port
    secgroup_name
        Secure group name
    flavor
        Flavor manage the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address
    git_branch
        Krake branch name


devstack.yml
    prometheus_port
        Prometheus server port
    service_provider_port
        Prometheus clients port
    template_name
        Name of the default kubernetes cluster template
    cluster_keypair
        Name of the default keypair that is used to spawn kubernetes clusters via Magnum
    idp_name
        Central IdP name
    federated_domain_name
        Federated domain name
    federation_protocol_name
        Federation protocol name
    idp_mapping_name
        Central IdP mapping name
    flavor
        Flavor manage the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address
    git_branch
        Krake branch name

gateways.yml
    flavor
        Flavor manage the sizing for the compute, memory and storage capacity of the host

krake_apps.yml
    api_host
        OpenStack Heat template API name
    api_port
        OpenStack Heat template API port
    flavor
        Flavor manage the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address

magnum_clusters.yml
    prometheus_port
        Prometheus server port
    magnum_path
        Magnum path
    kube_api_config
        Path of kubernetes configuration file
    user_role
        Federated user role
    user_project
        Federated project name

minikube_clusters.yml
    api_port
        OpenStack Heat template api port
    minikube_install_dir
        Minikube installation directory path
    minikube_version
        Minikube version
    kubectl_version
        Kubectl version
    kube_api_config
        Kubectl api configuration file path
    minikube_path
        Minikube keystone path
    user_role
        Federated user role
    user_project
        Federated project name
    flavor
        Flavor manage the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address

prometheus.yml
    prometheus_admin_pass
        Prometheus server admin password
    grafana_admin_pass
        Grafana server admin password
    ports
        Prometheus server VM open ports
    flavor
        Flavor manage the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address
    git_branch
        Krake branch name
