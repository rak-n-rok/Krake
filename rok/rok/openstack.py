"""OpenStack subcommands

.. code:: bash

    python -m rok openstack --help

"""
import os

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

openstack = ParserSpec("openstack", aliases=["os"], help="Manage OpenStack resources")

project = openstack.subparser("project", help="Manage OpenStack projects")


class ProjectTable(BaseTable):
    url = Cell("spec.url")
    template = Cell("spec.template")


@project.command("list", help="List OpenStack projects")
@argument(
    "-a", "--all", action="store_true", help="Show OpenStack projects in all namespaces"
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ProjectTable(many=True))
def list_projects(config, session, namespace, all):
    if all:
        url = f"/openstack/projects"
    else:
        if namespace is None:
            namespace = config["user"]
        url = f"/openstack/namespaces/{namespace}/projects"
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@project.command("create", help="Create OpenStack project")
@argument("--auth-url", help="URL to OpenStack identity service (Keystone)")
@argument(
    "--application-credential",
    nargs=2,
    help="OpenStack a1uthentication credential and secret",
)
@argument("--user-id", help="UUID of OpenStack user")
@argument("--password", help="Password of OpenStack user")
@argument("--project-id", help="UUID of OpenStack project")
@argument("--template", help="UUID of Magnum cluster template", required=True)
@argument("name", help="Name of the project")
@arg_formatting
@arg_namespace
@arg_labels
@arg_metric
@depends("config", "session")
@printer(table=ProjectTable())
def create_project(
    config,
    session,
    template,
    auth_url,
    application_credential,
    user_id,
    password,
    project_id,
    name,
    namespace,
    labels,
    metrics,
):
    if namespace is None:
        namespace = config["user"]

    if application_credential:
        auth = {
            "type": "application_credential",
            "application_credential": {
                "id": application_credential[0],
                "secret": application_credential[1],
            },
        }
    else:
        try:
            if user_id is None:
                user_id = os.environ["OS_USER_ID"]
            if password is None:
                password = os.environ["OS_PASSWORD"]
            if project_id is None:
                project_id = os.environ["OS_PROJECT_ID"]
        except KeyError as err:
            missing = err.args[0]
            raise SystemExit(f"Error: Environment variable '{missing}' is missing.")

        auth = {
            "type": "password",
            "password": {
                "user": {"id": user_id, "password": password},
                "project": {"id": project_id},
            },
        }

    if auth_url is None:
        auth_url = os.environ["OS_AUTH_URL"]

    project = {
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "url": auth_url,
            "auth": auth,
            "template": template,
            "metrics": metrics,
        },
    }
    resp = session.post(f"/openstack/namespaces/{namespace}/projects", json=project)
    return resp.json()


@project.command("get", help="Get OpenStack project")
@argument("name", help="OpenStack project name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ProjectTable())
def get_project(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/openstack/namespaces/{namespace}/projects/{name}", raise_for_status=False
    )
    if resp.status_code == 404:
        print(f"Error: OpenStack project {name!r} not found")
        raise SystemExit(1)

    resp.raise_for_status()
    return resp.json()


@project.command("update", help="Update OpenStack project")
@argument("name", help="OpenStack project name")
@argument("--auth-url", help="URL to OpenStack identity service (Keystone)")
@argument(
    "--application-credential",
    nargs=2,
    help="OpenStack authentication credential and secret",
)
@argument("--user-id", help="UUID of OpenStack user")
@argument("--password", help="Password of OpenStack user")
@argument("--project-id", help="UUID of OpenStack project")
@argument("--template", help="UUID of Magnum cluster template")
@arg_namespace
@arg_labels
@arg_metric
@depends("config", "session")
@printer(table=ProjectTable())
def update_project(
    config,
    session,
    namespace,
    name,
    auth_url,
    application_credential,
    user_id,
    password,
    project_id,
    template,
    labels,
    metrics,
):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/openstack/namespaces/{namespace}/projects/{name}", raise_for_status=False
    )
    project = resp.json()

    if application_credential:
        project["spec"]["auth"] = {
            "type": "application_credential",
            "application_credential": {
                "id": application_credential[0],
                "secret": application_credential[1],
            },
        }
    else:
        try:
            if user_id is None:
                user_id = os.environ["OS_USER_ID"]
            if password is None:
                password = os.environ["OS_PASSWORD"]
            if project_id is None:
                project_id = os.environ["OS_PROJECT_ID"]
        except KeyError as err:
            missing = err.args[0]
            raise SystemExit(f"Error: Environment variable '{missing}' is missing.")

        project["spec"]["auth"] = {
            "type": "password",
            "password": {
                "user": {"id": user_id, "password": password},
                "project": {"id": project_id},
            },
        }

    if template is not None:
        project["spec"]["template"] = template

    if auth_url is not None:
        project["spec"]["url"] = auth_url

    if labels:
        project["metadata"]["labels"] = labels

    if metrics:
        project["spec"]["metrics"] = metrics

    resp = session.put(
        f"/openstack/namespaces/{namespace}/projects/{name}", json=project
    )
    return resp.json()


@project.command("delete", help="Delete OpenStack project")
@argument("name", help="OpenStack project name")
@arg_formatting
@arg_namespace
@depends("config", "session")
@printer(table=ProjectTable())
def delete_project(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.delete(f"/openstack/namespaces/{namespace}/projects/{name}")
    if resp.status_code == 204:
        return None
    return resp.json()


cluster = openstack.subparser("cluster", help="Manage Magnum clusters")


arg_project_label_constraints = argument(
    "-L",
    "--project-label-constraint",
    dest="project_label_constraints",
    default=[],
    action="append",
    help=(
        "Constraint for labels of the OpenStack project. "
        "Can be specified multiple times"
    ),
)


class ClusterListTable(BaseTable):
    state = Cell("status.state")


class ClusterTable(ClusterListTable):
    reason = Cell("status.reason", formatter=dict_formatter)
    master = Cell("status.master_addresses")
    nodes = Cell("status.node_addresses")
    project = Cell("status.project.name")


@cluster.command("create", help="Create Magnum cluster")
@argument("name", help="Name of the project")
@arg_formatting
@arg_namespace
@arg_labels
@arg_metric
@arg_project_label_constraints
@argument("--master-count", type=int, help="Number of master nodes")
@argument("--node-count", type=int, help="Number of worker nodes")
@depends("config", "session")
@printer(table=ClusterTable())
def create_cluster(
    config,
    session,
    namespace,
    name,
    labels,
    metrics,
    project_label_constraints,
    master_count,
    node_count,
):
    if namespace is None:
        namespace = config["user"]

    cluster = {
        "metadata": {
            "name": name,
            "labels": labels,
            "constraints": {"project": {"labels": project_label_constraints}},
        },
        "spec": {
            "master_count": master_count,
            "node_count": node_count,
            "metrics": metrics,
        },
    }
    resp = session.post(
        f"/openstack/namespaces/{namespace}/magnumclusters",
        json=cluster,
        raise_for_status=False,
    )
    return resp.json()


@cluster.command("list", help="List Magnum clusters")
@argument(
    "-a", "--all", action="store_true", help="Show applications in all namespaces"
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterListTable(many=True))
def list_clusters(config, session, namespace, all):
    if all:
        url = "/openstack/magnumclusters"
    else:
        if namespace is None:
            namespace = config["user"]
        url = f"/openstack/namespaces/{namespace}/magnumclusters"
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@cluster.command("get", help="Get Magnum cluster")
@argument("name", help="Magnum cluster name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable())
def get_cluster(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/openstack/namespaces/{namespace}/magnumclusters/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        print(f"Error: Magnum cluster {name!r} not found")
        raise SystemExit(1)

    resp.raise_for_status()
    return resp.json()


@cluster.command("update", help="Update Magnum cluster")
@argument("name", help="Magnum cluster name")
@argument("--node-count", type=int, help="Number of worker nodes")
@arg_namespace
@arg_metric
@arg_project_label_constraints
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable())
def update_cluster(
    config, session, namespace, name, metrics, project_label_constraints, node_count
):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/openstack/namespaces/{namespace}/magnumclusters/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        print(f"Error: Magnum cluster {name!r} not found")
        raise SystemExit(1)
    resp.raise_for_status()
    cluster = resp.json()

    if node_count is not None:
        cluster["spec"]["node_count"] = node_count

    if metrics:
        cluster["spec"]["metrics"] = metrics

    if project_label_constraints:
        if cluster["spec"]["constraints"] is None:
            cluster["spec"]["constraints"] = {}
        if cluster["spec"]["constraints"].get("project") is None:
            cluster["spec"]["constraints"]["project"] = {}
        cluster["spec"]["constraints"]["project"]["labels"] = project_label_constraints

    resp = session.put(
        f"/openstack/namespaces/{namespace}/magnumclusters/{name}", json=cluster
    )
    return resp.json()


@cluster.command("delete", help="Delete Magnum cluster")
@argument(
    "--cascade",
    help="Delete the cluster and all dependent resources",
    action="store_true",
)
@argument("name", help="Magnum cluster name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=ClusterTable())
def delete_cluster(config, session, namespace, name, cascade):
    if namespace is None:
        namespace = config["user"]

    url = f"/openstack/namespaces/{namespace}/magnumclusters/{name}"
    if cascade:
        url = f"{url}?cascade"

    resp = session.delete(url)
    if resp.status_code == 204:
        return None
    return resp.json()
