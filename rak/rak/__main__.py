import os
import sys
import argparse
import yaml

from .provision import provision, unprovision
from .deploy import deploy


def fullprovision(config, hosts):
    provision(config, hosts)
    deploy(config, hosts)


parser = argparse.ArgumentParser(
    prog="rak",
    description="Command line interface for provisioning the Krake infrastructure",
)

subparsers = parser.add_subparsers()

# Provision subparser
provision_sb = subparsers.add_parser("provision", aliases=["pro"])
provision_sb.add_argument("hosts", nargs="+")
provision_sb.set_defaults(func=provision)

# Deploy subparser
deploy_sb = subparsers.add_parser("deploy")
deploy_sb.add_argument("hosts", nargs="+")
deploy_sb.set_defaults(func=deploy)

# Full Provision subparser
fullprovision_sb = subparsers.add_parser("fullprovision")
fullprovision_sb.add_argument("hosts", nargs="+")
fullprovision_sb.set_defaults(func=fullprovision)

# Unprovision subparser
unprovision_sb = subparsers.add_parser("unprovision")
unprovision_sb.add_argument("hosts", nargs="+")
unprovision_sb.set_defaults(func=unprovision)


def main():

    config = load_config()

    print(config)

    args = parser.parse_args()
    args.func(config, args.hosts)

    sys.exit(0)


def load_config():

    try:
        XDG_CONFIG_HOME = os.environ["XDG_CONFIG_HOME"]
    except KeyError:
        XDG_CONFIG_HOME = os.path.join(os.environ["HOME"], ".config")

    config_paths = [
        "rak.yaml",
        os.path.join(XDG_CONFIG_HOME, "rak.yaml"),
        "/etc/rak/rak.yaml",
    ]

    for path in config_paths:
        try:
            with open(path, "r") as fd:
                return yaml.safe_load(fd)
        except FileNotFoundError:
            pass

    # No config file was found. Use defaults
    return {
        "git_directory": "/home/mg/gitlab/krake/",
        "ansible_directory": "ansible",
        "profile_directory": "/home/mg/gitlab/krake/rak/rak/profiles",
    }


if __name__ == "__main__":
    main()
