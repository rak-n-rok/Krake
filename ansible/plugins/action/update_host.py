import json
from copy import deepcopy
from pathlib import Path

from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleError


class ActionModule(ActionBase):
    special_args = frozenset(('hostname', 'append'))

    def run(self, tmp=None, task_vars=None):
        try:
            hostname = self._task.args['hostname']
        except KeyError:
            raise AnsibleError("'hostname' argument must be set")

        # If "append" is set to True, the host variables are updated and no
        # existing additional host variables will be deleted.
        append = self._task.args.get('append', False)

        hosts_file = Path(task_vars['hosts_file'])

        try:
            with hosts_file.open('r') as fd:
                inventory = json.load(fd)
        except (FileNotFoundError, json.JSONDecodeError):
            inventory = {}

        old_inventory = deepcopy(inventory)

        # Delete non-existent hosts from inventory
        for host in old_inventory.keys():
            if host not in task_vars['hostvars']:
                del inventory[host]

        host_vars = {key: value for key, value in self._task.args.items()
                     if key not in self.special_args}

        inventory_hostvars = inventory.setdefault(hostname, {})

        # Delete old host variables
        if not append:
            for key in list(inventory_hostvars.keys()):
                if key not in host_vars:
                    del inventory_hostvars[key]

        for key, value in host_vars.items():
            inventory_hostvars[key] = value

        if old_inventory != inventory:
            hosts_file.parent.mkdir(parents=True, exist_ok=True)

            with hosts_file.open('w') as fd:
                json.dump(inventory, fd, sort_keys=True, indent=4)

            return {
                'changed': True,
                'add_host': dict(host_name=hostname, host_vars=host_vars)
            }
        else:
            return dict(changed=False)
