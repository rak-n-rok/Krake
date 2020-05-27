#!/usr/bin/env python3
from argparse import ArgumentParser
import json
import shlex
import os
from itertools import chain


header = """# Auto-generated SSH configuration file for a given Ansible
# Krake inventory:
#
#     {hosts_file}
#
"""


def translate_hosts_to_conf(fname):
    with open(fname) as f:
        hosts = json.load(f)

    configs = (
        generate_ssh_entry(name, conf)
        for name, conf in hosts.items()
        if "ansible_host" in conf
    )

    return header.format(hosts_file=os.path.abspath(fname)) + "\n".join(configs)


def generate_extra_options(optstr):
    """Generate SSH config settings from SSH command line arguments statements."""
    options = shlex.split(optstr)

    while options:
        key = options.pop(0)

        if key == "-o":
            value = options.pop(0)
            name, option = value.split("=", 1)
            yield "    {} {}\n".format(name, option)


template = """Host {name}
    HostName {hostname}
    User {user}
    IdentityFile {identity_file}
"""


def generate_ssh_entry(host, conf):
    """Generate a single SSH config entry for the given host"""
    head = template.format(
        name=host,
        hostname=conf["ansible_host"],
        user=conf["ansible_user"],
        identity_file=conf["ansible_ssh_private_key_file"] or "~/.ssh/id_rsa",
    )

    common = generate_extra_options(conf.get("ansible_ssh_common_args", ""))
    extra = generate_extra_options(conf.get("ansible_ssh_extra_args", ""))

    return head + "".join(chain(common, extra))


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Generate ssh config section for "
        "every dynamic host in Ansible "
        "inventory"
    )
    parser.add_argument("hosts")
    parser.add_argument("--out", help="Output file", default=None)
    args = parser.parse_args()

    config = translate_hosts_to_conf(args.hosts)

    if args.out is None:
        print(config)
    else:
        with open(args.out, "w") as f:
            f.write(config)
