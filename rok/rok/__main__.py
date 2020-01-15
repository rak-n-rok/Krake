import sys
from .fixtures import Resolver
from .parser import ParserSpec
from .kubernetes import kubernetes
from .openstack import openstack


spec = ParserSpec(prog="rok", description="Command line interface for Krake")
spec.add_spec(kubernetes)
spec.add_spec(openstack)

parser = spec.create_parser()


def main():
    args = vars(parser.parse_args())
    command = args.pop("command")

    with Resolver() as resolver:
        exit_code = resolver(command, **args)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
