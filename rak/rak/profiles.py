import os
import yaml

from dataclasses import MISSING

# from typing import NamedTuple

# Directory structure definition
# GIT_DIR = "/home/mg/gitlab/krake"
# RAK_DIR = "rak/rak"
PROFILE_DIRECTORY = "profiles"
DEFAULT_PROFILES_DIRECTORY = "defaults"
current_dir = os.path.dirname(os.path.realpath(__file__))


class InvalidHostname(Exception):
    pass


class SubProfile(object):
    def __init__(self, name):
        self.name = name
        self._variables = MISSING

    @property
    def variables(self):
        if self._variables is not MISSING:
            return self._variables

        self._variables = {}
        for file in self.files_to_load():
            try:
                with open(file) as f:
                    # data = yaml.load(f, Loader=yaml.FullLoader)
                    vars_to_add = yaml.load(f)
            except FileNotFoundError:
                print(f"File {file} couldn't be found")
                pass
            else:
                self._variables.update(vars_to_add)

        return self._variables

    def files_to_load(self):
        raise NotImplementedError


class Environment(SubProfile):
    def __init__(self, name):
        super().__init__(name)

        self.private_network_name = f"krake-{self.name}-network"
        self.private_subnet_name = f"krake-{self.name}-subnet"
        self.router_name = f"krake-{self.name}-router"
        self.common_ports_secgroup_name = f"krake-{self.name}-ports-commonsecgroup"
        self.common_icmp_secgroup_name = f"krake-{self.name}-icmp-commonsecgroup"

        self.gateway = None

    @property
    def private_subnet_cidr(self):
        return self.variables["private_subnet_cidr"]

    @property
    def public_network_name(self):
        return self.variables["public_network_name"]

    def files_to_load(self):

        files_to_load = [
            os.path.join(
                current_dir, PROFILE_DIRECTORY, DEFAULT_PROFILES_DIRECTORY, "all.yaml"
            ),
            os.path.join(current_dir, PROFILE_DIRECTORY, self.name, "all.yaml"),
        ]

        return files_to_load

    def generate_stack_parameters(self):

        """From the environment variables, format a parameter dictionary to
        use during Heat Stack creation or update

        Args:
            host (Host): The Host which will be provision or updated.

        Returns:
            dict: a valid parameter dictionary to use for the Heat stack
            creation or update

        """

        stack_parameters = {
            "private_network_name": self.private_network_name,
            "private_subnet_name": self.private_subnet_name,
            "private_subnet_cidr": self.private_subnet_cidr,
            "public_network_name": self.public_network_name,
            "router_name": self.router_name,
            "common_ports_secgroup_name": self.common_ports_secgroup_name,
            "common_icmp_secgroup_name": self.common_icmp_secgroup_name,
        }

        # The Heat templating language doesn't allow complex data structure
        # neither complex looping. We have to format the security_rule
        # dictionary and pass two lists to the Heat stacks: one for the list
        # of ports, and one for the list of corresponding protocol. Order
        # matters i.e. element X of port_list has to correspond to element X
        # of protocol_list. See the Heat reference:
        # https://docs.openstack.org/heat/latest/template_guide/hot_spec.html#repeat
        port_list = []
        protocol_list = []
        for security_rule in self.variables["common_port_list"]:
            port_list.append(security_rule["port"])
            protocol_list.append(security_rule["protocol"])

        stack_parameters["secrule_ports"] = ", ".join(map(str, port_list))
        stack_parameters["secrule_protocols"] = ", ".join(protocol_list)

        return stack_parameters


class Group(SubProfile):
    def __init__(self, name):
        super().__init__(name)
        (host_type, environment_name) = name.split("_")
        self.host_type = host_type  # krake, minikube, gateway
        self.environment_name = environment_name

    def files_to_load(self):

        files_to_load = [
            os.path.join(
                current_dir,
                PROFILE_DIRECTORY,
                DEFAULT_PROFILES_DIRECTORY,
                f"{self.host_type}.yaml",
            ),
            os.path.join(
                current_dir,
                PROFILE_DIRECTORY,
                self.environment_name,
                f"{self.host_type}.yaml",
            ),
        ]

        return files_to_load


class Host(SubProfile):
    """docstring for Host"""

    def __init__(self, name):
        super().__init__(name)

        try:
            (host_type, environment_name, uid) = name.split("_")
        except ValueError:
            raise InvalidHostname

        self.host_type = host_type
        self.environment_name = environment_name
        self.uid = uid
        self.group_name = f"{host_type}_{environment_name}"

        self.group = None
        self.environment = None
        self._full_profile = MISSING

        self.stack_outputs = {}
        self.ansible_variables = {}

    @property
    def full_profile(self):
        if self._full_profile is MISSING:
            self._full_profile = {}
            self._full_profile.update(self.environment.variables)
            self._full_profile.update(self.group.variables)
            self._full_profile.update(self.variables)

        return self._full_profile

    @property
    def host_vars(self):
        return {**self.variables, **self.stack_outputs, **self.ansible_variables}

    def files_to_load(self):

        files_to_load = [
            os.path.join(
                current_dir,
                PROFILE_DIRECTORY,
                self.environment_name,
                self.host_type,
                f"{self.uid}.yaml",
            )
        ]

        return files_to_load

    def generate_stack_parameters(self):

        """From the host variables, format a parameter dictionary to use during
        Heat Stack creation or update

        Args:
            host (Host): The Host which will be provision or updated.

        Returns:
            dict: a valid parameter dictionary to use for the Heat stack creation
            or update

        """

        print(self.full_profile["create_floating_ip"])

        stack_parameters = {
            "instance_name": self.name,
            "public_keys": self.full_profile["public_keys"],
            "private_network_name": self.environment.private_network_name,
            "private_subnet_name": self.environment.private_subnet_name,
            "public_network_name": self.environment.public_network_name,
            "common_ports_secgroup_name": self.environment.common_ports_secgroup_name,
            "common_icmp_secgroup_name": self.environment.common_icmp_secgroup_name,
            "flavor": self.full_profile["flavor"],
            "image": self.full_profile["image"],
            "create_floating_ip": self.full_profile["create_floating_ip"],
            "use_config_drive": self.full_profile["OS_use_config_drive"],
            "allow_icmp": self.full_profile["allow_icmp"],
        }

        # The Heat templating language doesn't allow complex data structure
        # neither complex looping. We have to format the security_rule dictionary
        # and pass two lists to the Heat stacks: one for the list of ports, and
        # one for the list of corresponding protocol. Order matters i.e. element X
        # of port_list has to correspond to element X of protocol_list. See the
        # Heat reference:
        # https://docs.openstack.org/heat/latest/template_guide/hot_spec.html#repeat
        port_list = []
        protocol_list = []
        for security_rule in self.full_profile["secrules"]:
            port_list.append(security_rule["port"])
            protocol_list.append(security_rule["protocol"])

        stack_parameters["secrule_ports"] = ", ".join(map(str, port_list))
        stack_parameters["secrule_protocols"] = ", ".join(protocol_list)

        print(stack_parameters)

        return stack_parameters

    def augment_host_profile(self, stack):
        print(stack.output)
