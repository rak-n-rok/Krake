import sys
from argparse import FileType
import yaml
from .parser import subparsers
from .fixtures import use


@use("session")
def create(session, file):
    manifest = file.read()

    resp = session.post("/kubernetes/applications", json={"manifest": manifest})
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

create_parser = commands.add_parser("create", help="Create Kubernetes application")
create_parser.set_defaults(command=create)
create_parser.add_argument("-f", "--file", type=FileType(), required=True)

delete_parser = commands.add_parser("delete", help="Delete Kubernetes application")
delete_parser.set_defaults(command=delete)
delete_parser.add_argument("id", help="Kubernetes application ID")
