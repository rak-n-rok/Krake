"""Kubernetes subcommands

.. code:: bash

    python -m rok kubernetes --help

"""
import sys
from argparse import FileType
from base64 import b64encode
import yaml
from .parser import ParserSpec, argument


kubernetes = ParserSpec(
    "kubernetes", aliases=["kube"], help="Manage Kubernetes applications"
)


@kubernetes.command("list", help="List Kubernetes application")
@argument("-a", "--all", action="store_true", help="Show deleted applications")
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
def list_applications(config, session, namespace, all):
    if namespace is None:
        namespace = config["user"]

    if all:
        url = f"/namespaces/{namespace}/kubernetes/applications?all"
    else:
        url = f"/namespaces/{namespace}/kubernetes/applications"
    resp = session.get(url)
    for app in resp.json():
        print("---")
        yaml.dump(app, default_flow_style=False, stream=sys.stdout)


@kubernetes.command("create", help="Create Kubernetes application")
@argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@argument("name", help="Name of the application")
def create_application(config, session, file, namespace, name):
    if namespace is None:
        namespace = config["user"]

    manifest = file.read()

    resp = session.post(
        f"/namespaces/{namespace}/kubernetes/applications",
        json={"manifest": manifest, "name": name},
    )
    data = resp.json()
    yaml.dump(data, default_flow_style=False, stream=sys.stdout)


@kubernetes.command("get", help="Get Kubernetes application")
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@argument("name", help="Kubernetes application name")
def get_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/namespaces/{namespace}/kubernetes/applications/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        print(f"Error: Kubernetes application {name!r} not found")
        return 1

    resp.raise_for_status()
    data = resp.json()
    yaml.dump(data, default_flow_style=False, stream=sys.stdout)


@kubernetes.command("update", help="Update Kubernetes application")
@argument("name", help="Kubernetes application name")
@argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
def update_application(config, session, namespace, name, file):
    if namespace is None:
        namespace = config["user"]

    manifest = file.read()
    session.put(
        f"/namespaces/{namespace}/kubernetes/applications/{name}",
        json={"manifest": manifest},
    )


@kubernetes.command("delete", help="Delete Kubernetes application")
@argument("-n", "--namespace", help="Namespace of the application. Defaults to user")
@argument("name", help="Kubernetes application name")
def delete_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    session.delete(f"/namespaces/{namespace}/kubernetes/applications/{name}")


cluster = kubernetes.subparser("cluster", help="Manage Kubernetes cluster")


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
                data = b64encode(fd.read())
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

        resp = session.post(
            f"/namespaces/{namespace}/kubernetes/clusters", json=cluster_config
        )

        print("---")
        data = resp.json()
        yaml.dump(data, default_flow_style=False, stream=sys.stdout)


@cluster.command("list", help="List Kubernetes clusters")
@argument(
    "-n", "--namespace", help="Namespace of the Kubernetes cluster. Defaults to user"
)
def list_clusters(config, session, namespace):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/namespaces/{namespace}/kubernetes/clusters")
    for cluster in resp.json():
        print("---")
        yaml.dump(cluster, default_flow_style=False, stream=sys.stdout)
