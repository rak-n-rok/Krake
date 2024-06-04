import os

from collections import defaultdict
from functionals.utils import KRAKE_HOMEDIR
from functionals.resource_definitions import (
    ResourceKind,
    ClusterDefinition,
    ApplicationDefinition,
    DEFAULT_NAMESPACE,
)

GIT_DIR = "git/krake"
CLUSTERS_CONFIGS = f"{KRAKE_HOMEDIR}/clusters/config"
TEMPLATES_PATH = f"{KRAKE_HOMEDIR}/{GIT_DIR}/templates"
MANIFEST_PATH = f"{TEMPLATES_PATH}/applications/k8s"
TOSCA_PATH = f"{TEMPLATES_PATH}/applications/tosca"
OBSERVER_PATH = f"{TEMPLATES_PATH}/applications/observer-schemas"
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
    environment will create or register the requested resources in the requested
    order when started. Actions can then be performed on the environment.
    Finally, all resources, created or registered, are deleted in the reverse order
    of their creation or registration.

    The structure of the environment is given using the ``resources`` parameter. This
    parameter should be a dict with the following syntax:

    {
        <priority 0>: [<resource A>, <resource_B>...],
        <priority 1>: [<resource C>, <resource_D>...],
    }
    register:
        If the resource has attribute :attr:`register` and it is `True` the resource
        will be registered instead of created.

    priority:
        Priorities are integer. All resources with the highest priority (higher number)
        will be created or registered first.

    resource lists:
        The resource lists are composed of instances of resource definitions (e.g
        :class:`ClusterDefinition`). All resources with the same priority will be
        created or registered "at the same time", i.e. not concurrently,
        but between the ones with higher and the ones with lower priority.

        Note that the resources in these list do not need to have the same kind.

    To ensure that a resource is actually created, registered or deleted, methods
    can be added to the resources' definition, respectively ``check_created``,
    ``check_registered`` and ``check_deleted``.
    These methods are not meant to test the behavior of Krake, but simply to block the
    environment. When entering the context created by the :class:`Environment`, these
    checks ensure that the actual resources are created or registered before handing
    over to the actual test in the test environment.

    The ``check_created``, ``check_registered`` and ``check_deleted`` do not take
    any parameter and do not return anything. However, if the resource is not
    respectively created, registered or deleted after a certain time, they should
    raise an exception.

    Example:
        .. code:: python

            {
                10: [ClusterDefinition(...), ClusterDefinition(..., register=True)],
                0: [
                        ApplicationDefinition(...),
                        ApplicationDefinition(...),
                        ApplicationDefinition(...),
                    ],
            }

    Args:
        resources (dict): a dictionary that describes the resources to create or
            register, with their priority.
        before_handlers (list): this list of functions will be called one after the
            other in the given order before all Krake resources have been created or
            registered. Their signature should be "handler(dict) -> void". The given
            dict contains the definition of all resources managed by the Environment.
        after_handlers (list): this list of functions will be called one after the other
            in the given order after all Krake resources have been deleted. Their
            signature should be "handler(dict) -> void". The given dict contains the
            definition of all resources managed by the Environment.
        creation_delay (int, optional): The number of seconds that should be waited,
            before creating the next resource.
        registration_delay (int, optional): The number of seconds that should
            be allowed before concluding that a resource could not be registered.
        cluster_expected_state (str, optional): The expected state of one or more of the
            to be checked clusters.
        app_expected_state (str, optional): The expected state of one or more of the to
            be checked apps.
    """

    def __init__(
        self,
        resources,
        before_handlers=None,
        after_handlers=None,
        creation_delay=10,
        registration_delay=10,
        cluster_expected_state=None,
        app_expected_state=None,
        ignore_check=False,
        ignore_verification=False,
    ):
        # Dictionary: "priority: list of resources to create or register"
        self.res_to_apply = resources
        self.resources = defaultdict(list)
        self.creation_delay = creation_delay
        self.registration_delay = registration_delay

        self.cluster_expected_state = cluster_expected_state
        self.app_expected_state = app_expected_state

        self.before_handlers = before_handlers if before_handlers else []
        self.after_handlers = after_handlers if after_handlers else []

        self.ignore_check = ignore_check
        self.ignore_verification = ignore_verification

    def __enter__(self):
        """Create or register all given resources and check that they have been
        actually created or registered.

        Returns:
            Environment: the current environment, after having been populated with the
                resources to create or register.

        """
        for handler in self.before_handlers:
            handler(self.resources)

        # Create or register resources with the highest priority first
        for _, resource_list in sorted(self.res_to_apply.items(), reverse=True):
            for resource in resource_list:
                self.resources[resource.kind] += [resource]
                if hasattr(resource, "register") and resource.register:
                    resource.register_resource(
                        ignore_verification=self.ignore_verification
                    )
                else:
                    resource.create_resource(
                        ignore_verification=self.ignore_verification
                    )
                if not self.ignore_check:
                    if resource.kind == ResourceKind.CLUSTER:
                        if hasattr(resource, "register") and resource.register:
                            resource.check_registered(delay=self.registration_delay)
                        else:
                            resource.check_created(
                                delay=self.creation_delay,
                                expected_state=self.cluster_expected_state,
                            )
                    elif resource.kind == ResourceKind.APPLICATION:
                        if hasattr(resource, "register") and resource.register:
                            resource.check_registered(delay=self.registration_delay)
                        else:
                            resource.check_created(
                                delay=self.creation_delay,
                                expected_state=self.app_expected_state,
                            )
                    else:
                        if hasattr(resource, "register") and resource.register:
                            resource.check_registered(delay=self.registration_delay)
                        else:
                            resource.check_created(delay=self.creation_delay)

        return self

    def __exit__(self, *exceptions):
        """Delete all given resources and check that they have been actually deleted."""
        # Delete resources with the lowest priority first
        for _, resource_list in sorted(self.res_to_apply.items()):
            for resource in resource_list:
                resource.delete_resource()

        # Check for each resource if it has been deleted
        if not self.ignore_check:
            for _, resource_list in sorted(self.res_to_apply.items()):
                for resource in resource_list:
                    if hasattr(resource, "check_deleted"):
                        resource.check_deleted()

        for handler in self.after_handlers:
            handler(self.resources)

    def get_resource_definition(self, kind, name):
        """
        If there exists exactly one resource in 'resources' of kind 'kind'
        with name 'name', return it. Otherwise, raise an RuntimeError.
        Args:
            kind (ResourceKind): the kind of resource which is sought.
            name (str): the name of the resource that is sought.

        Returns:
            ResourceDefinition: If found, the sought resource.
                if kind == ResourceKind.CLUSTER: ClusterDefinition
                If kind == ResourceKind.APPLICATION: ApplicationDefinition

        Raises:
            RuntimeError: if not exactly one resource was found.

        """
        found = [r for r in self.resources[kind] if r.name == name]
        if len(found) != 1:
            msg = (
                f"Found {len(found)} resources of kind {kind} with name {name} "
                f"(expected one)."
            )
            if len(found) != 0:
                msg += f" They were: {', '.join(str(rd) for rd in found)}"
            raise RuntimeError(msg)
        return found[0]


def create_simple_environment(
    cluster_name,
    kubeconfig_path,
    app_name,
    app_namespace=DEFAULT_NAMESPACE,
    manifest_path=None,
    tosca=None,
    csar=None,
    observer_schema_path=None,
):
    """Create the resource definitions for a test environment with one Cluster and one
    Application. The Cluster should be registered first, and is thus given a higher
    priority.

    Resource should be described by :args:`manifest_path` or by :args:`tosca_path`

    Args:
        cluster_name (PathLike): name of the kubernetes cluster that will be registered
        kubeconfig_path (PathLike): path to the kubeconfig file for the cluster to
            register.
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
        10: [
            ClusterDefinition(
                name=cluster_name,
                kubeconfig_path=kubeconfig_path,
                register=True,
                backoff_limit=1,
            )
        ],
        0: [
            ApplicationDefinition(
                name=app_name,
                namespace=app_namespace,
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
    app_backoff=None,
    app_backoff_delay=None,
    app_backoff_limit=None,
    auto_cluster_create=False,
    observer_schema_path=None,
):
    """Create the resource definitions for a test environment with
    one Application and multiple Clusters.

    Args:
        kubeconfig_paths (dict[str, PathLike]): mapping between Cluster
            names and path to the kubeconfig file for the corresponding Cluster
            to register.
        cluster_labels (dict[str, dict[str, str]], optional): mapping between
            Cluster names and labels for the corresponding Cluster to register.
            The labels are given as a dictionary with the label names as keys
            and the label values as values.
        metrics (dict[str, list[WeightedMetric]], optional): mapping between
            Cluster names and metrics for the corresponding Cluster to register.
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
        app_backoff (int, optional): multiplier applied to backoff_delay between
            attempts. default: 1 (no backoff)
        app_backoff_delay (int, optional): delay [s] between attempts. default: 1
        app_backoff_limit (int, optional): a maximal number of attempts,
            default: -1 (infinite)
        auto_cluster_create (bool, optional): flag for the creation of new clusters
            with clouds

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
            register=True,
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
                backoff=app_backoff,
                backoff_delay=app_backoff_delay,
                backoff_limit=app_backoff_limit,
                auto_cluster_create=auto_cluster_create,
                observer_schema_path=observer_schema_path,
            )
        ]
    return env


def create_default_environment(
    cluster_names,
    metrics=None,
    cluster_labels=None,
    app_cluster_constraints=None,
    app_migration=None,
    app_backoff=None,
    app_backoff_delay=None,
    app_backoff_limit=None,
    auto_cluster_create=False,
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
        app_backoff (int, optional): multiplier applied to backoff_delay between
            attempts. default: 1 (no backoff)
        app_backoff_delay (int, optional): delay [s] between attempts. default: 1
        app_backoff_limit (int, optional): a maximal number of attempts, default: -1
            (infinite)

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
        app_backoff=app_backoff,
        app_backoff_delay=app_backoff_delay,
        app_backoff_limit=app_backoff_limit,
        auto_cluster_create=auto_cluster_create,
    )
