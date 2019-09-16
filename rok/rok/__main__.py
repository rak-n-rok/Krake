import sys
from .parser import parser
from .fixtures import Resolver
from . import kubernetes


def main():
    args = vars(parser.parse_args())
    command = args.pop("command")

    with Resolver() as resolver:
        exit_code = resolver(command, **args)
        # dependencies = resolver.resolve(command)
        # exit_code = command(**args, **dependencies)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
