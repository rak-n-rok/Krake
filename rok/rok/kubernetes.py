"""Kubernetes subcommands

.. code:: bash

    python -m rok kubernetes --help

"""
import sys
from argparse import FileType
from base64 import b64encode
import yaml

from .parser import (
    ParserSpec,
    argument,
    arg_formatting,
    arg_labels,
    arg_namespace,
    arg_metric,
)
from .fixtures import depends
from .formatters import BaseTable, Cell, printer, dict_formatter


kubernetes = ParserSpec(
    "kubernetes", aliases=["kube"], help="Manage Kubernetes resources"
)

application = kubernetes.subparser(
    "application", aliases=["app"], help="Manage Kubernetes applications"
)

arg_cluster_label_constraints = argument(
    "-L",
    "--cluster-label-constraint",
    dest="cluster_label_constraints",
    default=[],
    action="append",
    help="Constraint for labels of the cluster. Can be specified multiple times",
)

arg_hooks = argument(
    "-H",
    "--hook",
    dest="hooks",
    default=[],
    action="append",
    help="Application hook. Can be specified multiple times",
)

arg_cluster_resource_constraints = argument(
    "-R",
    "--cluster-resource-constraint",
    dest="cluster_resource_constraints",
    default=[],
    action="append",
    help="Custom resources definition constraint of the cluster. "
    "Can be specified multiple times",
)

arg_custom_resources = argument(
    "-R",
    "--custom-resource",
    dest="custom_resources",
    default=[],
    action="append",
    help="Custom resources definition of the cluster. "
    "Can be specified multiple times",
)


class ApplicationListTable(BaseTable):
    state = Cell("status.state")


@application.command("list", help="List Kubernetes application")
@argument(
    "-a", "--all", action="store_true", help="Show applications in all namespaces"
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ApplicationListTable(many=True))
def list_applications(config, session, namespace, all):
    if all:
        url = f"/kubernetes/applications"
    else:
        if namespace is None:
            namespace = config["user"]
        url = f"/kubernetes/namespaces/{namespace}/applications"
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@application.command("create", help="Create Kubernetes application")
@argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)
@argument("name", help="Name of the application")
@arg_cluster_label_constraints
@arg_cluster_resource_constraints
@arg_namespace
@arg_labels
@arg_hooks
@depends("config", "session")
def create_application(
    config,
    session,
    file,
    name,
    namespace,
    cluster_label_constraints,
    labels,
    cluster_resource_constraints,
    hooks,
):
    if namespace is None:
        namespace = config["user"]

    manifest = list(yaml.safe_load_all(file))
    app = {
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "hooks": hooks,
            "manifest": manifest,
            "constraints": {
                "cluster": {
                    "labels": cluster_label_constraints,
                    "custom_resources": cluster_resource_constraints,
                }
            },
        },
    }
    resp = session.post(f"/kubernetes/namespaces/{namespace}/applications", json=app)
    data = resp.json()
    yaml.dump(data, default_flow_style=False, stream=sys.stdout)


class ApplicationTable(BaseTable):
    reason = Cell("status.reason", formatter=dict_formatter)
    services = Cell("status.services", formatter=dict_formatter)
    constraints = Cell("spec.constraints", formatter=dict_formatter)


@application.command("get", help="Get Kubernetes application")
@argument("name", help="Kubernetes application name")
@arg_namespace
@arg_formatting
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
@argument("-f", "--file", type=FileType(), help="Kubernetes manifest file")
@arg_cluster_label_constraints
@arg_cluster_resource_constraints
@arg_namespace
@arg_labels
@arg_hooks
@depends("config", "session")
def update_application(
    config,
    session,
    namespace,
    name,
    file,
    labels,
    cluster_label_constraints,
    cluster_resource_constraints,
    hooks,
):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/kubernetes/namespaces/{namespace}/applications/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        raise SystemExit(f"Error: Magnum cluster {name!r} not found")
    resp.raise_for_status()
    app = resp.json()

    if file:
        manifest = list(yaml.safe_load_all(file))
        app["spec"]["manifest"] = manifest

    if labels:
        app["metadata"]["labels"] = labels
    if hooks:
        app["spec"]["hooks"] = hooks

    app_constraints = app["spec"]["constraints"]
    if cluster_label_constraints:
        app_constraints["cluster"]["labels"] = cluster_label_constraints
    if cluster_resource_constraints:
        app_constraints["cluster"]["custom_resources"] = cluster_resource_constraints

    resp = session.put(
        f"/kubernetes/namespaces/{namespace}/applications/{name}", json=app
    )

    return resp.json()


@application.command("delete", help="Delete Kubernetes application")
@argument("name", help="Kubernetes application name")
@arg_namespace
@depends("config", "session")
def delete_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.delete(f"/kubernetes/namespaces/{namespace}/applications/{name}")
    if resp.status_code == 204:
        return None
    return resp.json()


cluster = kubernetes.subparser("cluster", help="Manage Kubernetes clusters")


class ClusterTable(BaseTable):
    pass


@cluster.command("create", help="Register an existing Kubernetes cluster")
@argument("--context", "-c", dest="contexts", action="append")
@argument(
    "kubeconfig",
    type=FileType(),
    help="Kubeconfig file that should be used to control this cluster",
)
@arg_custom_resources
@arg_metric
@arg_namespace
@arg_labels
@depends("config", "session")
def create_cluster(
    config, session, namespace, kubeconfig, contexts, metrics, labels, custom_resources
):
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
            "metadata": {"name": cluster["name"], "labels": labels},
            "spec": {
                "kubeconfig": cluster_config,
                "metrics": metrics,
                "custom_resources": custom_resources,
            },
        }
        resp = session.post(
            f"/kubernetes/namespaces/{namespace}/clusters", json=cluster
        )

        print("---")
        data = resp.json()
        yaml.dump(data, default_flow_style=False, stream=sys.stdout)


@cluster.command("list", help="List Kubernetes clusters")
@argument(
    "-a", "--all", action="store_true", help="Show applications in all namespaces"
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable(many=True))
def list_clusters(config, session, namespace, all):
    if all:
        url = "/kubernetes/clusters"
    else:
        if namespace is None:
            namespace = config["user"]
        url = f"/kubernetes/namespaces/{namespace}/clusters"
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@cluster.command("delete", help="Delete Kubernetes cluster")
@argument(
    "--cascade",
    help="Delete the cluster and all dependent resources",
    action="store_true",
)
@argument("name", help="Kubernetes cluster name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable())
def delete_cluster(config, session, namespace, name, cascade):
    if namespace is None:
        namespace = config["user"]

    url = f"/kubernetes/namespaces/{namespace}/clusters/{name}"
    if cascade:
        url = f"{url}?cascade"

    resp = session.delete(url)
    if resp.status_code == 204:
        return None
    return resp.json()
