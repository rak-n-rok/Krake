# import pytest

# import os
import yaml

# from rak.__main__ import load_config
from rak.inventory import Inventory

from pathlib import Path
from tempfile import TemporaryDirectory


def test_add_group_to_inventory():

    yaml_inventory = {
        "all": {
            "children": {
                "mygroup1": {"hosts": {"myhost1": {}}, "children": {"mychild1": {}}}
            }
        }
    }

    with TemporaryDirectory() as tempdir:
        inventory_path = Path(tempdir) / "hosts"

        with inventory_path.open("w") as fd:
            yaml.dump(yaml_inventory, stream=fd)

        inventory = Inventory(inventory_path)

    existing_groupname = "mygroup1"
    nonexisting_groupname = "mygroup2"

    # Test adding a non existing group to the inventory
    inventory.add_group_to_inventory(nonexisting_groupname)

    assert nonexisting_groupname in inventory["all"]["children"]
    assert inventory["all"]["children"][nonexisting_groupname] == {}

    # Test if hosts and children are preserved
    inventory.add_group_to_inventory(existing_groupname)

    assert existing_groupname in inventory["all"]["children"]
    assert inventory["all"]["children"][existing_groupname] == {
        "hosts": {"myhost1": {}},
        "children": {"mychild1": {}},
    }


def test_remove_group_from_inventory():

    yaml_inventory = {
        "all": {
            "children": {
                "mygroup1": {"hosts": {"myhost1": {}}, "children": {"mychild1": {}}}
            }
        }
    }

    with TemporaryDirectory() as tempdir:
        inventory_path = Path(tempdir) / "hosts"

        with inventory_path.open("w") as fd:
            yaml.dump(yaml_inventory, stream=fd)

        inventory = Inventory(inventory_path)

    existing_groupname = "mygroup1"
    nonexisting_groupname = "mygroup2"

    # Test removing a non existing group from the inventory
    inventory.remove_group_from_inventory(nonexisting_groupname)

    assert nonexisting_groupname not in inventory["all"]["children"]

    # Test removing an existing group
    inventory.remove_group_from_inventory(existing_groupname)

    assert existing_groupname not in inventory["all"]["children"]


def test_add_child_to_group():

    yaml_inventory = {
        "all": {
            "children": {
                "mygroup1": {"hosts": {"myhost1": {}}, "children": {"mychild1": {}}}
            }
        }
    }

    with TemporaryDirectory() as tempdir:
        inventory_path = Path(tempdir) / "hosts"

        with inventory_path.open("w") as fd:
            yaml.dump(yaml_inventory, stream=fd)

        inventory = Inventory(inventory_path)

    parent_group = "mygroup1"
    existing_child = "mychild1"
    nonexisting_child = "mychild2"

    # Test adding a new child to a group
    inventory.add_child_to_group(parent_group, nonexisting_child)
    assert nonexisting_child in inventory["all"]["children"]["mygroup1"]["children"]
    assert inventory["all"]["children"]["mygroup1"]["children"][nonexisting_child] == {}

    # Test adding an already existing child to a group
    inventory.add_child_to_group(parent_group, existing_child)
    assert existing_child in inventory["all"]["children"]["mygroup1"]["children"]
    assert inventory["all"]["children"]["mygroup1"]["children"][existing_child] == {}


def test_remove_child_from_group():

    yaml_inventory = {
        "all": {
            "children": {
                "mygroup1": {"hosts": {"myhost1": {}}, "children": {"mychild1": {}}}
            }
        }
    }

    with TemporaryDirectory() as tempdir:
        inventory_path = Path(tempdir) / "hosts"

        with inventory_path.open("w") as fd:
            yaml.dump(yaml_inventory, stream=fd)

        inventory = Inventory(inventory_path)

    parent_group = "mygroup1"
    existing_child = "mychild1"
    nonexisting_child = "mychild2"

    # Test removing an existing child from a group
    inventory.remove_child_from_group(parent_group, nonexisting_child)
    assert nonexisting_child not in inventory["all"]["children"]["mygroup1"]["children"]

    # Test removing child not existing from a group
    inventory.remove_child_from_group(parent_group, existing_child)
    assert existing_child not in inventory["all"]["children"]["mygroup1"]["children"]


def test_add_host_to_group():

    yaml_inventory = {
        "all": {
            "children": {
                "mygroup1": {"hosts": {"myhost1": {}}, "children": {"mychild1": {}}}
            }
        }
    }

    with TemporaryDirectory() as tempdir:
        inventory_path = Path(tempdir) / "hosts"

        with inventory_path.open("w") as fd:
            yaml.dump(yaml_inventory, stream=fd)

        inventory = Inventory(inventory_path)

    parent_group = "mygroup1"
    existing_host = "myhost1"
    nonexisting_host = "myhost2"

    # Test adding a new child to a group
    inventory.add_host_to_group(parent_group, nonexisting_host)
    assert nonexisting_host in inventory["all"]["children"]["mygroup1"]["hosts"]
    assert inventory["all"]["children"]["mygroup1"]["hosts"][nonexisting_host] == {}

    # Test adding an already existing child to a group
    inventory.add_host_to_group(parent_group, existing_host)
    assert existing_host in inventory["all"]["children"]["mygroup1"]["hosts"]
    assert inventory["all"]["children"]["mygroup1"]["hosts"][existing_host] == {}


def test_remove_host_from_group():

    yaml_inventory = {
        "all": {
            "children": {
                "mygroup1": {"hosts": {"myhost1": {}}, "children": {"mychild1": {}}}
            }
        }
    }

    with TemporaryDirectory() as tempdir:
        inventory_path = Path(tempdir) / "hosts"

        with inventory_path.open("w") as fd:
            yaml.dump(yaml_inventory, stream=fd)

        inventory = Inventory(inventory_path)

    parent_group = "mygroup1"
    existing_host = "myhost1"
    nonexisting_host = "myhost2"

    # Test removing an existing child from a group
    inventory.remove_host_from_group(parent_group, nonexisting_host)
    assert nonexisting_host not in inventory["all"]["children"]["mygroup1"]["hosts"]

    # Test removing child not existing from a group
    inventory.remove_host_from_group(parent_group, existing_host)
    assert existing_host not in inventory["all"]["children"]["mygroup1"]["hosts"]
