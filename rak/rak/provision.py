from .profiles import Host, Group, Environment
from .stacks import create_or_update_stack, get_stack_outputs, delete_stack_by_name
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


GIT_DIR = "/home/mg/gitlab/krake/"
ANSIBLE_DIR = "ansible"


def unprovision_hosts(hostnames):

    print(f"Hosts to unprovision: {hostnames}")

    # Load hosts profiles
    print("1. Load hosts profiles")

    hosts = []
    groups = {}  # key: group name, value Group object
    environments = {}  # key: environment name, value Environment object
    for hostname in hostnames:
        print("**************")
        print(f"Loading profile for host: {hostname}")

        host = Host(hostname)

        # Create Group if not exist, link to Host
        if host.group_name not in groups:
            groups[host.group_name] = Group(host.group_name)

        host.group = groups[host.group_name]

        # Create Environment if not exist, link to Host
        if host.environment_name not in environments:
            environments[host.environment_name] = Environment(host.environment_name)

        host.environment = environments[host.environment_name]

        if host.host_type == "gateway":
            host.environment.gateway = host
            hosts.insert(0, host)
        else:
            hosts.append(host)

    #        print(host.variables)
    #        print(host.group.variables)
    #        print(host.environment.variables)

    inventory_file = "hosts.yaml"
    inventory_path = os.path.join(GIT_DIR, ANSIBLE_DIR, inventory_file)

    # Augment inventory = Add host to correct groups
    with open(inventory_path) as f:
        # data = yaml.load(f, Loader=yaml.FullLoader)
        inventory = yaml.load(f)

    for host in hosts:
        print("Unprovision host")
        print(host.name)
        # Delete Stacks
        delete_stack_by_name(host.name, allow_notfound=True)

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
        if is_group_empty(environment.name, inventory):
            print("environment found empty")
            # Remove environment from inventory
            remove_group_from_inventory(environment.name, inventory)
            # Remove environment vars
            remove_group_vars(environment.name)

    print(inventory)

    with open(inventory_path, "w") as f:
        yaml.dump(inventory, f)


def provision_hosts(hostnames):
    """Main function to provision a list of hosts

    The function is devided in 4 main pieces:
    1. Loading the host profiles
    2. Getting the environment information
    3. Provisioning the environment
    4. Provisioning the hosts

    Args:
        hostnames (list): List of hosts to provision

    """

    print(f"Hosts to provision: {hostnames}")

    # Load hosts profiles
    print("1. Load hosts profiles")

    hosts = []
    groups = {}  # key: group name, value Group object
    environments = {}  # key: environment name, value Environment object
    for hostname in hostnames:
        print("**************")
        print(f"Loading profile for host: {hostname}")

        host = Host(hostname)

        # Create Group if not exist, link to Host
        if host.group_name not in groups:
            groups[host.group_name] = Group(host.group_name)

        host.group = groups[host.group_name]

        # Create Environment if not exist, link to Host
        if host.environment_name not in environments:
            environments[host.environment_name] = Environment(host.environment_name)

        host.environment = environments[host.environment_name]

        if host.host_type == "gateway":
            host.environment.gateway = host
            hosts.insert(0, host)
        else:
            hosts.append(host)

    #         print(host.variables)
    #         print(host.group.variables)
    #         print(host.environment.variables)

    inventory_file = "hosts.yaml"
    inventory_path = os.path.join(GIT_DIR, ANSIBLE_DIR, inventory_file)
    # Augment inventory = Add host to correct groups
    with open(inventory_path) as f:
        # data = yaml.load(f, Loader=yaml.FullLoader)
        inventory = yaml.load(f)

    print("3. Provision networks")

    # Provision Network
    for environment in environments.values():
        print("**************")
        print(f"Provisioning network + secgroup for environment: {environment.name}")

        # Create Network + Common security group if not exist
        stack_parameters = {}
        try:
            stack_parameters = environment.generate_stack_parameters()
        except AttributeError:
            print("Profile incomplete")
            raise

        stack = create_or_update_stack(
            environment.name, "environment", stack_parameters, wait=True, interval=2
        )

        stack_outputs = get_stack_outputs(stack)
        add_group_to_inventory(environment.name, inventory)
        add_group_vars(environment.name, {**environment.variables, **stack_outputs})

    for group in groups.values():

        print("****")
        print(group.name)

        add_group_to_inventory(group.name, inventory)
        add_child_to_group(group.name, environment.name, inventory)
        # add_child_to_group(environment.name, group.host_type, inventory)
        add_child_to_group(group.name, group.host_type, inventory)
        add_group_vars(group.name, group.variables)

    print("4. Provision hosts")

    for host in hosts:
        print("**************")
        print(f"Provisioning host: {host.name}")

        # Launch host Stack
        stack_parameters = {}
        try:
            stack_parameters = host.generate_stack_parameters()
        except AttributeError:
            print("Profile incomplete")
            raise

        stack = create_or_update_stack(
            host.name,
            "virtualmachine",
            stack_parameters,
            wait=True,
            retry=60,
            interval=5,
        )

        host.stack_outputs = get_stack_outputs(stack)
        print(host.stack_outputs)

        host.ansible_variables = generate_ansible_variables(host)

        add_host_to_group(host.name, host.group.name, inventory)
        add_host_vars(host.name, host.host_vars)

    with open(inventory_path, "w") as f:
        yaml.dump(inventory, f)


def generate_ansible_variables(host):

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

        ansible_host = host.stack_outputs["private_ip"]
    else:
        ansible_ssh_common_args = (
            "-o StrictHostKeyChecking=No -o UserKnownHostsFile=/dev/null"
        )
        ansible_host = host.stack_outputs["public_ip"]

    ansible_variables = {
        "hostname": host.name,
        "ansible_host": ansible_host,
        "ansible_user": "ubuntu",
        "ansible_ssh_common_args": ansible_ssh_common_args,
        "ansible_ssh_private_key_file": host.full_profile["key_file"],
        "ansible_python_interpreter": "python3",
    }

    return ansible_variables
