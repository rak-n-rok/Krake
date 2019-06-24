"""Kubernetes subcommands

.. code:: bash

    python -m rok kubernetes --help

"""
import sys
from argparse import FileType
import yaml
from .parser import subparsers
from .fixtures import use


@use("session")
def list_applications(session, all):
    if all:
        url = "/kubernetes/applications?all"
    else:
        url = "/kubernetes/applications"
    resp = session.get(url)
    data = resp.json()
    for app in data:
        print("---")
        yaml.dump(app, default_flow_style=False, stream=sys.stdout)


@use("session")
def create(session, file):
    manifest = file.read()

    resp = session.post("/kubernetes/applications", json={"manifest": manifest})
    data = resp.json()
    yaml.dump(data, default_flow_style=False, stream=sys.stdout)


@use("session")
def get(session, id):
    resp = session.get(f"/kubernetes/applications/{id}", raise_for_status=False)
    if resp.status_code == 404:
        print(f"Error: Kubernetes application {id!r} not found")
        return 1

    resp.raise_for_status()
    data = resp.json()
    yaml.dump(data, default_flow_style=False, stream=sys.stdout)


@use("session")
def update(session, id, file):
    manifest = file.read()
    session.put(f"/kubernetes/applications/{id}", json={"manifest"})


@use("session")
def delete(session, id):
    session.delete(f"/kubernetes/applications/{id}")


kubernetes = subparsers.add_parser(
    "kubernetes", aliases=["k8s", "kube"], help="Manage Kubernetes applications"
)
commands = kubernetes.add_subparsers(help="Kubernetes subcommands", dest="command")
commands.required = True

list_parser = commands.add_parser("list", help="List Kubernetes application")
list_parser.set_defaults(command=list_applications)
list_parser.add_argument(
    "-a", "--all", action="store_true", help="Show deleted applications"
)

create_parser = commands.add_parser("create", help="Create Kubernetes application")
create_parser.set_defaults(command=create)
create_parser.add_argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)

get_parser = commands.add_parser("get", help="Get Kubernetes application")
get_parser.set_defaults(command=get)
get_parser.add_argument("id", help="Application ID")

update_parser = commands.add_parser("update", help="Update Kubernetes application")
update_parser.set_defaults(command=update)
update_parser.add_argument("id", help="Application ID")
update_parser.add_argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)

delete_parser = commands.add_parser("delete", help="Delete Kubernetes application")
delete_parser.set_defaults(command=delete)
delete_parser.add_argument("id", help="Kubernetes application ID")
