import json
from collections import MutableMapping
from pathlib import Path

from ansible.errors import AnsibleParserError
from ansible.plugins.inventory.yaml import InventoryModule as YAMLInventory
from ansible.module_utils._text import to_native


DOCUMENTATION = """
    name: krake_inventory
    plugin_type: inventory
    short_description: Parse standard YAML static inventory but augment host variables with auto-generated JSON-file
    description:
    options:
      yaml_extensions:
        description: list of 'valid' extensions for files containing YAML
        type: list
        default: ['.yaml', '.yml', '.json']
        env:
          - name: ANSIBLE_YAML_FILENAME_EXT
          - name: ANSIBLE_INVENTORY_PLUGIN_EXTS
        ini:
          - key: yaml_valid_extensions
            section: defaults
          - section: inventory_plugin_yaml
            key: yaml_valid_extensions
"""

EXAMPLES = """
    plugin: krake_inventory

    all:
      vars:
        keypair: <your-keypair>
        key_file: null
        gateway: krake-gateway

      children:
        gateways:
          hosts:
            krake-gateway:
              network: krake-network
              vpn_cidr: 10.9.0.0/24

        central_idps:
          hosts:
            krake-central-idp:
              network: krake-network

        devstacks:
          hosts:
            krake-devstack-1:
              id: 1
              idp: krake-central-idp
            krake-devstack-2:
              id: 2
              idp: krake-central-idp

        magnum_clusters:
          hosts:
            openstack-cluster-1:
              name: kubernetes1
              devstack: krake-devstack-1

        prometheus:
          hosts:
            krake-prometheus:
              hostname: prometheus
              network: krake-network

        krake_apps:
          hosts:
            krake:
              hostname: krake
              idp: krake-central-idp
              devstacks:
                - krake-devstack-2
              magnum_clusters:
                - openstack-cluster-1
              authorized_keys:
                - public_keys/my
                - public_keys/another

        networks:
          hosts:
            krake-network:
              subnet_name: krake-subnet
              subnet_cidr: 192.168.0.0/24
              public_network: shared-public-IPv4
              router_name: krake-router
              common_secgroup_name: krake-common-secgroup

"""


class InventoryModule(YAMLInventory):
    NAME = 'krake_inventory'

    ignore_keys = ['plugin']

    def parse(self, inventory, loader, path, cache=False):
        # We do not call the base class here because this would raise an
        # exception. Instead, we reimplment its behavior. Furthermore, relying
        # on behavior of the base class method when overwriting a method is
        # often times a bad idea.
        self.loader = loader
        self.inventory = inventory

        self.set_options()

        try:
            data = self.loader.load_from_file(path, cache=False)
        except Exception as e:
            raise AnsibleParserError(e)

        if not data:
            raise AnsibleParserError("Parsed empty YAML file")
        elif not isinstance(data, MutableMapping):
            raise AnsibleParserError("YAML inventory has invalid structure, it should be a dictionary, got: {}".format(type(data)))

        # We expect top level keys to correspond to groups, iterate over them
        # to get host, vars and subgroups (which we iterate over recursivelly)
        if not isinstance(data, MutableMapping):
            raise AnsibleParserError("Invalid data from file, expected dictionary and got:\n\n{!r}".format(to_native(data)))

        for group_name in data:
            if group_name not in self.ignore_keys:
                self._parse_group(group_name, data[group_name])

        try:
            hosts_file = self.inventory.groups['all'].get_vars()['hosts_file']
        except KeyError:
            filename = '{}.json'.format(Path(path).stem)
            hosts_file = Path(__file__).parent.parent.parent / '.etc' / filename
            self.inventory.set_variable('all', 'hosts_file', str(hosts_file))

        try:
            with open(hosts_file, 'r') as fd:
                hosts = json.load(fd)
        except (FileNotFoundError, json.JSONDecodeError):
            hosts = {}

        # Load host and host variables
        for hostname, host_vars in hosts.items():
            if hostname in self.inventory.hosts:
                for key, value in host_vars.items():
                    self.inventory.set_variable(hostname, key, value)
