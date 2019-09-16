from argparse import ArgumentParser


parser = ArgumentParser(prog="rok", description="Command line interface for Krake")
subparsers = parser.add_subparsers(help="Application types", dest="command")
subparsers.required = True
