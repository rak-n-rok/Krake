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
    mutually_exclusive_group,
    arg_formatting,
    arg_labels,
    arg_namespace,
    arg_metric,
)
from .fixtures import depends
from .formatters import (
    BaseTable,
    Cell,
    printer,
    dict_formatter,
    bool_formatter,
    format_datetime,
)

kubernetes = ParserSpec(
    "kubernetes", aliases=["kube"], help="Manage Kubernetes resources"
)

application = kubernetes.subparser(
    "application", aliases=["app"], help="Manage Kubernetes applications"
)

arg_migration_constraints = mutually_exclusive_group(
    [
        (
            ["--disable-migration"],
            {
                "dest": "disable_migration",
                "action": "store_true",
                "help": "Disable migration of the application",
            },
        ),
        (
            ["--enable-migration"],
            {
                "dest": "enable_migration",
                "action": "store_true",
                "help": "Enable migration of the application",
            },
        ),
    ]
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
        url = "/kubernetes/applications"
    else:
        if namespace is None:
            namespace = config["user"]
        url = f"/kubernetes/namespaces/{namespace}/applications"
    resp = session.get(url)
    body = resp.json()
    return body["items"]


class ApplicationTable(ApplicationListTable):
    reason = Cell("status.reason", formatter=dict_formatter)
    services = Cell("status.services", formatter=dict_formatter)
    migration = Cell(
        "spec.constraints.migration", name="allow migration", formatter=bool_formatter
    )
    label_constraints = Cell(
        "spec.constraints.cluster.labels", name="label constraints"
    )
    resources_constraints = Cell(
        "spec.constraints.cluster.custom_resources", name="resources constraints"
    )
    hooks = Cell("spec.hooks")
    scheduled_to = Cell("status.scheduled_to")
    scheduled = Cell("status.scheduled", formatter=format_datetime)
    running_on = Cell("status.running_on")


@application.command("create", help="Create Kubernetes application")
@argument(
    "-f", "--file", type=FileType(), required=True, help="Kubernetes manifest file"
)
@argument("name", help="Name of the application")
@arg_migration_constraints(default="--enable-migration")
@arg_cluster_label_constraints
@arg_cluster_resource_constraints
@arg_namespace
@arg_labels
@arg_hooks
@arg_formatting
@depends("config", "session")
@printer(table=ApplicationTable())
def create_application(
    config,
    session,
    file,
    name,
    namespace,
    disable_migration,
    enable_migration,
    cluster_label_constraints,
    labels,
    cluster_resource_constraints,
    hooks,
):
    if namespace is None:
        namespace = config["user"]

    migration = True
    if enable_migration or disable_migration:  # If either one was specified by the user
        migration = enable_migration
    manifest = list(yaml.safe_load_all(file))
    app = {
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "hooks": hooks,
            "manifest": manifest,
            "constraints": {
                "migration": migration,
                "cluster": {
                    "labels": cluster_label_constraints,
                    "custom_resources": cluster_resource_constraints,
                },
            },
        },
    }
    resp = session.post(f"/kubernetes/namespaces/{namespace}/applications", json=app)
    return resp.json()


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
        raise SystemExit(f"Error 404: Application {name!r} not found")
    resp.raise_for_status()

    resp.raise_for_status()
    return resp.json()


@application.command("update", help="Update Kubernetes application")
@argument("name", help="Kubernetes application name")
@argument("-f", "--file", type=FileType(), help="Kubernetes manifest file")
@arg_migration_constraints()
@arg_cluster_label_constraints
@arg_cluster_resource_constraints
@arg_namespace
@arg_labels
@arg_hooks
@arg_formatting
@depends("config", "session")
@printer(table=ApplicationTable())
def update_application(
    config,
    session,
    namespace,
    name,
    file,
    labels,
    disable_migration,
    enable_migration,
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
        raise SystemExit(f"Error 404: Application {name!r} not found")
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
    if disable_migration or enable_migration:
        app_constraints["migration"] = enable_migration

    resp = session.put(
        f"/kubernetes/namespaces/{namespace}/applications/{name}", json=app
    )

    return resp.json()


@application.command("delete", help="Delete Kubernetes application")
@argument("name", help="Kubernetes application name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ApplicationTable())
def delete_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.delete(
        f"/kubernetes/namespaces/{namespace}/applications/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Application {name!r} not found")
    resp.raise_for_status()

    if resp.status_code == 204:
        return None
    return resp.json()


cluster = kubernetes.subparser("cluster", help="Manage Kubernetes clusters")


class ClusterTableList(BaseTable):
    state = Cell("status.state")


class ClusterTable(ClusterTableList):
    custom_resources = Cell("spec.custom_resources")
    metrics = Cell("spec.metrics")
    failing_metrics = Cell("status.metrics_reasons", formatter=dict_formatter)


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


def create_cluster_config(kubeconfig, context_name=None):
    """From the provided kubeconfig, create a new kubeconfig that only contains the
    context provided. If no context is provided, the current one is used instead.

    Args:
        kubeconfig (_io.TextIOWrapper): the content of the provided kubeconfig file.
        context_name (str): the name of the context to use for the extraction.

    Returns:
        dict[str, Any]: the newly created kubeconfig, with only the provided context.

    """
    config = yaml.safe_load(kubeconfig)

    def find_resource_by_name(kind, name):
        for resource in config[kind]:
            if resource["name"] == name:
                return resource
        raise ValueError(f"Resource {name!r} of kind {kind!r} not found")

    if not context_name:
        current_context = find_resource_by_name("contexts", config["current-context"])
        context_name = current_context["name"]

    try:
        context = find_resource_by_name("contexts", context_name)
    except ValueError:
        sys.exit(
            f"Error: the context {context_name!r} is not present in the provided"
            " kubeconfig file"
        )

    cluster = find_resource_by_name("clusters", context["context"]["cluster"])
    user = find_resource_by_name("users", context["context"]["user"])

    # Replace the path of the certificates with the actual certificates to prevent
    # non-found files in Krake.
    replace_file_attr(cluster["cluster"], "certificate-authority")
    replace_file_attr(user["user"], "client-certificate")
    replace_file_attr(user["user"], "client-key")

    cluster_config = config.copy()
    cluster_config["clusters"] = [cluster]
    cluster_config["contexts"] = [context]
    cluster_config["users"] = [user]
    cluster_config["current-context"] = context["name"]

    return cluster_config, cluster["name"]


@cluster.command("create", help="Register an existing Kubernetes cluster")
@argument(
    "--context", "-c", help="Name of the context inside the kubeconfig file to use."
)
@argument(
    "kubeconfig",
    type=FileType(),
    help="Kubeconfig file that should be used to control this cluster",
)
@arg_custom_resources
@arg_metric
@arg_namespace
@arg_labels
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable(many=False))
def create_cluster(
    config, session, namespace, kubeconfig, context, metrics, labels, custom_resources
):
    if namespace is None:
        namespace = config["user"]

    cluster_config, cluster_name = create_cluster_config(kubeconfig, context)

    to_create = {
        "metadata": {"name": cluster_name, "labels": labels},
        "spec": {
            "kubeconfig": cluster_config,
            "metrics": metrics,
            "custom_resources": custom_resources,
        },
    }
    resp = session.post(f"/kubernetes/namespaces/{namespace}/clusters", json=to_create)
    return resp.json()


@cluster.command("list", help="List Kubernetes clusters")
@argument(
    "-a", "--all", action="store_true", help="Show applications in all namespaces"
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTableList(many=True))
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


@cluster.command("get", help="Get Kubernetes cluster")
@argument("name", help="Kubernetes cluster name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable())
def get_cluster(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/kubernetes/namespaces/{namespace}/clusters/{name}", raise_for_status=False
    )
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Kubernetes cluster {name!r} not found")

    resp.raise_for_status()
    return resp.json()


@cluster.command("update", help="Update Kubernetes cluster")
@argument("name", help="Kubernetes cluster name")
@argument("-f", "--file", type=FileType(), help="Kubernetes kubeconfig file")
@argument(
    "--context", "-c", help="Name of the context inside the kubeconfig file to use."
)
@arg_custom_resources
@arg_metric
@arg_namespace
@arg_formatting
@arg_labels
@depends("config", "session")
@printer(table=ClusterTable())
def update_cluster(
    config, session, name, namespace, file, context, metrics, labels, custom_resources
):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/kubernetes/namespaces/{namespace}/clusters/{name}", raise_for_status=False
    )
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Kubernetes cluster {name!r} not found")
    resp.raise_for_status()
    cluster = resp.json()

    if file:
        cluster["spec"]["kubeconfig"], _ = create_cluster_config(file, context)

    if labels:
        cluster["metadata"]["labels"] = labels
    if metrics:
        cluster["spec"]["metrics"] = metrics
    if custom_resources:
        cluster["spec"]["custom_resources"] = custom_resources

    resp = session.put(
        f"/kubernetes/namespaces/{namespace}/clusters/{name}", json=cluster
    )

    return resp.json()


@cluster.command("delete", help="Delete Kubernetes cluster")
@argument("name", help="Kubernetes cluster name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable())
def delete_cluster(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.delete(
        f"/kubernetes/namespaces/{namespace}/clusters/{name}", raise_for_status=False
    )
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Kubernetes cluster {name!r} not found")
    resp.raise_for_status()

    if resp.status_code == 204:
        return None
    return resp.json()
