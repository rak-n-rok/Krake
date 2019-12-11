from .profiles import Host, Group, Environment
from .stacks import (
    make_heat_client,
    create_or_update_stack,
    get_stack_outputs,
    delete_stack,
    get_stack_by_name,
    StackNotFound,
)
from .inventory import (
    add_group_to_inventory,
    add_child_to_group,
    add_host_to_group,
    add_group_vars,
    add_host_vars,
    remove_host_from_group,
    remove_host_vars,
    remove_child_from_group,
    remove_group_from_inventory,
    remove_group_vars,
    is_group_empty,
)

import os
import yaml

import logging

# import threading
# import time
# import concurrent.futures

from multiprocessing import Pool


format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")


def load_profiles(hostnames, profile_directory):
    hosts = {}  # key: host name, value Host object
    groups = {}  # key: group name, value Group object
    environments = {}  # key: environment name, value Environment object
    for hostname in hostnames:
        print("**************")
        print(f"Loading profile for host: {hostname}")

        host = Host(hostname, profile_directory)

        # Create Group if not exist, link to Host
        if host.group_name not in groups:
            groups[host.group_name] = Group(host.group_name, profile_directory)

        host.group = groups[host.group_name]

        # Create Environment if not exist, link to Host
        if host.environment_name not in environments:
            environments[host.environment_name] = Environment(
                host.environment_name, profile_directory
            )

        host.environment = environments[host.environment_name]
        host.group.environment = environments[host.environment_name]

        if host.host_type == "gateway":
            host.environment.gateway = host

        hosts[hostname] = host

    return sort_hosts(hosts), groups, environments


def sort_hosts(hosts):
    gateway_hosts = {}
    other_hosts = {}

    for host in hosts:
        if hosts[host].host_type == "gateway":
            gateway_hosts[host] = hosts[host]
        else:
            other_hosts[host] = hosts[host]

    return {**gateway_hosts, **other_hosts}


def provision_environment(environment, heat_client):
    logging.info(f"Thread: Started provisioning for {environment.name}")

    # Create Network + Common security group if not exist
    try:
        stack_parameters = environment.generate_stack_parameters()
    except AttributeError:
        print("Profile incomplete")
        raise

    if environment.name == "myenv2":
        raise AttributeError

    stack = create_or_update_stack(
        heat_client,
        environment.name,
        "environment",
        stack_parameters,
        wait=True,
        interval=2,
    )

    logging.info(f"Thread: Finished provisioning for {environment.name}")
    return get_stack_outputs(stack)


def add_environment_ansible(environment_name, group_vars, inventory, ansible_dir):
    add_group_to_inventory(environment_name, inventory)
    add_group_vars(environment_name, group_vars, ansible_dir)


def add_group_ansible(group, inventory, ansible_dir):

    add_group_to_inventory(group.name, inventory)
    add_child_to_group(group.name, group.environment.name, inventory)
    # add_child_to_group(environment.name, group.host_type, inventory)
    add_child_to_group(group.name, group.host_type, inventory)
    add_group_vars(group.name, group.variables, ansible_dir)


def provision_host(host):
    """Provision a Host on top of OpenStack using Heat

    Args:
        host (Host): Host to provision

    Returns:
        dict: The infrastructure variables, such as IP Addresses, which are created
            during the provisioning.

    Raises:
        AttributeError: if some required variables are not defined in the host profile.
    """

    try:
        stack_parameters = host.generate_stack_parameters()
    except AttributeError:
        print("Profile incomplete")
        raise

    stack = create_or_update_stack(
        host.name, "virtualmachine", stack_parameters, wait=True, retry=60, interval=5
    )

    return get_stack_outputs(stack)


def add_host_ansible(host, stack_outputs, inventory, ansible_dir):

    host_ansible_variables = generate_ansible_variables(host, stack_outputs)
    host_vars = generate_host_vars(
        host.variables, stack_outputs, host_ansible_variables
    )

    add_host_to_group(host.name, host.group.name, inventory)
    add_host_vars(host.name, host_vars, ansible_dir)


def provision(config, hostnames):
    """Main function to provision a list of hosts

    The function is devided in 4 main pieces:
    1. Loading of the hosts, group, and environment profiles
    2. Provisioning of the environments
    3. Provisioning of the hosts

    Args:
        config (dict): The rak configuration
        hostnames (list): List of hosts to provision
    """

    ansible_dir = config["ansible_directory"]
    profile_directory = config["profile_directory"]
    inventory_file = config["ansible_inventory_file"]

    print(f"Hosts to provision: {hostnames}")

    # Load profiles
    print("1. Load profiles")
    hosts, groups, environments = load_profiles(hostnames, profile_directory)

    inventory_path = os.path.join(ansible_dir, inventory_file)
    with open(inventory_path) as f:
        inventory = yaml.load(f, Loader=yaml.FullLoader)

    heat_client = make_heat_client()

    # Provision Environments
    # arg_list = [[environment, heat_client] for environment in environments.values()]

    with Pool(2) as p:
        # results = [p.apply_async(provision_environment, args=args) for args in
        # arg_list]
        results = [
            p.apply_async(provision_environment, args=[environment, heat_client])
            for environment in environments.values()
        ]
        p.close()
        p.join()

    for result in results:
        if result.successful():
            stack_outputs = result.get()
        else:
            # result.get()
            print("Not successful")

    return

    #     with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    #         logging.info("Provisioning environments")
    #         for environment in environments.values():
    #             logging.info(f"Provisioning {environment.name}")
    #             executor.submit(provision_environment, environment)
    #
    #     logging.info("Provisioning environment is done")

    for environment in environments.values():
        group_vars = {**environment.variables, **environment.stack_outputs}
        add_environment_ansible(environment.name, group_vars, inventory, ansible_dir)

    #     for environment in environments.values():
    #         stack_outputs = provision_environment(environment)
    #         add_environment_ansible(environment, stack_outputs, inventory,
    # ansible_dir)

    # Provision Groups
    for group in groups.values():
        add_group_ansible(group, inventory, ansible_dir)

    # Provision Hosts
    for host in hosts.values():
        stack_outputs = provision_host(host)
        add_host_ansible(host, stack_outputs, inventory, ansible_dir)

    with open(inventory_path, "w") as f:
        yaml.dump(inventory, f)


def generate_ansible_variables(host, stack_outputs):

    if host.full_profile["use_gateway"] and host is not host.environment.gateway:
        gateway = host.environment.gateway

        jump_host = (
            f"{gateway.ansible_variables['ansible_user']}@"
            f"{gateway.ansible_variables['ansible_host']}"
        )
        jump_key_file = gateway.ansible_variables["ansible_ssh_private_key_file"]

        ansible_ssh_common_args = (
            "-o StrictHostKeyChecking=No -o UserKnownHostsFile=/dev/null -o "
            "ProxyCommand='ssh -o StrictHostKeyChecking=No -o "
            f"UserKnownHostsFile=/dev/null -i {jump_key_file} -W %h:%p -q {jump_host}'"
        )

        ansible_host = stack_outputs["private_ip"]
    else:
        ansible_ssh_common_args = (
            "-o StrictHostKeyChecking=No -o UserKnownHostsFile=/dev/null"
        )
        ansible_host = stack_outputs["public_ip"]

    ansible_variables = {
        "hostname": host.name,
        "ansible_host": ansible_host,
        "ansible_user": "ubuntu",
        "ansible_ssh_common_args": ansible_ssh_common_args,
        "ansible_ssh_private_key_file": host.full_profile["key_file"],
        "ansible_python_interpreter": "python3",
    }

    return ansible_variables


def generate_host_vars(host_variables, stack_outputs, host_ansible_variables):
    """Generate the host_vars to write for an Ansible host.

    The host_vars are composed of:
    1. The host variables, i.e the variables loaded from the host profile.
    2. The stack output, i.e the infrastructure pieces which are created
    during host provisioning such as IP Addresses.
    3. The specific ansible variables for this host, i.e how ansible should
    communicate with this host, with which user, etc.

    They are loaded in the exact order. In case of similar keys, host
    variables are overwritten by the stack outputs, which are in turn
    overwritten by the specific ansible variables.

    Args:
        host_variables (dict): the host variables loaded from the host profile
        stack_outputs (dict): the output of the Heat Stack corresponding to
            this host
        host_ansible_variables (dict): the specific Ansible variables for this
            host

    Returns:
        dict: The host_vars to write for this host.

    """
    return {**host_variables, **stack_outputs, **host_ansible_variables}


def unprovision(config, hostnames):

    print(f"Hosts to unprovision: {hostnames}")

    ansible_dir = config["ansible_directory"]
    profile_directory = config["profile_directory"]
    inventory_file = config["ansible_inventory_file"]
    strict_stack_deletion = config["strict_stack_deletion"]

    # Load hosts profiles
    print("1. Load hosts profiles")

    hosts, groups, environments = load_profiles(hostnames, profile_directory)

    inventory_path = os.path.join(ansible_dir, inventory_file)

    # Augment inventory = Add host to correct groups
    with open(inventory_path) as f:
        # data = yaml.load(f, Loader=yaml.FullLoader)
        inventory = yaml.load(f)

    heat_client = make_heat_client()

    for host in hosts:
        print("Unprovision host")
        print(host.name)
        # Delete Stacks

        try:
            stack = get_stack_by_name(heat_client, host.name)
        except StackNotFound:
            if strict_stack_deletion:
                raise
        else:
            delete_stack(stack.id)

        # Remove hosts from groups
        remove_host_from_group(host.name, host.host_type, inventory)
        remove_host_from_group(host.name, host.group.name, inventory)

        # Delete host vars
        remove_host_vars(host.name)

    # Clean empty groups
    for group in groups.values():
        print("clean group")
        print(group.name)
        if is_group_empty(group.name, inventory):
            print("Group found empty")

            # Remove group from inventory
            remove_child_from_group(group.name, group.host_type, inventory)
            remove_child_from_group(group.name, group.environment_name, inventory)
            remove_group_from_inventory(group.name, inventory)

            # Remove group vars
            remove_group_vars(group.name)

    # Clean empty environments
    for environment in environments.values():
        print("Clean environment")
        print(environment.name)

        try:
            stack = get_stack_by_name(heat_client, environment.name)
        except StackNotFound:
            if strict_stack_deletion:
                raise
        else:
            delete_stack(stack.id, allow_notfound=True)

        if is_group_empty(environment.name, inventory):
            print("environment found empty")
            # Remove environment from inventory
            remove_group_from_inventory(environment.name, inventory)
            # Remove environment vars
            remove_group_vars(environment.name)

    print(inventory)

    with open(inventory_path, "w") as f:
        yaml.dump(inventory, f)
