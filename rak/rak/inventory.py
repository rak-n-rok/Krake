import os
import yaml


GIT_DIR = "/home/mg/gitlab/krake/"
ANSIBLE_DIR = "ansible"


def add_group_to_inventory(groupname, inventory):
    print(f"adding {groupname} to inv")

    if groupname not in inventory["all"]["children"]:
        inventory["all"]["children"][groupname] = {}


def add_child_to_group(child, groupname, inventory):
    if "children" not in inventory["all"]["children"][groupname]:
        inventory["all"]["children"][groupname]["children"] = {child: {}}
    elif child not in inventory["all"]["children"][groupname]["children"]:
        inventory["all"]["children"][groupname]["children"][child] = {}


def add_host_to_group(hostname, groupname, inventory):
    # First "child"
    if "hosts" not in inventory["all"]["children"][groupname]:
        inventory["all"]["children"][groupname]["hosts"] = {hostname: {}}
    elif hostname not in inventory["all"]["children"][groupname]["hosts"]:
        inventory["all"]["children"][groupname]["hosts"][hostname] = {}


def add_group_vars(groupname, group_vars):
    if group_vars:
        group_vars_path = os.path.join(GIT_DIR, ANSIBLE_DIR, "group_vars", groupname)
        with open(group_vars_path, "w") as f:
            yaml.dump(group_vars, f)


def add_host_vars(hostname, host_vars):
    if host_vars:
        host_vars_path = os.path.join(GIT_DIR, ANSIBLE_DIR, "host_vars", hostname)
        with open(host_vars_path, "w") as f:
            yaml.dump(host_vars, f)


def remove_host_from_group(hostname, groupname, inventory):

    print("remove_host_from_group")
    print(hostname, groupname)

    try:
        del inventory["all"]["children"][groupname]["hosts"][hostname]
    except KeyError:
        print("host not present in group")
        # Allow host to have been already deleted
        pass


def remove_child_from_group(child, groupname, inventory):

    print("remove_child_from_group")
    print(child, groupname)

    try:
        del inventory["all"]["children"][groupname]["children"][child]
    except KeyError:
        print("child not present in group")
        # Allow host to have been already deleted
        pass


def remove_group_vars(groupname):

    print("remove_group_vars")
    print(groupname)

    group_vars_path = os.path.join(GIT_DIR, ANSIBLE_DIR, "group_vars", groupname)
    try:
        os.remove(group_vars_path)
    except FileNotFoundError:
        print("group_vars not found")
        pass


def remove_host_vars(hostname):

    print("remove_host_vars")
    print(hostname)

    host_vars_path = os.path.join(GIT_DIR, ANSIBLE_DIR, "host_vars", hostname)
    try:
        os.remove(host_vars_path)
    except FileNotFoundError:
        pass


def remove_group_from_inventory(groupname, inventory):

    print("remove_group_from_inventory")
    print(groupname, inventory)

    try:
        del inventory["all"]["children"][groupname]
    except KeyError:
        print("group not found in inventory")
        # Allow host to have been already deleted
        pass


def is_group_empty(groupname, inventory):
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
