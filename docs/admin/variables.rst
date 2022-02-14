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
        Security group name
    flavor
        Flavor manages the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address
    git_branch
        Git branch name


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
        Flavor manages the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address
    git_branch
        Git branch name

gateways.yml
    flavor
        Flavor manage the sizing for the compute, memory and storage capacity of the host
    wireguard_port:
        Port on which the wireguard service will listen to on the gateway.

krake_apps.yml
    flavor
        Flavor manages the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address
    api_host
        OpenStack Heat template API name
    api_port
        OpenStack Heat template API port

    etcd_host (string)
        Name of the etcd container started using docker-compose.
    etcd_port (int)
        Port of the etcd cluster in the etcd container started using docker-compose.
    etcd_peer_port (int)
        Peer listening port of the etcd cluster in the etcd container started using docker-compose.

    api_host (string)
        Name of the Krake API container started using docker-compose.
    api_port (int)
        Port that can be used to reach the Krake API present in the container started using docker-compose.

    enable_tls (boolean)
        Enable or disable TLS support for communications with the API (for the API, controllers and Rok utility).
        The certificates need to be added manually into the ``/etc/krake`` directory in the Krake VM.

    worker_count (integer)
        On each Controller, amount of working units that will handle resources received concurrently.
    debounce (float)
        On each Controller, timeout (in seconds) for the worker queue before handing over a resource,
        to wait for an updated state.

    complete_hook_user (string)
        Name of the user for the "complete" hook.
    complete_hook_cert_dest (file path)
        Path inside the deployed Application where the certificate and its key will be
        stored (for the "complete" hook).
    complete_hook_env_token (string)
        Name of the environment variable that will contain the token in the deployed
        Application.
    complete_hook_env_url (string)
        Name of the environment variable that will contain the URL of the Krake API in
        the deployed Application.
    external_endpoint (URL, optional)
        URL of the Krake API that will be reachable for any deployed Application.
    use_private_ip (boolean)
        If set to True, and no external endpoint has been set, the URL for the external
        endpoint (see above) will be computed automatically, using the Krake API private
        IP, its port and the "http" or "https" scheme depending on the status of TLS on
        the Krake API (enabled or disabled).

    shutdown_hook_user (string)
        Name of the user for the "shutdown" hook.
    shutdown_hook_cert_dest (file path)
        Path inside the deployed Application where the certificate and its key will be
        stored (for the "complete" hook).
    shutdown_hook_env_token (string)
        Name of the environment variable that will contain the token in the deployed
        Application.
    shutdown_hook_env_url (string)
        Name of the environment variable that will contain the URL of the Krake API in
        the deployed Application.

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
        Flavor manages the sizing for the compute, memory and storage capacity of the host
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
        Flavor manages the sizing for the compute, memory and storage capacity of the host
    floating_ip
        Enables the use of public IP address
    git_branch
        Git branch name
