"""infrastructure subcommands

.. code:: bash

    python -m rok infrastructure --help

"""
import sys
import getpass

from enum import Enum

from .parser import (
    ParserSpec,
    argument,
    arg_namespace,
    arg_formatting,
    arg_metric,
    arg_global_metric,
    arg_labels,
)
from .fixtures import depends
from .formatters import (
    BaseTable,
    Cell,
    printer,
)

from .helpers import wrap_labels

# Parsers
infrastructure = ParserSpec(
    "infrastructure", aliases=["infra"], help="Manage infrastructure resources"
)

global_infrastructure_provider = infrastructure.subparser(
    "globalinfrastructureprovider",
    aliases=["gprovider", "gip"],
    help="Manage global infrastructure providers",
)
infrastructure_provider = infrastructure.subparser(
    "infrastructureprovider",
    aliases=["provider", "ip"],
    help="Manage infrastructure providers",
)
global_cloud = infrastructure.subparser(
    "globalcloud", aliases=["gcloud", "gc"], help="Manage global clouds"
)
cloud = infrastructure.subparser("cloud", help="Manage clouds")


# ################ Managing global infrastructure providers


class InfrastructureProviderType(str, Enum):
    IM = "im"


class InfrastructureProviderListTable(BaseTable):
    # TODO: Infrastructure provider `spec` is instance of
    #  :class:`PolymorphicContainer` that is defined by :attr:`type`.
    #  Hence, the :class:`Cell` should be modified to accept e.g.
    #  "wildcard attributes" ("spec.*.url") when some nested
    #  attribute with polymorphic parent should be displayed
    #  in the table.
    #  YAGNI for now.
    type = Cell("spec.type")
    url = Cell("spec.im.url")


class InfrastructureProviderTable(InfrastructureProviderListTable):
    pass


@global_infrastructure_provider.command(
    "list", help="List global infrastructure providers"
)
@arg_formatting
@depends("session")
@printer(table=InfrastructureProviderListTable(many=True))
def list_globalinfrastructureproviders(session):
    resp = session.get("/infrastructure/globalinfrastructureproviders")
    body = resp.json()
    return body["items"]


@global_infrastructure_provider.command(
    "register", help="Register global infrastructure provider"
)
@argument(
    "--type",
    dest="ip_type",
    required=True,
    help="Global infrastructure provider type. Valid types: "
    f"{', '.join([t.value for t in InfrastructureProviderType])}",
)
@argument(
    "--url",
    required=True,
    help="Global infrastructure provider API url. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--username",
    help="Global infrastructure provider API username. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--password",
    required=False,
    help="Global infrastructure provider API password. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--token",
    help=f"Global infrastructure provider API token. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument("name", help="Name of the infrastructure provider")
@arg_formatting
@depends("session")
@printer(table=InfrastructureProviderTable())
def register_globalinfrastructureprovider(
    session,
    ip_type,
    url,
    username,
    password,
    token,
    name,
):
    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please set your Infrastructure Provider '
                                          'password: ')
    if ip_type == InfrastructureProviderType.IM:
        provider = {
            "api": "infrastructure",
            "kind": "GlobalInfrastructureProvider",
            "metadata": {
                "name": name,
                "labels": [],
                "deletion_state": {"deleted": False}
            },
            "spec": {
                "type": "im",
                "im": {
                    "url": url,
                    "username": username,
                    "password": password,
                    "token": token,
                },
            },
        }
    else:
        sys.exit(f"Error: Unsupported global infrastructure provider type: '{ip_type}'")

    resp = session.post(
        "/infrastructure/globalinfrastructureproviders",
        json=provider,
    )
    return resp.json()


@global_infrastructure_provider.command(
    "get", help="Get global infrastructure provider"
)
@argument("name", help="Global infrastructure provider name")
@arg_formatting
@depends("session")
@printer(table=InfrastructureProviderTable())
def get_globalinfrastructureprovider(session, name):
    resp = session.get(f"/infrastructure/globalinfrastructureproviders/{name}")
    return resp.json()


@global_infrastructure_provider.command(
    "update", help="Update global infrastructure provider"
)
@argument("name", help="Global infrastructure provider name")
@argument(
    "--url",
    help="Global infrastructure provider API url. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--username",
    help="Global infrastructure provider API username. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--password",
    required=False,
    help="Global infrastructure provider API password. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--token",
    help=f"Global infrastructure provider API token. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@arg_formatting
@depends("session")
@printer(table=InfrastructureProviderTable())
def update_globalinfrastructureprovider(
    session,
    name,
    url,
    username,
    password,
    token,
):
    resp = session.get(f"/infrastructure/globalinfrastructureproviders/{name}")
    provider = resp.json()

    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please enter your Infrastructure Provider '
                                          'password: ')
    provider["spec"]["im"]["password"] = password

    if provider["spec"]["type"] == InfrastructureProviderType.IM:
        if url:
            provider["spec"]["im"]["url"] = url
        if username:
            provider["spec"]["im"]["username"] = username
        if token:
            provider["spec"]["im"]["token"] = token

    resp = session.put(
        f"/infrastructure/globalinfrastructureproviders/{name}",
        json=provider,
    )
    return resp.json()


@global_infrastructure_provider.command(
    "delete", help="Delete global infrastructure provider"
)
@argument("name", help="Global infrastructure provider name")
@arg_formatting
@depends("session")
@printer(table=InfrastructureProviderTable())
def delete_globalinfrastructureprovider(session, name):
    resp = session.delete(
        f"/infrastructure/globalinfrastructureproviders/{name}",
    )

    if resp.status_code == 204:
        return None

    return resp.json()


# ################ Managing infrastructure providers


@infrastructure_provider.command("list", help="List infrastructure providers")
@argument(
    "-a",
    "--all",
    action="store_true",
    help="Show infrastructure providers in all namespaces",
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=InfrastructureProviderListTable(many=True))
def list_infrastructureproviders(config, session, namespace, all):
    if all:
        url = "/infrastructure/infrastructureproviders"
    else:
        if namespace is None:
            namespace = config["user"]
        url = f"/infrastructure/namespaces/{namespace}/infrastructureproviders"
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@infrastructure_provider.command("register", help="Register infrastructure provider")
@argument(
    "--type",
    dest="ip_type",
    required=True,
    help="Infrastructure provider type. Valid types: "
    f"{', '.join([t.value for t in InfrastructureProviderType])}",
)
@argument(
    "--url",
    required=True,
    help="Infrastructure provider API url. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--username",
    help="Infrastructure provider API username. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--password",
    required=False,
    help="Infrastructure provider API password. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--token",
    help=f"Infrastructure provider API token. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument("name", help="Name of the infrastructure provider")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=InfrastructureProviderTable())
def register_infrastructureprovider(
    config,
    session,
    namespace,
    ip_type,
    url,
    username,
    password,
    token,
    name,
):
    if namespace is None:
        namespace = config["user"]

    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please set your Infrastructure Provider '
                                          'password: ')
    if ip_type == InfrastructureProviderType.IM:
        provider = {
            "api": "infrastructure",
            "kind": "InfrastructureProvider",
            "metadata": {
                "name": name,
                "labels": [],
                "deletion_state": {"deleted": False}
            },
            "spec": {
                "type": "im",
                "im": {
                    "url": url,
                    "username": username,
                    "password": password,
                    "token": token,
                },
            },
        }
    else:
        sys.exit(f"Error: Unsupported infrastructure provider type: '{ip_type}'")

    resp = session.post(
        f"/infrastructure/namespaces/{namespace}/infrastructureproviders",
        json=provider,
    )
    return resp.json()


@infrastructure_provider.command("get", help="Get infrastructure provider")
@argument("name", help="Infrastructure provider name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=InfrastructureProviderTable())
def get_infrastructureprovider(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}"
    )
    return resp.json()


@infrastructure_provider.command("update", help="Update infrastructure provider")
@argument("name", help="Infrastructure provider name")
@argument(
    "--url",
    help="Metrics provider API url. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--username",
    help="Infrastructure provider API username. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--password",
    required=False,
    help="Infrastructure provider API password. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@argument(
    "--token",
    help=f"Infrastructure provider API token. "
    f"Valid together with --type {InfrastructureProviderType.IM.value}.",
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=InfrastructureProviderTable())
def update_infrastructureprovider(
    config,
    session,
    namespace,
    name,
    url,
    username,
    password,
    token,
):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(
        f"/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}"
    )
    provider = resp.json()

    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please enter your Infrastructure Provider '
                                          'password: ')
    provider["spec"]["im"]["password"] = password

    if provider["spec"]["type"] == InfrastructureProviderType.IM:
        if url:
            provider["spec"]["im"]["url"] = url
        if username:
            provider["spec"]["im"]["username"] = username
        if token:
            provider["spec"]["im"]["token"] = token

    resp = session.put(
        f"/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}",
        json=provider,
    )
    return resp.json()


@infrastructure_provider.command("delete", help="Delete infrastructure provider")
@argument("name", help="Infrastructure provider name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=InfrastructureProviderTable())
def delete_infrastructureprovider(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.delete(
        f"/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}",
    )

    if resp.status_code == 204:
        return None

    return resp.json()


# ################ Managing global clouds


class CloudType(str, Enum):
    OPENSTACK = "openstack"


class CloudListTable(BaseTable):
    # TODO: Cloud `spec` is instance of
    #  :class:`PolymorphicContainer` that is defined by :attr:`type`.
    #  Hence, the :class:`Cell` should be modified to accept e.g.
    #  "wildcard attributes" ("spec.*.metrics") when some nested
    #  attribute with polymorphic parent should be displayed
    #  in the table.
    #  YAGNI for now.
    type = Cell("spec.type")
    metrics = Cell("spec.openstack.metrics")
    infra_provider = Cell("spec.openstack.infrastructure_provider.name")
    state = Cell("status.state")


class CloudTable(CloudListTable):
    pass


@global_cloud.command("list", help="List global clouds")
@arg_formatting
@depends("session")
@printer(table=CloudListTable(many=True))
def list_globalclouds(session):
    resp = session.get("/infrastructure/globalclouds")
    body = resp.json()
    return body["items"]


@global_cloud.command("register", help="Register global cloud")
@argument(
    "--type",
    dest="cloud_type",
    required=True,
    help="Global cloud type. Valid types: "
    f"{', '.join([t.value for t in CloudType])}",
)
@argument(
    "--global-infra-provider",
    required=True,
    help="Global infrastructure provider name for cloud management.",
)
@argument(
    "--url",
    required=True,
    help="URL to OpenStack identity service (Keystone). "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--username",
    required=True,
    help="Username or UUID of OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--password",
    required=False,
    help="Password of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--project",
    required=True,
    help="Name or UUID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--domain-name",
    help="Domain name of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
    default="Default",
)
@argument(
    "--domain-id",
    help="Domain ID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
    default="default",
)
@argument("name", help="Global cloud name")
@arg_global_metric
@arg_labels
@arg_formatting
@depends("session")
@printer(table=CloudTable())
def register_globalcloud(
    session,
    cloud_type,
    url,
    username,
    domain_name,
    project,
    domain_id,
    password,
    global_infra_provider,
    global_metrics,
    labels,
    name,
):
    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please enter your Cloud password: ')

    if cloud_type == CloudType.OPENSTACK:
        cloud_resource = {
            "api": "infrastructure",
            "kind": "GlobalCloud",
            "metadata": {
                "name": name,
                "deletion_state": {"deleted": False},
                "labels": wrap_labels(labels),
            },
            "spec": {
                "type": "openstack",
                "openstack": {
                    "url": url,
                    "metrics": global_metrics,
                    "infrastructure_provider": {
                        "name": global_infra_provider,
                        "namespaced": False,
                    },
                    "auth": {
                        "type": "password",
                        "password": {
                            "version": "3",
                            "user": {
                                "username": username,
                                "password": password,
                                "domain_name": domain_name,
                            },
                            "project": {
                                "name": project,
                                "domain_id": domain_id,
                            },
                        },
                    },
                },
            },
        }
    else:
        sys.exit(f"Error: Unsupported global cloud type: '{cloud_type}'")

    resp = session.post(
        "/infrastructure/globalclouds",
        json=cloud_resource,
    )
    return resp.json()


@global_cloud.command("get", help="Get global cloud")
@argument("name", help="Global cloud name")
@arg_formatting
@depends("session")
@printer(table=CloudTable())
def get_globalcloud(session, name):
    resp = session.get(f"/infrastructure/globalclouds/{name}")
    return resp.json()


@global_cloud.command("update", help="Update global cloud")
@argument("name", help="Global cloud name")
@argument(
    "--global-infra-provider",
    help="Global infrastructure provider name for cloud management.",
)
@argument(
    "--url",
    help="URL to OpenStack identity service (Keystone). "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--username",
    help="Username or UUID of OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--password",
    required=False,
    help="Password of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--domain-name",
    help="Domain name of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--project",
    help="Name or UUID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--domain-id",
    help="Domain ID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@arg_global_metric
@arg_labels
@arg_formatting
@depends("session")
@printer(table=CloudTable())
def update_globalcloud(
    session,
    name,
    url,
    username,
    password,
    domain_name,
    project,
    domain_id,
    global_infra_provider,
    global_metrics,
    labels,
):
    resp = session.get(f"/infrastructure/globalclouds/{name}")
    cloud_resource = resp.json()

    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please enter your Cloud password: ')
    cloud_resource["metadata"]["password"] = password

    if cloud_resource["spec"]["type"] == CloudType.OPENSTACK:
        if labels:
            cloud_resource["metadata"]["labels"] = wrap_labels(labels)
        if url:
            cloud_resource["spec"]["openstack"]["url"] = url
        if global_metrics:
            cloud_resource["spec"]["openstack"]["metrics"] = global_metrics
        if username:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["user"][
                "username"
            ] = username
        if domain_name:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["user"][
                "domain_name"
            ] = domain_name
        if project:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["project"][
                "name"
            ] = project
        if domain_id:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["project"][
                "domain_id"
            ] = domain_id
        if global_infra_provider:
            cloud_resource["spec"]["openstack"]["infrastructure_provider"][
                "name"
            ] = global_infra_provider
            cloud_resource["spec"]["openstack"]["infrastructure_provider"][
                "namespaced"
            ] = False

    resp = session.put(
        f"/infrastructure/globalclouds/{name}",
        json=cloud_resource,
    )
    return resp.json()


@global_cloud.command("delete", help="Delete global cloud")
@argument("name", help="Global cloud name")
@arg_formatting
@depends("session")
@printer(table=CloudTable())
def delete_globalcloud(session, name):
    resp = session.delete(
        f"/infrastructure/globalclouds/{name}",
    )

    if resp.status_code == 204:
        return None

    return resp.json()


# ################ Managing clouds


@cloud.command("list", help="List clouds")
@argument("-a", "--all", action="store_true", help="Show clouds in all namespaces")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=CloudListTable(many=True))
def list_clouds(config, session, namespace, all):
    if all:
        url = "/infrastructure/clouds"
    else:
        if namespace is None:
            namespace = config["user"]
        url = f"/infrastructure/namespaces/{namespace}/clouds"
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@cloud.command("register", help="Register cloud")
@argument(
    "--type",
    dest="cloud_type",
    required=True,
    help="Cloud type. Valid types: " f"{', '.join([t.value for t in CloudType])}",
)
@argument("--infra-provider", help="Infrastructure provider name for cloud management.")
@argument(
    "--global-infra-provider",
    help="Global infrastructure provider name for cloud management.",
)
@argument(
    "--url",
    required=True,
    help="URL to OpenStack identity service (Keystone). "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--username",
    required=True,
    help="Username or UUID of OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--password",
    required=False,
    help="Password of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--project",
    required=True,
    help="Name or UUID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--domain-name",
    help="Domain name of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
    default="Default",
)
@argument(
    "--domain-id",
    help="Domain ID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
    default="default",
)
@argument("name", help="Cloud name")
@arg_metric
@arg_global_metric
@arg_labels
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=CloudTable())
def register_cloud(
    config,
    session,
    namespace,
    cloud_type,
    url,
    username,
    password,
    domain_name,
    project,
    domain_id,
    infra_provider,
    global_infra_provider,
    metrics,
    global_metrics,
    labels,
    name,
):
    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please enter your OpenStack password: ')

    if infra_provider and global_infra_provider:
        sys.exit(
            "Error: Cloud should be associated only with one infrastructure provider."
            " Use one from infrastructure provider or global infrastructure provider "
            " options."
        )

    if not infra_provider and not global_infra_provider:
        sys.exit(
            "Error: Cloud should be associated with an infrastructure provider."
            " Use infrastructure provider or global infrastructure provider options."
        )

    if namespace is None:
        namespace = config["user"]

    if cloud_type == CloudType.OPENSTACK:
        cloud_resource = {
            "api": "infrastructure",
            "kind": "Cloud",
            "metadata": {
                "name": name,
                "labels": wrap_labels(labels),
                "deletion_state": {"deleted": False}
            },
            "spec": {
                "type": "openstack",
                "openstack": {
                    "url": url,
                    "metrics": metrics + global_metrics,
                    "infrastructure_provider": {
                        "name": infra_provider or global_infra_provider,
                        "namespaced": True if infra_provider else False,
                    },
                    "auth": {
                        "type": "password",
                        "password": {
                            "version": "3",
                            "user": {
                                "username": username,
                                "password": password,
                                "domain_name": domain_name,
                            },
                            "project": {
                                "name": project,
                                "domain_id": domain_id,
                            },
                        },
                    },
                },
            },
        }
    else:
        sys.exit(f"Error: Unsupported cloud type: '{cloud_type}'")

    resp = session.post(
        f"/infrastructure/namespaces/{namespace}/clouds",
        json=cloud_resource,
    )
    return resp.json()


@cloud.command("get", help="Get cloud")
@argument("name", help="Cloud name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=CloudTable())
def get_cloud(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/infrastructure/namespaces/{namespace}/clouds/{name}")
    return resp.json()


@cloud.command("update", help="Update cloud")
@argument("name", help="Cloud name")
@argument("--infra-provider", help="Infrastructure provider name for cloud management.")
@argument(
    "--global-infra-provider",
    help="Global infrastructure provider name for cloud management.",
)
@argument(
    "--url",
    help="URL to OpenStack identity service (Keystone). "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--username",
    help="Username or UUID of OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--password",
    required=False,
    help="Password of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--domain-name",
    help="Domain name of the OpenStack user. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--project",
    help="Name or UUID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@argument(
    "--domain-id",
    help="Domain ID of the OpenStack project. "
    f"Valid together with --type {CloudType.OPENSTACK.value}.",
)
@arg_metric
@arg_global_metric
@arg_labels
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=CloudTable())
def update_cloud(
    config,
    session,
    namespace,
    name,
    password,
    url,
    username,
    domain_name,
    project,
    domain_id,
    infra_provider,
    global_infra_provider,
    metrics,
    global_metrics,
    labels,
):
    if infra_provider and global_infra_provider:
        sys.exit(
            "Error: Cloud should be associated only with one infrastructure provider."
            " Use one from infrastructure provider or global infrastructure provider"
            " options."
        )

    if namespace is None:
        namespace = config["user"]

    resp = session.get(f"/infrastructure/namespaces/{namespace}/clouds/{name}")
    cloud_resource = resp.json()

    if password:
        pass
    else:
        password = getpass.getpass(prompt='Please enter your Cloud password: ')
    cloud_resource["metadata"]["password"] = password

    if cloud_resource["spec"]["type"] == CloudType.OPENSTACK:
        if labels:
            cloud_resource["metadata"]["labels"] = wrap_labels(labels)
        if url:
            cloud_resource["spec"]["openstack"]["url"] = url
        if metrics or global_metrics:
            cloud_resource["spec"]["openstack"]["metrics"] = metrics + global_metrics
        if username:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["user"][
                "username"
            ] = username
        if domain_name:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["user"][
                "domain_name"
            ] = domain_name
        if project:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["project"][
                "name"
            ] = project
        if domain_id:
            cloud_resource["spec"]["openstack"]["auth"]["password"]["project"][
                "domain_id"
            ] = domain_id
        if infra_provider:
            cloud_resource["spec"]["openstack"]["infrastructure_provider"][
                "name"
            ] = infra_provider
        if infra_provider:
            cloud_resource["spec"]["openstack"]["infrastructure_provider"][
                "name"
            ] = infra_provider
            cloud_resource["spec"]["openstack"]["infrastructure_provider"][
                "namespaced"
            ] = True
        if global_infra_provider:
            cloud_resource["spec"]["openstack"]["infrastructure_provider"][
                "name"
            ] = global_infra_provider
            cloud_resource["spec"]["openstack"]["infrastructure_provider"][
                "namespaced"
            ] = False

    resp = session.put(
        f"/infrastructure/namespaces/{namespace}/clouds/{name}",
        json=cloud_resource,
    )
    return resp.json()


@cloud.command("delete", help="Delete cloud")
@argument("name", help="Cloud name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=CloudTable())
def delete_cloud(config, session, namespace, name):
    if namespace is None:
        namespace = config["user"]

    resp = session.delete(
        f"/infrastructure/namespaces/{namespace}/clouds/{name}",
    )

    if resp.status_code == 204:
        return None

    return resp.json()
