import os
from collections import defaultdict

from functionals.utils import KRAKE_HOMEDIR
from functionals.resource_definitions import (
    ClusterDefinition,
    ApplicationDefinition,
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
        self,
        resources,
        before_handlers=None,
        after_handlers=None,
        creation_delay=10,
        ignore_check=False,
    ):
        # Dictionary: "priority: list of resources to create"
        self.res_to_create = resources
        self.resources = defaultdict(list)
        self.creation_delay = creation_delay

        self.before_handlers = before_handlers if before_handlers else []
        self.after_handlers = after_handlers if after_handlers else []

        self.ignore_check = ignore_check

    def __enter__(self):
        """Create all given resources and check that they have been actually created.

        Returns:
            Environment: the current environment, after having been populated with the
                resources to create.

        """
        for handler in self.before_handlers:
            handler(self.resources)

        # Create resources with the highest priority first
        for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
            for resource in resource_list:
                self.resources[resource.kind] += [resource]
                resource.create_resource()

        # Check for each resource if it has been created
        if not self.ignore_check:
            for _, resource_list in sorted(self.res_to_create.items(), reverse=True):
                for resource in resource_list:
                    resource.check_created(delay=self.creation_delay)

        return self

    def __exit__(self, *exceptions):
        """Delete all given resources and check that they have been actually deleted."""
        # Delete resources with the lowest priority first
        for _, resource_list in sorted(self.res_to_create.items()):
            for resource in resource_list:
                resource.delete_resource()

        # Check for each resource if it has been deleted
        if not self.ignore_check:
            for _, resource_list in sorted(self.res_to_create.items()):
                for resource in resource_list:
                    if hasattr(resource, "check_deleted"):
                        resource.check_deleted()

        for handler in self.after_handlers:
            handler(self.resources)

    def get_resource_definition(self, kind, name):
        """
        If there exists exactly one resource in 'resources' of kind 'kind'
        with name 'name', return it. Otherwise, raise an AssertionError.
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
    cluster_name,
    kubeconfig_path,
    app_name,
    manifest_path=None,
    tosca=None,
    csar=None,
    observer_schema_path=None,
):
    """Create the resource definitions for a test environment with one Cluster and one
    Application. The Cluster should be created first, and is thus given a higher
    priority.

    Resource should be described by :args:`manifest_path` or by :args:`tosca_path`

    Args:
        cluster_name (PathLike): name of the kubernetes cluster that will be created
        kubeconfig_path (PathLike): path to the kubeconfig file for the cluster to
            create.
        app_name (PathLike): name of the Application to create.
        manifest_path (PathLike, optional): path to the manifest file that should
            be used to create the Application.
        tosca (Union[PathLike, str], optional): path to the TOSCA file or URL that
            should be used to create the Application.
        csar (str, optional): URL to the CSAR file that should be used to
            create the Application.
        observer_schema_path (PathLike, optional): path to the observer_schema file
            that should be used by the Kubernetes Observer

    Returns:
        dict: an environment definition to use to create a test environment.

    """
    assert (
        manifest_path or tosca or csar
    ), "Resource should be described by Kubernetes manifest or TOSCA or CSAR"
    return {
        10: [ClusterDefinition(name=cluster_name, kubeconfig_path=kubeconfig_path)],
        0: [
            ApplicationDefinition(
                name=app_name,
                manifest_path=manifest_path,
                tosca=tosca,
                csar=csar,
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
    tosca=None,
    csar=None,
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
        metrics (dict[str, list[WeightedMetric]], optional): mapping between
            Cluster names and metrics for the corresponding Cluster to create.
        app_name (str, optional): name of the Application to create.
        manifest_path (PathLike, optional): path to the manifest file that
            should be used to create the Application.
        tosca (Union[PathLike, str], optional): path to the TOSCA file or URL that
            should be used to create the Application.
        csar (str, optional): URL to the CSAR file that should be used to
            create the Application.
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

    all_unique_metrics_providers = {
        # A non-existent metric do not have a metrics provider, so its
        # get_metrics_provider() method returns None.
        weighted_metric.metric.get_metrics_provider()
        for cluster_name in kubeconfig_paths
        for weighted_metric in metrics[cluster_name]
    }
    # Discard None metrics providers from non-existent metrics present in metrics
    all_unique_metrics_providers.discard(None)
    all_unique_metrics = {
        weighted_metric.metric
        for cluster_name in kubeconfig_paths
        for weighted_metric in metrics[cluster_name]
    }

    env = {}
    if metrics:
        env[30] = all_unique_metrics_providers
        env[20] = all_unique_metrics
    env[10] = [
        ClusterDefinition(
            name=cn,
            kubeconfig_path=kcp,
            labels=cluster_labels[cn],
            metrics=metrics[cn],
        )
        for cn, kcp in kubeconfig_paths.items()
    ]
    if app_name:
        env[0] = [
            ApplicationDefinition(
                name=app_name,
                manifest_path=manifest_path,
                tosca=tosca,
                csar=csar,
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
        metrics (dict[str, list[WeightedMetric]], optional):
            Cluster names and their metrics.
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
