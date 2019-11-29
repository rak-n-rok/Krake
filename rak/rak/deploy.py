from ansible import context
from ansible.cli import CLI
from ansible.module_utils.common.collections import ImmutableDict
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager

import os


def make_executor(hosts, ansible_dir, ansible_inventory_file):

    loader = DataLoader()

    context.CLIARGS = ImmutableDict(
        tags={},
        listtags=False,
        listtasks=False,
        listhosts=False,
        syntax=False,
        connection="ssh",
        module_path=None,
        forks=100,
        remote_user="ubuntu",
        private_key_file=None,
        ssh_common_args=None,
        ssh_extra_args=None,
        sftp_extra_args=None,
        scp_extra_args=None,
        become=True,
        become_method="sudo",
        become_user="root",
        verbosity=True,
        check=False,
        start_at_task=None,
    )

    inventory = InventoryManager(
        loader=loader, sources=(os.path.join(ansible_dir, ansible_inventory_file))
    )
    inventory.subset(", ".join(hosts))

    variable_manager = VariableManager(
        loader=loader, inventory=inventory, version_info=CLI.version_info(gitinfo=False)
    )

    pbex = PlaybookExecutor(
        playbooks=["/home/mg/gitlab/krake/ansible/site.yml"],
        inventory=inventory,
        variable_manager=variable_manager,
        loader=loader,
        passwords={},
    )

    return pbex


def deploy(config, hosts):

    ansible_dir = config["ansible_dir"]
    ansible_inventory_file = config["ansible_inventory_file"]

    pbex = make_executor(hosts, ansible_dir, ansible_inventory_file)

    results = pbex.run()

    print(results)
