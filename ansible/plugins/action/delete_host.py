import json
from copy import deepcopy
from pathlib import Path

from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleError


class ActionModule(ActionBase):
    special_args = frozenset(('hostname'))

    def run(self, tmp=None, task_vars=None):
        try:
            hostname = self._task.args['hostname']
        except KeyError:
            raise AnsibleError("'hostname' argument must be set")

        hosts_file = Path(task_vars['hosts_file'])

        try:
            with hosts_file.open('r') as fd:
                inventory = json.load(fd)
        except (FileNotFoundError, json.JSONDecodeError):
            inventory = {}

        try:
            del inventory[hostname]
        except KeyError:
            return dict(changed=False)

        hosts_file.parent.mkdir(parents=True, exist_ok=True)

        with hosts_file.open('w') as fd:
            json.dump(inventory, fd, sort_keys=True, indent=4)

        return {
            'changed': True,
        }
