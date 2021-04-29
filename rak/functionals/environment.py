import os
from collections import defaultdict

from utils import KRAKE_HOMEDIR
from resource_definitions import (
    ClusterDefinition,
    ApplicationDefinition,
    ProjectDefinition,
    MagnumClusterDefinition,
)

GIT_DIR = "git/krake"
TEST_DIR = "rak/functionals"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
MANIFEST_PATH = f"{KRAKE_HOMEDIR}/{GIT_DIR}/{TEST_DIR}"
DEFAULT_MANIFEST = "echo-demo.yaml"
DEFAULT_KUBE_APP_NAME = "echo-demo"


def get_default_kubeconfig_path(cluster_name):
    """Return the default kubeconfig_path for the given cluster.

    Args:
        cluster_name (str): The name of a cluster

    Returns:
        str: The default path for the clusters kubeconfig file.

    """
    return os.path.join(CLUSTERS_CONFIGS, cluster_name)


def _convert_to_metrics_list(metrics):
    """Convert a dict of metrics names and weights as keys and values, into a list
    of dicts with the two keys "name" and "weight" as keys and the metrics name and
    metric weight as their corresponding values.

    Examples:
          metrics {"name1": 1.0, "name2": 2.0} results in the output
          [{"name": "name1", "weight": 1.0}, {"name": "name2", "weight": 2.0}]

    Args:
        metrics (dict[str, float]): metrics to convert

    Returns:
        list[dict[str, object]]: list of dicts with the two keys "name" and "weight" as
            keys and the metrics name and metric weight as their corresponding values.
    """
    metrics_list = []
    for metric_name, metric_weight in metrics.items():
        metrics_list.append({"name": metric_name, "weight": metric_weight})
    return metrics_list


class Environment(object):
    """Context manager to use for starting tests on a specific test environment. This
    environment will create the requested resources in the requested order when started.
    Actions can then be performed on the environment. Finally, all resources created are
    deleted in the reverse order of their creation.

    The structure of the environment is given using the ``resources`` parameter. This
    parameter should be a dict with the following syntax:

    {
        <priority 0>: [<resource A>, <resource_B>...],
        <priority 1>: [<resource C>, <resource_D>...],
    }

    priority:
        Priorities are integer. All resources with the highest priority (higher number)
        will be created first.

    resource lists:
        The resource lists are composed of instances of resource definitions (e.g
        :class:`ClusterDefinition`). All resources with the same priority will be
        created "at the same time", i.e. not concurrently, but between the ones with
        higher and the ones with lower priority.

        Note that the resources in these list do not need to have the same kind.

    To ensure that a resource is actually created or deleted, methods can be added to
    the resources definition, respectively ``check_created`` and ``check_deleted``.
    These methods are not meant to test the behavior of Krake, but simply to block the
    environment. When entering the context created by the :class:`Environment`, these
    checks ensure that the actual resources are created before handing over to the
    actual test in the test environment.

    The ``check_created`` and ``check_deleted`` do not take any parameter and do not
    return anything. However, if the resource is not respectively created or deleted
    after a certain time, they should raise an exception.

    Example:
        .. code:: python

            {
                10: [ClusterDefinition(...), ClusterDefinition(...)],
                0: [
                        ApplicationDefinition(...),
                        ApplicationDefinition(...),
                        ApplicationDefinition(...),
                    ],
            }

    Args:
        resources (dict): a dictionary that describes the resources to create, with
            their priority.
        before_handlers (list): this list of functions will be called one after the
            other in the given order before all Krake resources have been created. Their
            signature should be "handler(dict) -> void". The given dict contains the
            definition of all resources managed by the Environment.
        after_handlers (list): this list of functions will be called one after the other
            in the given order after all Krake resources have been deleted. Their
            signature should be "handler(dict) -> void". The given dict contains the
            definition of all resources managed by the Environment.
        creation_delay (int, optional): The number of seconds that should
            be allowed before concluding that a resource could not be created.

    """

    def __init__(
        self, resources, before_handlers=None, after_handlers=None, creation_delay=10
    ):
        # Dictionary: "priority: list of resources to create"
        self.res_to_create = resources
        self.resources = defaultdict(list)
        self.creation_delay = creation_delay

        self.before_handlers = before_handlers if before_handlers else []
        self.after_handlers = after_handlers if after_handlers else []

    def __enter__(self):
        """Create all given resources and check that they have been actually created.

        Returns:
            Environment: the current environment, after having been populated with the
                resources to create.

        """
        for handler in self.before_handlers:
            handler(self.resources)

        # Create resources with highest priority first
        for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
            for resource in resource_list:
                self.resources[resource.kind] += [resource]
                resource.create_resource()

        # Check for each resource if it has been created
        for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
            for resource in resource_list:
                resource.check_created(delay=self.creation_delay)

        return self

    def __exit__(self, *exceptions):
        """Delete all given resources and check that they have been actually deleted."""
        # Delete resources with lowest priority first
        for _, resource_list in sorted(self.res_to_create.items()):
            for resource in resource_list:
                resource.delete_resource()

        # Check for each resource if it has been deleted
        for _, resource_list in sorted(self.res_to_create.items()):
            for resource in resource_list:
                if hasattr(resource, "check_deleted"):
                    resource.check_deleted()

        for handler in self.after_handlers:
            handler(self.resources)

    def get_resource_definition(self, kind, name):
        """
        If there exists exactly one resource in 'resources' of kind 'kind'
        with name 'name', return it. Otherwise raise AssertionError.
        Args:
            kind (ResourceKind): the kind of resource which is sought.
            name (str): the name of the resource that is sought.

        Returns:
            ResourceDefinition: If found, the sought resource.
                if kind == ResourceKind.CLUSTER: ClusterDefinition
                If kind == ResourceKind.APPLICATION: ApplicationDefinition

        Raises:
            AssertionError if not exactly one resource was found.

        """
        found = [r for r in self.resources[kind] if r.name == name]
        if len(found) != 1:
            msg = (
                f"Found {len(found)} resources of kind {kind} with name {name} "
                f"(expected one)."
            )
            if len(found) != 0:
                msg += f" They were: {', '.join(str(rd) for rd in found)}"
            raise AssertionError(msg)
        return found[0]


def create_simple_environment(
    cluster_name, kubeconfig_path, app_name, manifest_path, observer_schema_path=None
):
    """Create the resource definitions for a test environment with one Cluster and one
    Application. The Cluster should be created first, and is thus given a higher
    priority.

    Args:
        cluster_name (PathLike): name of the kubernetes cluster that will be created
        kubeconfig_path (PathLike): path to the kubeconfig file for the cluster to
            create.
        app_name (PathLike): name of the Application to create.
        manifest_path (PathLike): path to the manifest file that should be used to
            create the Application.
        observer_schema_path (PathLike, optional): path to the observer_schema file
            that should be used by the Kubernetes Observer

    Returns:
        dict: an environment definition to use to create a test environment.

    """
    return {
        10: [ClusterDefinition(name=cluster_name, kubeconfig_path=kubeconfig_path)],
        0: [
            ApplicationDefinition(
                name=app_name,
                manifest_path=manifest_path,
                observer_schema_path=observer_schema_path,
            )
        ],
    }


def create_multiple_cluster_environment(
    kubeconfig_paths,
    cluster_labels=None,
    metrics=None,
    app_name=None,
    manifest_path=None,
    app_cluster_constraints=None,
    app_migration=None,
):
    """Create the resource definitions for a test environment with
    one Application and multiple Clusters.

    Args:
        kubeconfig_paths (dict[str, PathLike]): mapping between Cluster
            names and path to the kubeconfig file for the corresponding Cluster
            to create.
        cluster_labels (dict[str, dict[str, str]], optional): mapping between
            Cluster names and labels for the corresponding Cluster to create.
            The labels are given as a dictionary with the label names as keys
            and the label values as values.
        metrics (dict[str, dict[str, float]], optional): mapping between
            Cluster names and metrics for the corresponding Cluster to create.
            The metrics are given as a dictionary with the metric names as keys
            and the metric weights as values.
        app_name (str, optional): name of the Application to create.
        manifest_path (PathLike, optional): path to the manifest file that
            should be used to create the Application.
        app_cluster_constraints (list[str], optional): list of cluster constraints
            for the Application to create.
        app_migration (bool, optional): migration flag indicating whether the
            application should be able to migrate.

    Returns:
        dict[int, list[ResourceDefinition]]: an environment definition to use to create
            a test environment.

    """
    if not cluster_labels:
        cluster_labels = {cn: {} for cn in kubeconfig_paths}
    if not metrics:
        metrics = {cn: {} for cn in kubeconfig_paths}
    if not app_cluster_constraints:
        app_cluster_constraints = []

    env = {
        10: [
            ClusterDefinition(
                name=cn,
                kubeconfig_path=kcp,
                labels=cluster_labels[cn],
                metrics=_convert_to_metrics_list(metrics[cn]),
            )
            for cn, kcp in kubeconfig_paths.items()
        ]
    }
    if app_name:
        env[0] = [
            ApplicationDefinition(
                name=app_name,
                manifest_path=manifest_path,
                constraints=app_cluster_constraints,
                migration=app_migration,
            )
        ]
    return env


def create_default_environment(
    cluster_names,
    metrics=None,
    cluster_labels=None,
    app_cluster_constraints=None,
    app_migration=None,
):
    """Create and return a test environment definition with one application and
    len(cluster_names) clusters using default kubeconfig and manifest files.

    This method is a convenience method wrapping
    `create_multiple_cluster_environment()`.

    The kubeconfig file that will be used for `cluster_name` in `cluster_names`
    is given by get_default_kubeconfig_path(). This file is assumed to exist.

    The manifest file that will be used for the application is
    `MANIFEST_PATH/DEFAULT_MANIFEST`. This file is assumed to exist.

    Args:
        cluster_names (list[str]): cluster names
        metrics (dict[str, dict[str, float]], optional):
            Cluster names and their metrics.
            keys: the same names as in `cluster_names`
            values: dict of metrics
                keys: metric names
                values: weight of the metrics
        cluster_labels (dict[str, dict[str, str]], optional):
            Cluster names and their cluster labels.
            keys: the same names as in `cluster_names`
            values: dict of cluster labels
                keys: cluster labels
                values: value of the cluster labels
        app_cluster_constraints (list[str], optional):
            list of cluster constraints, e.g. ["location != DE"]
        app_migration (bool, optional): migration flag indicating whether the
            application should be able to migrate. If not provided, none is
            provided when creating the application.

    Returns:
        dict: an environment definition to use to create a test environment.

    """
    kubeconfig_paths = {c: get_default_kubeconfig_path(c) for c in cluster_names}
    manifest_path = os.path.join(MANIFEST_PATH, DEFAULT_MANIFEST)
    return create_multiple_cluster_environment(
        kubeconfig_paths=kubeconfig_paths,
        metrics=metrics,
        cluster_labels=cluster_labels,
        app_name=DEFAULT_KUBE_APP_NAME,
        manifest_path=manifest_path,
        app_cluster_constraints=app_cluster_constraints,
        app_migration=app_migration,
    )


def create_magnum_cluster_environment(
    project_names,
    cluster_name,
    template_id,
    project_id,
    user_id,
    user_password,
    auth_url,
    metrics=None,
    project_labels=None,
    constraints=None,
):
    """Create an environment with one or several Krake Project resources and one
    MagnumCluster resource.

    Args:
        project_names (list[str]): the names of each Krake Project resources to create.
        cluster_name (str): name of the Magnum Cluster resource in Krake.
        template_id (str): UUID of the OpenStack cluster template to use for the
            creation of the Magnum clusters.
        project_id (str): UUID of the OpenStack Project to use as base for the Krake
            Projects.
        user_id (str): UUID of the OpenStack user to get for creating the Krake Project.
        user_password (str): password of the OpenStack user to get for creating the
            Krake Project.
        auth_url (str): URL of the Identity service of the OpenStack infrastructure.
        metrics (dict[str, dict[str, float]], optional):
            Cluster names and their metrics.
            keys: the same names as in `cluster_names`
            values: dict of metrics
                keys: metric names
                values: weight of the metrics
        project_labels (dict[str, dict[str, str]], optional): project names and their
            labels.
            keys: the same names as in `cluster_names`
            values: dict of cluster labels
                keys: cluster labels
                values: value of the cluster labels
        constraints (list[str], optional): list of cluster constraints,
            e.g. ["location != DE"].

    Returns:
        dict[int, list[resource_definitions.ResourceDefinition]]:

    """
    if not project_labels:
        project_labels = {pn: {} for pn in project_names}
    if not metrics:
        metrics = {pn: {} for pn in project_names}
    if not constraints:
        constraints = []

    password_credentials = (project_id, user_id, user_password)
    return {
        10: [
            ProjectDefinition(
                project_name,
                auth_url,
                template_id,
                password_credentials=password_credentials,
                labels=project_labels[project_name],
                metrics=_convert_to_metrics_list(metrics[project_name]),
            )
            for project_name in project_names
        ],
        0: [
            MagnumClusterDefinition(
                cluster_name, master_count=1, node_count=1, constraints=constraints
            )
        ],
    }
