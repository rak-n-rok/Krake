import os
import yaml


def add_group_to_inventory(groupname, inventory):
    """Add a group into the Ansible inventory by adding it as a child of the
    "all" group

    Args:
        groupname (str): Name of the group
        inventory (dict): JSON representation of the Ansible inventory
    """

    if groupname not in inventory["all"]["children"]:
        inventory["all"]["children"][groupname] = {}


def add_child_to_group(child, groupname, inventory):
    """Add a child to an existing group in the Ansible inventory

    Args:
        child (str): Name of the child group
        groupname (str): Name of the parent group
        inventory (dict): JSON representation of the Ansible inventory

    """
    if "children" not in inventory["all"]["children"][groupname]:
        inventory["all"]["children"][groupname]["children"] = {child: {}}
    elif child not in inventory["all"]["children"][groupname]["children"]:
        inventory["all"]["children"][groupname]["children"][child] = {}


def add_host_to_group(hostname, groupname, inventory):
    """Add a host to a group in the Ansible inventory

    Args:
        hostname (str): Name of the host
        groupname (str): Name of the group
        inventory (dict): JSON representation of the Ansible inventory
    """

    # First "child"
    if "hosts" not in inventory["all"]["children"][groupname]:
        inventory["all"]["children"][groupname]["hosts"] = {hostname: {}}
    elif hostname not in inventory["all"]["children"][groupname]["hosts"]:
        inventory["all"]["children"][groupname]["hosts"][hostname] = {}


def add_group_vars(groupname, group_vars, ansible_dir):
    """Create the group vars file for a group

    Args:
        groupname (str): Name of the group
        group_vars (dict): JSON representation of the group_vars
        ansible_dir (str): Path to the ansible base directory
    """
    if group_vars:
        group_vars_path = os.path.join(ansible_dir, "group_vars", groupname)
        with open(group_vars_path, "w") as f:
            yaml.dump(group_vars, f)


def add_host_vars(hostname, host_vars, ansible_dir):
    """Create the host vars file for a host

    Args:
        hostname (str): Name of the host
        host_vars (dict): JSON representation of the host_vars
        ansible_dir (str): Path to the ansible base directory
    """
    if host_vars:
        host_vars_path = os.path.join(ansible_dir, "host_vars", hostname)
        with open(host_vars_path, "w") as f:
            yaml.dump(host_vars, f)


def remove_host_from_group(hostname, groupname, inventory):
    """Remove a host from a group in the Ansible inventory

    Args:
        hostname (str): Name of the host
        groupname (str): Name of the group
        inventory (dict): JSON representation of the Ansible inventory
    """
    try:
        del inventory["all"]["children"][groupname]["hosts"][hostname]
    except KeyError:
        print("host not present in group")
        # Allow host to have been already deleted
        pass


def remove_child_from_group(child, groupname, inventory):
    """Add a child group from a parent group in the Ansible inventory

    Args:
        child (str): Name of the child group
        groupname (str): Name of the parent group
        inventory (dict): JSON representation of the Ansible inventory
    """
    print("remove_child_from_group")
    print(child, groupname)

    try:
        del inventory["all"]["children"][groupname]["children"][child]
    except KeyError:
        print("child not present in group")
        # Allow host to have been already deleted
        pass


def remove_group_vars(groupname, ansible_dir):
    """Remove the group vars file of a group

    Args:
        groupname (str): Name of the group
        ansible_dir (str): Path to the ansible base directory
    """

    print("remove_group_vars")
    print(groupname)

    group_vars_path = os.path.join(ansible_dir, "group_vars", groupname)
    try:
        os.remove(group_vars_path)
    except FileNotFoundError:
        print("group_vars not found")
        pass


def remove_host_vars(hostname, ansible_dir):
    """Remove the host vars file of a host

    Args:
        hostname (str): Name of the host
        ansible_dir (str): Path to the ansible base directory
    """

    print("remove_host_vars")
    print(hostname)

    host_vars_path = os.path.join(ansible_dir, "host_vars", hostname)
    try:
        os.remove(host_vars_path)
    except FileNotFoundError:
        pass


def remove_group_from_inventory(groupname, inventory):
    """Remove a group from the Ansible inventory by removing it from the "all"
    group children

    Args:
        groupname (str): Name of the group
        inventory (dict): JSON representation of the Ansible inventory
    """

    try:
        del inventory["all"]["children"][groupname]
    except KeyError:
        print("group not found in inventory")
        # Allow group to have been already deleted
        pass


def is_group_empty(groupname, inventory):
    """Test is a group is empty by checking if it possessed children and/or hosts

    Args:
        groupname (str): Name of the group
        inventory (dict): JSON representation of the Ansible inventory
    """

    return (
        (groupname not in inventory["all"]["children"])
        or (
            "children" in inventory["all"]["children"][groupname]
            and not inventory["all"]["children"][groupname]["children"]
        )
        or (
            "hosts" in inventory["all"]["children"][groupname]
            and not inventory["all"]["children"][groupname]["hosts"]
        )
    )
