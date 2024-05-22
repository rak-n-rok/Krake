"""Kubernetes subcommands

.. code:: bash

    python -m rok kubernetes --help

"""
import json
import sys
import warnings
from argparse import FileType, Action
from base64 import b64encode
from functools import partial

import yaml

from .parser import (
    ParserSpec,
    argument,
    mutually_exclusive_group,
    arg_config,
    arg_formatting,
    arg_labels,
    arg_namespace,
    arg_metric,
    arg_global_metric,
    arg_backoff,
    arg_backoff_delay,
    arg_backoff_limit,
)
from .fixtures import depends
from .formatters import (
    BaseTable,
    Cell,
    printer,
    dict_formatter,
    bool_formatter,
    format_datetime,
    nodes_formatter,
    pods_formatter,
)

warnings.formatwarning = lambda message, *args, **kwargs: f"WARNING: {message}\n"

WARN_RESOURCES = {
    "Job",
    "CronJob",
    "StatefulSet",
}

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

arg_hook_complete = argument(
    "--hook-complete",
    dest="hooks",
    const=["complete"],
    action="append_const",
    help="Enables the application complete hook.",
)

TIMEOUT_PERIOD = 60


class ShutdownAction(Action):
    def __call__(self, parser, namespace, values=None, option_string=None):
        if values is None:
            values = []
        if len(values) < 1:
            defaults = [TIMEOUT_PERIOD]
            values = ["shutdown"] + values + defaults[len(values) :]
        else:
            values = ["shutdown"] + values
        attr = getattr(namespace, self.dest)
        if attr is None:
            attr = []
        setattr(namespace, self.dest, attr + [values])


def is_tosca_definition(definitions):
    """Evaluate if the application definition provided by end-user
    is a TOSCA template.

     TOSCA templates should be a single YAML file with a
     `tosca_definitions_version` key in it.

    Args:
        definitions (list): Given list of app definitions to analyze.

    Returns:
        bool: True is the app definition is a TOSCA template,
            False otherwise.

    """
    try:
        tosca, *_ = definitions
    except ValueError:
        return False

    if "tosca_definitions_version" in tosca.keys():
        return True

    return False


arg_hook_shutdown = argument(
    "--hook-shutdown",
    dest="hooks",
    metavar=("timeout-period"),
    nargs="*",
    action=ShutdownAction,
    help=(
        f"Enables the application shutdown hook. Additional arguments are possible:"
        f" timeout-period [{TIMEOUT_PERIOD}]s"
    ),
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

arg_cluster_metric_constraints = argument(
    "-M",
    "--cluster-metric-constraint",
    dest="cluster_metric_constraints",
    default=[],
    action="append",
    help="Constraint for metrics of the cluster. Can be specified multiple times",
)


arg_cloud_label_constraints = argument(
    "-L",
    "--cloud-label-constraint",
    dest="cloud_label_constraints",
    default=[],
    action="append",
    help="Constraint for labels of the cloud. Can be specified multiple times",
)

arg_cloud_metric_constraints = argument(
    "-M",
    "--cloud-metric-constraint",
    dest="cloud_metric_constraints",
    default=[],
    action="append",
    help="Constraint for metrics of the cloud. Can be specified multiple times",
)

arg_label_inheritance = argument(
    "--inherit-labels",
    dest="inherit_labels",
    action="store_true",
    help=(
        "Enables inheritance of all labels from the cloud "
        "the cluster is scheduled to."
    ),
)

arg_metric_inheritance = argument(
    "--inherit-metrics",
    dest="inherit_metrics",
    action="store_true",
    help=(
        "Enables inheritance of all metrics from the cloud "
        "the cluster is scheduled to."
    ),
)

arg_auto_cluster_create = argument(
    "--auto-cluster-create",
    dest="auto_cluster_create",
    action="store_true",
    help="Boolean value, if clusters should be automatically created",
)


class ApplicationListTable(BaseTable):
    state = Cell("status.state")


def handle_warning(app):
    """Handle warning message print out

    A warning message is printed out when an application
    contains resources that we considered as non-optimal for migration,
    the migration is enabled and the user did not set shutdown hook for
    the requested application.

    The warning messages could be filtered by `PYTHONWARNINGS`
    environment variable.
    see https://docs.python.org/3/library/warnings.html#default-warning-filter

    The following syntax should be used to disable all warnings:

    .. code:: bash

        PYTHONWARNINGS=ignore rok kube app create -f example.yaml example

    Args:
        app (dict): Application to evaluate

    """
    manifest = app["spec"]["manifest"]
    tosca = app["spec"]["tosca"]
    hooks = app["spec"].get("hooks", [])
    migration = app["spec"]["constraints"]["migration"]

    if "shutdown" not in [hook[0] for hook in hooks if hook] and migration:
        warn_resources = set()

        if manifest:
            warn_resources.union(
                [
                    resource["kind"]
                    for resource in manifest
                    if resource["kind"] in WARN_RESOURCES
                ]
            )
        elif tosca:
            for node in (
                tosca.get("topology_template", {}).get("node_templates", {}).values()
            ):
                if node:
                    for warn_resource in WARN_RESOURCES:
                        if warn_resource in json.dumps(
                            node.get("properties", {}).get("spec", {})
                        ):
                            warn_resources.add(warn_resource)

        if warn_resources:
            warnings.warn(
                f"Migration of k8s resources like `{', '.join(warn_resources)}`"
                " without graceful shutdown may exhibit errors or unexpected behavior."
                " Consider applying a shutdown hook or alternatively, disabling"
                " migration of the application by `--disable-migration` optional"
                " argument."
            )


@application.command("list", help="List Kubernetes application")
@argument(
    "-a", "--all", action="store_true", help="Show applications in all namespaces"
)
@arg_namespace
@arg_formatting
@arg_config
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
    container_health = Cell(
        "status.container_health", formatter=partial(pods_formatter)
    )
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
    metric_constraints = Cell(
        "spec.constraints.cluster.metrics", name="metric constraints"
    )
    hooks = Cell("spec.hooks")
    scheduled_to = Cell("status.scheduled_to")
    scheduled = Cell("status.scheduled", formatter=format_datetime)
    running_on = Cell("status.running_on")
    backoff = Cell("spec.backoff")
    backoff_delay = Cell("spec.backoff_delay")
    backoff_limit = Cell("spec.backoff_limit")


@application.command("create", help="Create Kubernetes application")
@argument(
    "-f",
    "--file",
    type=FileType(),
    help="Kubernetes manifest file or TOSCA template file",
)
@argument(
    "-u",
    "--url",
    type=str,
    help="TOSCA template URL or CSAR archive URL",
)
@argument(
    "-O",
    "--observer_schema_file",
    type=FileType(),
    help="Observer Schema File. "
    "If not specified, all fields present in the manifest file are observed",
)
@argument("name", help="Name of the application")
@arg_migration_constraints(default="--enable-migration")
@argument(
    "--wait",
    action="store",
    nargs="?",
    const="running",
    choices=["creating", "pending", "running"],
    help="Wait with the response until the application reaches a specific state."
    "If no state is specified, running is used as a default.",
)
@arg_cluster_label_constraints
@arg_cluster_resource_constraints
@arg_cluster_metric_constraints
@arg_namespace
@arg_labels
@arg_hook_complete
@arg_hook_shutdown
@arg_formatting
@arg_config
@arg_backoff
@arg_backoff_delay
@arg_backoff_limit
@arg_auto_cluster_create
@depends("config", "session")
@printer(table=ApplicationTable())
def create_application(
    config,
    session,
    file,
    url,
    observer_schema_file,
    name,
    namespace,
    disable_migration,
    enable_migration,
    cluster_label_constraints,
    labels,
    cluster_resource_constraints,
    cluster_metric_constraints,
    hooks,
    wait,
    backoff,
    backoff_delay,
    backoff_limit,
    auto_cluster_create
):
    manifest = []
    tosca = {}
    csar = None
    if file:
        definition = list(yaml.safe_load_all(file))
        if is_tosca_definition(definition):
            tosca, *_ = definition
        else:
            manifest = definition
    elif url:
        if url.endswith(("yaml", "yml")):
            tosca = url
        elif url.endswith(("zip", "csar")):
            csar = url
        else:
            sys.exit(
                "Error: Application should be defined by a TOSCA template URL"
                " with `.yaml` or `.yml` suffix or a CSAR archive URL with"
                " `.csar` or `.zip` suffix."
            )
    else:
        sys.exit(
            "Error: Application should be defined by a TOSCA template file"
            " or a Kubernetes manifest file via the `--file` optional argument or"
            " a TOSCA template URL or CSAR URL via the `--url` optional argument."
        )

    if namespace is None:
        namespace = config["user"]

    migration = True
    if enable_migration or disable_migration:  # If either one was specified by the user
        migration = enable_migration

    observer_schema = []

    if observer_schema_file:
        observer_schema = list(yaml.safe_load_all(observer_schema_file))

    app = {
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "manifest": manifest,
            "tosca": tosca,
            "csar": csar,
            "observer_schema": observer_schema,
            "constraints": {
                "migration": migration,
                "cluster": {
                    "labels": cluster_label_constraints,
                    "custom_resources": cluster_resource_constraints,
                    "metrics": cluster_metric_constraints,
                },
            },
            "backoff": backoff,
            "backoff_delay": backoff_delay,
            "backoff_limit": backoff_limit,
            "auto_cluster_create": auto_cluster_create,
        },
    }

    if hooks:
        app["spec"]["hooks"] = []
        for hook in hooks:
            app["spec"]["hooks"].append(hook[0])
            if isinstance(hook, list) and len(hook) > 1 and hook[0] == "shutdown":
                app["spec"]["shutdown_grace_time"] = hook[1]

    if not url:  # skip warning handling when the app is defined by URL (TOSCA, CSAR)
        handle_warning(app)

    blocking_state = False
    if wait is not None:
        blocking_state = wait

    resp = session.post(
        f"/kubernetes/namespaces/{namespace}/applications",
        json=app,
        params={"blocking": blocking_state},
    )
    return resp.json()


@application.command("get", help="Get Kubernetes application")
@argument("name", help="Kubernetes application name")
@arg_namespace
@arg_formatting
@arg_config
@depends("config", "session")
@printer(table=ApplicationTable())
def get_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/kubernetes/namespaces/{namespace}/applications/{name}")
    return resp.json()


@application.command("update", help="Update Kubernetes application")
@argument("name", help="Kubernetes application name")
@argument(
    "-f",
    "--file",
    type=FileType(),
    help="Kubernetes manifest file or TOSCA template file",
)
@argument(
    "-u",
    "--url",
    type=str,
    help="TOSCA template URL or CSAR archive URL",
)
@argument("-O", "--observer_schema_file", type=FileType(), help="Observer Schema File")
@argument(
    "--wait",
    action="store",
    nargs="?",
    const="running",
    choices=["reconciling", "running"],
    help="Wait with the response until the application reaches a specific state."
    "If no state is specified, running is used as a default.",
)
@argument(
    "--remove-existing-labels",
    action='store_true',
    help="remove currently existing labels"
)
@argument(
    "--remove-existing-label-constraints",
    action='store_true',
    help="remove currently existing label constraints"
)
@argument(
    "--remove-existing-resource-constraints",
    action='store_true',
    help="remove currently existing resource constraints"
)
@argument(
    "--remove-existing-metric-constraints",
    action='store_true',
    help="remove currently existing metric constraints"
)
@arg_migration_constraints()
@arg_cluster_label_constraints
@arg_cluster_resource_constraints
@arg_cluster_metric_constraints
@arg_namespace
@arg_labels
@arg_hook_complete
@arg_hook_shutdown
@arg_formatting
@arg_config
@arg_backoff
@arg_backoff_delay
@arg_backoff_limit
@depends("config", "session")
@printer(table=ApplicationTable())
def update_application(
    config,
    session,
    namespace,
    name,
    file,
    url,
    observer_schema_file,
    labels,
    remove_existing_labels,
    disable_migration,
    enable_migration,
    cluster_label_constraints,
    remove_existing_label_constraints,
    cluster_resource_constraints,
    remove_existing_resource_constraints,
    cluster_metric_constraints,
    remove_existing_metric_constraints,
    hooks,
    wait,
    backoff,
    backoff_delay,
    backoff_limit,
):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/kubernetes/namespaces/{namespace}/applications/{name}")
    app = resp.json()

    if file:
        definition = list(yaml.safe_load_all(file))
        if is_tosca_definition(definition):
            # The previously generated k8s manifest should be removed
            app["spec"]["manifest"] = []
            app["spec"]["tosca"], *_ = definition
        else:
            app["spec"]["manifest"] = definition
    elif url:
        if url.endswith(("yaml", "yml")):
            # The previously generated k8s manifest should be removed
            app["spec"]["manifest"] = []
            app["spec"]["tosca"] = url
        elif url.endswith(("zip", "csar")):
            # The previously generated k8s manifest as well as TOSCA template
            # (if there is one) should be removed
            app["spec"]["manifest"] = []
            app["spec"]["tosca"] = {}
            app["spec"]["csar"] = url
        else:
            sys.exit(
                "Error: Application should be defined by a TOSCA template URL"
                " with `.yaml` or `.yml` suffix or a CSAR archive URL with"
                " `.csar` or `.zip` suffix."
            )

    if observer_schema_file:
        observer_schema = list(yaml.safe_load_all(observer_schema_file))
        app["spec"]["observer_schema"] = observer_schema
    if remove_existing_labels:
        app["metadata"]["labels"] = {}
    if labels:
        app["metadata"]["labels"].update(labels)
    if hooks:
        app["spec"]["hooks"] = hooks

    app_constraints = app["spec"]["constraints"]
    if remove_existing_label_constraints:
        app_constraints["cluster"]["labels"] = []
    if cluster_label_constraints:
        app_constraints["cluster"]["labels"] = cluster_label_constraints
    if remove_existing_resource_constraints:
        app_constraints["cluster"]["custom_resources"] = []
    if cluster_resource_constraints:
        app_constraints["cluster"]["custom_resources"] = cluster_resource_constraints
    if remove_existing_metric_constraints:
        app_constraints["cluster"]["metrics"] = []
    if cluster_metric_constraints:
        app_constraints["cluster"]["metrics"] += cluster_metric_constraints
    if disable_migration or enable_migration:
        app_constraints["migration"] = enable_migration
    if backoff:
        app["spec"]["backoff"] = backoff
    if backoff_delay:
        app["spec"]["backoff_delay"] = backoff_delay
    if backoff_limit:
        app["spec"]["backoff_limit"] = backoff_limit

    if not url:  # skip warning handling when the app is defined by URL (TOSCA, CSAR)
        handle_warning(app)

    blocking_state = False
    if wait is not None:
        blocking_state = wait

    resp = session.put(
        f"/kubernetes/namespaces/{namespace}/applications/{name}",
        json=app,
        params={"blocking": blocking_state},
    )
    return resp.json()


@application.command("delete", help="Delete Kubernetes application")
@argument("name", help="Kubernetes application name")
@argument(
    "--wait",
    action="store",
    nargs="?",
    const="deleted",
    choices=["deleting", "deleted"],
    help="Wait with the response until the application reaches a specific state."
    "If no state is specified, deleted is used as a default.",
)
@argument(
    "--force",
    dest="force",
    action="store_true",
    help="Force delete Kubernetes application",
)
@arg_namespace
@arg_formatting
@arg_config
@depends("config", "session")
@printer(table=ApplicationTable())
def delete_application(config, session, namespace, name, wait, force):
    if namespace is None:
        namespace = config["user"]

    blocking_state = False
    if wait is not None:
        blocking_state = wait

    resp = session.delete(
        f"/kubernetes/namespaces/{namespace}/applications/{name}",
        params={"blocking": blocking_state, "force": force},
    )

    if resp.status_code == 204:
        return None

    return resp.json()


@application.command("retry", help="Retry to migrate or delete an application")
@argument("name", help="Kubernetes application name")
@arg_namespace
@arg_formatting
@arg_config
@depends("config", "session")
@printer(table=ApplicationTable())
def retry_application(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.put(f"/kubernetes/namespaces/{namespace}/applications/{name}/retry")

    if resp.status_code == 204:
        return None

    return resp.json()


cluster = kubernetes.subparser("cluster", help="Manage Kubernetes clusters")


class ClusterTableList(BaseTable):
    state = Cell("status.state")


class ClusterTable(ClusterTableList):
    reason = Cell("status.reason", formatter=dict_formatter)

    custom_resources = Cell("spec.custom_resources")
    metrics = Cell("spec.metrics")
    failing_metrics = Cell("status.metrics_reasons", formatter=dict_formatter)

    label_constraints = Cell("spec.constraints.cloud.labels", name="label constraints")
    metric_constraints = Cell(
        "spec.constraints.cloud.metrics", name="metric constraints"
    )
    scheduled_to = Cell("status.scheduled_to")
    scheduled = Cell("status.scheduled", formatter=format_datetime)
    running_on = Cell("status.running_on")


class ClusterTableDetail(ClusterTable):
    nodes = Cell("status.nodes", formatter=nodes_formatter)
    nodes_pid_pressure = Cell(
        "status.nodes", formatter=partial(nodes_formatter, pid_pressure=True)
    )
    nodes_memory_pressure = Cell(
        "status.nodes", formatter=partial(nodes_formatter, memory_pressure=True)
    )
    nodes_disk_pressure = Cell(
        "status.nodes", formatter=partial(nodes_formatter, disk_pressure=True)
    )
    backoff = Cell("spec.backoff")
    backoff_delay = Cell("spec.backoff_delay")
    backoff_limit = Cell("spec.backoff_limit")


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


@cluster.command("register", help="Register an existing Kubernetes cluster")
@argument(
    "--context", "-c", help="Name of the context inside the kubeconfig file to use."
)
@argument(
    "-k",
    "--kubeconfig",
    type=FileType(),
    required=True,
    help="Kubeconfig file that should be used to control this cluster",
)
@arg_custom_resources
@arg_metric
@arg_global_metric
@arg_namespace
@arg_labels
@arg_formatting
@arg_config
@arg_backoff
@arg_backoff_delay
@arg_backoff_limit
@depends("config", "session")
@printer(table=ClusterTable(many=False))
def register_cluster(
    config,
    session,
    namespace,
    kubeconfig,
    context,
    metrics,
    global_metrics,
    labels,
    custom_resources,
    backoff,
    backoff_delay,
    backoff_limit,
):
    if namespace is None:
        namespace = config["user"]

    cluster_config, cluster_name = create_cluster_config(kubeconfig, context)

    to_register = {
        "metadata": {"name": cluster_name, "labels": labels},
        "spec": {
            "kubeconfig": cluster_config,
            "metrics": metrics + global_metrics,
            "custom_resources": custom_resources,
            "backoff": backoff,
            "backoff_delay": backoff_delay,
            "backoff_limit": backoff_limit,
            "constraints": {
                "cloud": {
                    "labels": [],
                    "metrics": [],
                },
            },
        },
    }

    resp = session.post(
        f"/kubernetes/namespaces/{namespace}/clusters", json=to_register
    )

    return resp.json()


@cluster.command("create", help="Create Kubernetes cluster")
@argument("name", help="Kubernetes cluster name")
@argument(
    "-f",
    "--file",
    type=FileType(),
    required=True,
    help="TOSCA template file that describes desired Kubernetes cluster",
)
@arg_custom_resources
@arg_metric
@arg_global_metric
@arg_metric_inheritance
@arg_namespace
@arg_labels
@arg_label_inheritance
@arg_cloud_label_constraints
@arg_cloud_metric_constraints
@arg_formatting
@arg_config
@arg_backoff
@arg_backoff_delay
@arg_backoff_limit
@depends("config", "session")
@printer(table=ClusterTable(many=False))
def create_cluster(
    name,
    file,
    config,
    session,
    namespace,
    metrics,
    global_metrics,
    inherit_metrics,
    labels,
    inherit_labels,
    cloud_label_constraints,
    cloud_metric_constraints,
    custom_resources,
    backoff,
    backoff_delay,
    backoff_limit,
):
    if namespace is None:
        namespace = config["user"]

    to_create = {
        "metadata": {
            "name": name,
            "labels": labels,
            "inherit_labels": inherit_labels
        },
        "spec": {
            "tosca": yaml.safe_load(file),
            "metrics": metrics + global_metrics,
            "inherit_metrics": inherit_metrics,
            "custom_resources": custom_resources,
            "backoff": backoff,
            "backoff_delay": backoff_delay,
            "backoff_limit": backoff_limit,
            "constraints": {
                "cloud": {
                    "labels": cloud_label_constraints,
                    "metrics": cloud_metric_constraints,
                },
            },
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
@arg_config
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
@arg_config
@depends("config", "session")
@printer(table=ClusterTableDetail())
def get_cluster(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/kubernetes/namespaces/{namespace}/clusters/{name}")
    data = resp.json()

    if ((("inherit_metrics" in data['spec'] and data['spec']['inherit_metrics']) or
         data['spec']['constraints']['cloud']['metrics']) or
        (("inherit_labels" in data['spec'] and data['metadata']['inherit_labels']) or
         data['spec']['constraints']['cloud']['labels'])) and \
       data['status']['scheduled_to']:
        if data['status']['scheduled_to']['namespace']:
            cloud = session.get(
                f"/infrastructure/namespaces/"
                f"{data['status']['scheduled_to']['namespace']}"
                f"/clouds/{data['status']['scheduled_to']['name']}"
            ).json()
        else:
            cloud = session.get(
                f"/infrastructure/globalclouds/{data['status']['scheduled_to']['name']}"
            ).json()

        inherited_labels = dict()
        if data['metadata']['inherit_labels']:
            for label in cloud['metadata']['labels']:
                inherited_labels[label] = \
                    cloud['metadata']['labels'][label] + " (inherited)"
            if data['spec']['constraints']['cloud']['labels']:
                for constraint in data['spec']['constraints']['cloud']['labels']:
                    for label in cloud['metadata']['labels']:
                        if label in constraint:
                            inherited_labels[label] = \
                                cloud['metadata']['labels'][label] + " (inherited)"
        data['metadata']['labels'] = {**data['metadata']['labels'], **inherited_labels}

        inherited_metrics = list()
        if data['spec']['inherit_metrics']:
            for metric in cloud['spec'][cloud['spec']['type']]['metrics']:
                metric["inherited"] = True
                inherited_metrics.append(metric)

        if data['spec']['constraints']['cloud']['metrics']:
            for constraint in data['spec']['constraints']['cloud']['metrics']:
                for metric in cloud['spec'][cloud['spec']['type']]['metrics']:
                    if metric["name"] in constraint:
                        metric["inherited"] = True
                        inherited_metrics.append(metric)

        data['spec']['metrics'] += inherited_metrics

    return data


@cluster.command(
    "update", help="Update a Kubernetes cluster. By default, new metrics, labels, \
    cloud label constraints and cloud metric constraints                        \
    will be appended. To remove previous values, use with                       \
    --remove-existing-{FIELD_NAME}")
@argument("name", help="Kubernetes cluster name")
@argument("-k", "--kubeconfig", type=FileType(), help="Kubernetes kubeconfig file")
@argument(
    "--context", "-c", help="Name of the context inside the kubeconfig file to use."
)
@argument(
    "-f",
    "--file",
    type=FileType(),
    help="TOSCA template file that describes desired Kubernetes cluster",
)
@argument(
    "--remove-existing-labels",
    action='store_true',
    help="remove currently existing labels"
)
@argument(
    "--remove-existing-metrics",
    action='store_true',
    help="remove currently existing metrics"
)
@argument(
    "--remove-existing-cloud-label-constraints",
    action='store_true',
    help="remove currently existing label constraints"
)
@argument(
    "--remove-existing-cloud-metric-constraints",
    action='store_true',
    help="remove currently existing metric constraints"
)
@arg_custom_resources
@arg_metric
@arg_global_metric
@arg_namespace
@arg_formatting
@arg_config
@arg_labels
@arg_backoff
@arg_backoff_delay
@arg_backoff_limit
@arg_cloud_label_constraints
@arg_cloud_metric_constraints
@depends("config", "session")
@printer(table=ClusterTable())
def update_cluster(
    config,
    session,
    name,
    namespace,
    kubeconfig,
    context,
    file,
    metrics,
    global_metrics,
    remove_existing_metrics,
    labels,
    remove_existing_labels,
    cloud_label_constraints,
    remove_existing_cloud_label_constraints,
    cloud_metric_constraints,
    remove_existing_cloud_metric_constraints,
    custom_resources,
    backoff,
    backoff_delay,
    backoff_limit,
):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/kubernetes/namespaces/{namespace}/clusters/{name}")
    to_update = resp.json()

    if file:
        to_update["spec"]["tosca"] = yaml.safe_load(file)
    if kubeconfig:
        to_update["spec"]["kubeconfig"], _ = create_cluster_config(kubeconfig, context)
    if remove_existing_labels:
        to_update["metadata"]["labels"] = {}
    if labels:
        to_update["metadata"]["labels"].update(labels)
    if remove_existing_metrics:
        to_update["spec"]["metrics"] = []
    if metrics or global_metrics:
        for metric in metrics+global_metrics:
            if metric not in to_update["spec"]["metrics"]:
                to_update["spec"]["metrics"] += [metric]
    if custom_resources:
        to_update["spec"]["custom_resources"] = custom_resources
    if remove_existing_cloud_label_constraints:
        to_update["spec"]["constraints"]["cloud"]["labels"] = []
    if cloud_label_constraints:
        to_update["spec"]["constraints"]["cloud"]["labels"] += cloud_label_constraints
    if remove_existing_cloud_metric_constraints:
        to_update["spec"]["constraints"]["cloud"]["metrics"] = []
    if cloud_metric_constraints:
        to_update["spec"]["constraints"]["cloud"]["metrics"] += cloud_metric_constraints
    if backoff:
        to_update["spec"]["backoff"] = backoff
    if backoff_delay:
        to_update["spec"]["backoff_delay"] = backoff_delay
    if backoff_limit:
        to_update["spec"]["backoff_limit"] = backoff_limit
    resp = session.put(
        f"/kubernetes/namespaces/{namespace}/clusters/{name}", json=to_update
    )

    return resp.json()


@cluster.command("delete", help="Delete Kubernetes cluster")
@argument("name", help="Kubernetes cluster name")
@argument(
    "--force",
    dest="force",
    action="store_true",
    help="Force delete Kubernetes cluster from Krake",
)
@arg_namespace
@arg_formatting
@arg_config
@depends("config", "session")
@printer(table=ClusterTable())
def delete_cluster(config, session, namespace, name, force):
    if namespace is None:
        namespace = config["user"]
    resp = session.delete(
        f"/kubernetes/namespaces/{namespace}/clusters/{name}", params={"force": force}
    )

    if resp.status_code == 204:
        return None
    return resp.json()
