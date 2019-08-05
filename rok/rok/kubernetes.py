"""Kubernetes subcommands

.. code:: bash

    python -m rok kubernetes --help

"""
import sys
from argparse import FileType
from base64 import b64encode
import yaml

from .parser import ParserSpec, argument
from .fixtures import depends
from .formatters import BaseTable, Cell, printer


kubernetes = ParserSpec(
    "kubernetes", aliases=["kube"], help="Manage Kubernetes resources"
)

application = kubernetes.subparser(
    "application", aliases=["app"], help="Manage Kubernetes applications"
)

formatting = argument(
    "-f",
    "--format",
    choices=["table", "json", "yaml"],
    default="table",
    help="Format of the output, table by default",
)


class ApplicationListTable(BaseTable):
    pass


@application.command("list", help="List Kubernetes application")
@argument("-a", "--all", action="store_true", help="Show deleted applications")
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@formatting
@depends("config", "session")
@printer(table=ApplicationListTable(many=True))
def list_applications(config, session, namespace, all):
    if namespace is None:
        namespace = config["user"]

    if all:
        url = f"/kubernetes/namespaces/{namespace}/applications?all"
    else:
        url = f"/kubernetes/namespaces/{namespace}/applications"
    resp = session.get(url)
    return resp.json()


@application.command("create", help="Create Kubernetes application")
@argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@argument("name", help="Name of the application")
@depends("config", "session")
def create_application(config, session, file, namespace, name):
    if namespace is None:
        namespace = config["user"]

    app = {"metadata": {"name": name}, "spec": {"manifest": file.read()}}
    resp = session.post(f"/kubernetes/namespaces/{namespace}/applications", json=app)
    data = resp.json()
    yaml.dump(data, default_flow_style=False, stream=sys.stdout)


class ApplicationTable(BaseTable):
    reason = Cell("status.reason")


@application.command("get", help="Get Kubernetes application")
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@argument("name", help="Kubernetes application name")
@formatting
@depends("config", "session")
@printer(table=ApplicationTable())
def get_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/kubernetes/namespaces/{namespace}/applications/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        print(f"Error: Kubernetes application {name!r} not found")
        raise SystemExit(1)

    resp.raise_for_status()
    return resp.json()


@application.command("update", help="Update Kubernetes application")
@argument("name", help="Kubernetes application name")
@argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@depends("config", "session")
def update_application(config, session, namespace, name, file):
    if namespace is None:
        namespace = config["user"]

    app = {"metadata": {"name": name}, "spec": {"manifest": file.read()}}
    session.put(f"/kubernetes/namespaces/{namespace}/applications/{name}", json=app)


@application.command("delete", help="Delete Kubernetes application")
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@argument("name", help="Kubernetes application name")
@depends("config", "session")
def delete_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    session.delete(f"/kubernetes/namespaces/{namespace}/applications/{name}")


cluster = kubernetes.subparser("cluster", help="Manage Kubernetes clusters")


class ClusterTable(BaseTable):
    kind = Cell("spec.kind")


@cluster.command("create", help="Register an existing Kubernetes cluster")
@argument("--context", "-c", dest="contexts", action="append")
@argument(
    "-n", "--namespace", help="Namespace of the Kubernetes cluster. Defaults to user"
)
@argument(
    "kubeconfig",
    type=FileType(),
    help="Kubeconfig file that should be used to control this cluster",
)
@depends("config", "session")
def create_cluster(config, session, namespace, kubeconfig, contexts):
    if namespace is None:
        namespace = config["user"]

    config = yaml.safe_load(kubeconfig)

    if not contexts:
        # current_context = config["current-context"]
        # if not current_context:
        #     print("Error: No current context specified")
        #     return 1
        # contexts = [current_context]
        contexts = [context["name"] for context in config["contexts"]]

    def find_resource_by_name(kind, name):
        for resource in config[kind]:
            if resource["name"] == name:
                return resource
        raise ValueError(f"Resource {name!r} of kind {kind!r} not found")

    def replace_file_attr(spec, attr):
        """Load file references as base64-encoded string

        Deletes the file-reference attribute and add a new ``{attr}-data``
        attribute with the base64-encoded content of the referenced file.

        Attr:
            spec (dict): Resource specification
            attr (str): Name of the attribute

        """
        if attr in spec:
            with open(spec[attr], "rb") as fd:
                data = b64encode(fd.read()).decode()
            del spec[attr]
            spec[f"{attr}-data"] = data

    for context_name in contexts:
        context = find_resource_by_name("contexts", context_name)
        cluster = find_resource_by_name("clusters", context["context"]["cluster"])
        user = find_resource_by_name("users", context["context"]["user"])

        replace_file_attr(cluster["cluster"], "certificate-authority")
        replace_file_attr(user["user"], "client-certificate")
        replace_file_attr(user["user"], "client-key")

        cluster_config = config.copy()
        cluster_config["clusters"] = [cluster]
        cluster_config["contexts"] = [context]
        cluster_config["users"] = [user]
        cluster_config["current-context"] = context["name"]

        cluster = {
            "metadata": {"name": cluster["name"]},
            "spec": {"kubeconfig": cluster_config},
        }
        resp = session.post(
            f"/kubernetes/namespaces/{namespace}/clusters", json=cluster
        )

        print("---")
        data = resp.json()
        yaml.dump(data, default_flow_style=False, stream=sys.stdout)


@cluster.command("list", help="List Kubernetes clusters")
@argument(
    "-n", "--namespace", help="Namespace of the Kubernetes cluster. Defaults to user"
)
@formatting
@depends("config", "session")
@printer(table=ClusterTable(many=True))
def list_clusters(config, session, namespace):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/kubernetes/namespaces/{namespace}/clusters")
    return resp.json()


@cluster.command("delete", help="Delete Kubernetes cluster")
@argument("-n", "--namespace", help="Namespace of the cluster. Defaults to user")
@argument("name", help="Kubernetes cluster name")
@depends("config", "session")
def delete_cluster(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    session.delete(f"/kubernetes/namespaces/{namespace}/clusters/{name}")
