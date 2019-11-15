import sys
import argparse

from .provision import provision_hosts, unprovision_hosts
from .deploy import deploy_hosts

# from .fixtures import Resolver
# from .parser import ParserSpec
# from .kubernetes import kubernetes

parser = argparse.ArgumentParser(
    prog="rak",
    description="Command line interface for provisioning the Krake infrastructure",
)

subparsers = parser.add_subparsers()

# Provision subparser
provision = subparsers.add_parser("provision", aliases=["pro"])
provision.add_argument("hosts", nargs="+")
provision.set_defaults(func=provision_hosts)

# Deploy subparser
deploy = subparsers.add_parser("deploy")
deploy.add_argument("hosts", nargs="+")
deploy.set_defaults(func=deploy_hosts)

# Full Provision subparser
fullprovision = subparsers.add_parser("fullprovision")
fullprovision.add_argument("hosts", nargs="+")
fullprovision.set_defaults(func=fullprovision)

# Unprovision subparser
unprovision = subparsers.add_parser("unprovision")
unprovision.add_argument("hosts", nargs="+")
unprovision.set_defaults(func=unprovision_hosts)


def main():
    args = parser.parse_args()
    args.func(args.hosts)

    sys.exit(0)


def fullprovision(hosts):
    provision(hosts)
    deploy(hosts)


if __name__ == "__main__":
    main()
