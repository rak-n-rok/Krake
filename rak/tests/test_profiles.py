import pytest
import os
import yaml

from rak.__main__ import load_config
from rak.profiles import InvalidHostname, InvalidGroupname, Host, Group
from rak.provision import load_profiles
from pathlib import Path
from tempfile import TemporaryDirectory


def test_parse_hostname():

    valid_hostnames = [
        "krake_myenv_01",  # krake host in the myenv environment
        "gateway_myenv_01",  # gateway host in the myenv environment
        "minikube_myenv_01",  # minikube host in the myenv environment
        "krake_myenv2_01",  # krake host in the myenv2 environment
        "krake_myenv_100",  # krake host number in the myenv environment
    ]
    invalid_hostnames = [
        "krake_myenv",  # Missing UID
        "krake_myenv_",  # Missing UID
        "krake_myenv_string",  # UID is a string
        "krake_myenv_01_additional",  # Contains an additional string
        "additional_krake_myenv_01",  # Contains an additional string
        "notatype_myenv_01"  # host type is not a known type
        "krake-myenv-01",  # Wrong delimiters
    ]

    for hostname in valid_hostnames:
        Host.parse_hostname(hostname)

    for hostname in invalid_hostnames:
        print(hostname)
        with pytest.raises(InvalidHostname):
            Host.parse_hostname(hostname)


def test_parse_groupname():
    valid_groupnames = ["krake_myenv", "gateway_myenv", "minikube_myenv"]

    invalid_groupnames = [
        "krake",  # Missing environment
        "krake_",  # Missing environment
        "krake_myenv_01",  # UID shouldn't be in the group name
        "notatype_myenv",  # host type is not a known type
        "krake-myenv",  # Wrong delimiters
    ]

    for groupname in valid_groupnames:
        Group.parse_groupname(groupname)

    for groupname in invalid_groupnames:
        print(groupname)
        with pytest.raises(InvalidGroupname):
            Group.parse_groupname(groupname)


def test_load_profiles():

    profile_all = {"key": "value1"}
    profile_krake = {"key": "value2"}
    profile_myenv_all = {"key": "value3"}
    profile_myenv_krake = {"key": "value4"}
    profile_myenv_krake_01 = {"key": "value5"}

    config = load_config()

    with TemporaryDirectory() as tempdir:

        config["profile_directory"] = Path(tempdir)

        os.mkdir(Path(tempdir) / "defaults")
        os.mkdir(Path(tempdir) / "myenv")
        os.mkdir(Path(tempdir) / "myenv" / "krake")

        profile_all_path = Path(tempdir) / "defaults" / "all.yaml"
        profile_krake_path = Path(tempdir) / "defaults" / "krake.yaml"
        profile_myenv_all_path = Path(tempdir) / "myenv" / "all.yaml"
        profile_myenv_krake_path = Path(tempdir) / "myenv" / "krake.yaml"
        profile_myenv_krake_01_path = Path(tempdir) / "myenv" / "krake" / "01.yaml"

        with profile_all_path.open("w") as fd:
            yaml.dump(profile_all, stream=fd)

        with profile_krake_path.open("w") as fd:
            yaml.dump(profile_krake, stream=fd)

        with profile_myenv_all_path.open("w") as fd:
            yaml.dump(profile_myenv_all, stream=fd)

        with profile_myenv_krake_path.open("w") as fd:
            yaml.dump(profile_myenv_krake, stream=fd)

        with profile_myenv_krake_01_path.open("w") as fd:
            yaml.dump(profile_myenv_krake_01, stream=fd)

        hostnames = [
            "krake_myenv_01",
            "krake_myenv_02",
            "gateway_myenv_01",
            "krake_myenv2_01",
            "gateway_myenv2_01",
        ]

        hosts, groups, environments = load_profiles(
            hostnames, config["profile_directory"]
        )
        assert hosts["krake_myenv_01"].full_profile["key"] == "value5"
        assert hosts["krake_myenv_02"].full_profile["key"] == "value4"
        assert hosts["gateway_myenv_01"].full_profile["key"] == "value3"
        assert hosts["krake_myenv2_01"].full_profile["key"] == "value2"
        assert hosts["gateway_myenv2_01"].full_profile["key"] == "value1"


def test_host_group_env_relationship():
    config = load_config()

    hostnames = ["krake_myenv_01"]

    hosts, groups, environments = load_profiles(hostnames, config["profile_directory"])

    assert hosts["krake_myenv_01"].environment.name == "myenv"
    assert hosts["krake_myenv_01"].group.name == "krake_myenv"
    assert groups["krake_myenv"].environment.name == "myenv"


def test_generate_environment_stack_parameters_success():

    profile_all = {
        "private_subnet_cidr": "192.168.0.0/24",
        "public_network_name": "public-network",
        "common_port_list": [
            {"protocol": "tcp", "port": "42"},
            {"protocol": "udp", "port": "99"},
        ],
    }

    config = load_config()

    with TemporaryDirectory() as tempdir:

        config["profile_directory"] = Path(tempdir)

        os.mkdir(Path(tempdir) / "defaults")
        profile_all_path = Path(tempdir) / "defaults" / "all.yaml"

        with profile_all_path.open("w") as fd:
            yaml.dump(profile_all, stream=fd)

        hostnames = ["krake_myenv_01"]

        hosts, groups, environments = load_profiles(
            hostnames, config["profile_directory"]
        )

        stack_parameters = environments["myenv"].generate_stack_parameters()

        assert stack_parameters["private_network_name"] == "krake-myenv-network"
        assert stack_parameters["private_subnet_name"] == "krake-myenv-subnet"
        assert stack_parameters["private_subnet_cidr"] == "192.168.0.0/24"
        assert stack_parameters["public_network_name"] == "public-network"
        assert stack_parameters["router_name"] == "krake-myenv-router"
        assert (
            stack_parameters["common_ports_secgroup_name"]
            == "krake-myenv-ports-commonsecgroup"
        )
        assert (
            stack_parameters["common_icmp_secgroup_name"]
            == "krake-myenv-icmp-commonsecgroup"
        )
        assert stack_parameters["secrule_ports"] == "42, 99"
        assert stack_parameters["secrule_protocols"] == "tcp, udp"


def test_generate_environment_stack_parameters_error():

    profile_all = {
        "private_subnet_cidr": "192.168.0.0/24",
        "common_port_list": [
            {"protocol": "tcp", "port": "42"},
            {"protocol": "udp", "port": "99"},
        ],
    }

    config = load_config()

    with TemporaryDirectory() as tempdir:

        config["profile_directory"] = Path(tempdir)

        os.mkdir(Path(tempdir) / "defaults")
        profile_all_path = Path(tempdir) / "defaults" / "all.yaml"

        with profile_all_path.open("w") as fd:
            yaml.dump(profile_all, stream=fd)

        hostnames = ["krake_myenv_01"]

        hosts, groups, environments = load_profiles(
            hostnames, config["profile_directory"]
        )

        with pytest.raises(KeyError):
            environments["myenv"].generate_stack_parameters()


def test_generate_host_stack_parameters_success():

    profile_all = {
        "public_network_name": "public-network",
        "public_keys": ["MySSHKey1", "MySSHKey2"],
        "flavor": "MyFlavor",
        "image": "MyImage",
        "create_floating_ip": "True",
        "OS_use_config_drive": "True",
        "allow_icmp": "True",
        "secrules": [
            {"protocol": "tcp", "port": "42"},
            {"protocol": "udp", "port": "99"},
        ],
    }

    config = load_config()

    with TemporaryDirectory() as tempdir:

        config["profile_directory"] = Path(tempdir)

        os.mkdir(Path(tempdir) / "defaults")
        profile_all_path = Path(tempdir) / "defaults" / "all.yaml"

        with profile_all_path.open("w") as fd:
            yaml.dump(profile_all, stream=fd)

        hostnames = ["krake_myenv_01"]

        hosts, groups, environments = load_profiles(
            hostnames, config["profile_directory"]
        )

        stack_parameters = hosts["krake_myenv_01"].generate_stack_parameters()

        assert stack_parameters["instance_name"] == "krake_myenv_01"
        assert stack_parameters["public_keys"] == ["MySSHKey1", "MySSHKey2"]
        assert stack_parameters["private_network_name"] == f"krake-myenv-network"
        assert stack_parameters["private_subnet_name"] == f"krake-myenv-subnet"
        assert stack_parameters["public_network_name"] == "public-network"
        assert (
            stack_parameters["common_ports_secgroup_name"]
            == f"krake-myenv-ports-commonsecgroup"
        )
        assert (
            stack_parameters["common_icmp_secgroup_name"]
            == f"krake-myenv-icmp-commonsecgroup"
        )
        assert stack_parameters["flavor"] == "MyFlavor"
        assert stack_parameters["image"] == "MyImage"
        assert stack_parameters["create_floating_ip"] == "True"
        assert stack_parameters["use_config_drive"] == "True"
        assert stack_parameters["allow_icmp"] == "True"
        assert stack_parameters["secrule_ports"] == "42, 99"
        assert stack_parameters["secrule_protocols"] == "tcp, udp"


def test_generate_host_stack_parameters_error():

    profile_all = {
        "public_network_name": "public-network",
        "public_keys": ["MySSHKey1", "MySSHKey2"],
        "flavor": "MyFlavor",
        "create_floating_ip": "True",
        "OS_use_config_drive": "True",
        "allow_icmp": "True",
        "secrules": [
            {"protocol": "tcp", "port": "42"},
            {"protocol": "udp", "port": "99"},
        ],
    }

    config = load_config()

    with TemporaryDirectory() as tempdir:

        config["profile_directory"] = Path(tempdir)

        os.mkdir(Path(tempdir) / "defaults")
        profile_all_path = Path(tempdir) / "defaults" / "all.yaml"

        with profile_all_path.open("w") as fd:
            yaml.dump(profile_all, stream=fd)

        hostnames = ["krake_myenv_01"]

        hosts, groups, environments = load_profiles(
            hostnames, config["profile_directory"]
        )

        with pytest.raises(KeyError, match="image"):
            hosts["krake_myenv_01"].generate_stack_parameters()
