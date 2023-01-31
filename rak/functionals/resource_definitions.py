import itertools
import os
import time
from abc import ABC, abstractmethod
from enum import Enum

from functionals.utils import (
    run,
    check_resource_exists,
    check_cluster_created_and_up,
    check_app_running_on,
    check_app_created_and_up,
    check_return_code,
    check_resource_deleted,
    allow_404,
    DEFAULT_NAMESPACE,
)


class ResourceKind(Enum):
    APPLICATION = "application"
    CLUSTER = "cluster"
    METRIC = "metric"
    GLOBALMETRIC = "globalmetric"
    METRICSPROVIDER = "metricsprovider"
    GLOBALMETRICSPROVIDER = "globalmetricsprovider"

    def is_namespaced(self):
        return self not in [self.GLOBALMETRICSPROVIDER, self.GLOBALMETRIC]


class ResourceDefinition(ABC):
    """Definition of a resource for the test environment :class:`Environment`.

    Describes how to create, update and delete a resource with the rok utility.
    Also defines checks to perform to test whether these actions were successful.

    Attributes:
        name (str): name of the resource
        kind (ResourceKind): resource kind
        _mutable_attributes (list[str]): list of the attributes of the
            ResourceDefinition which can be modified by its update_resource() method.
        namespace (str, optional): the namespace of the resource

    Raises:
        ValueError: if kind does not match namespace or if name is missing
    """

    def __init__(self, name, kind, namespace=None):
        if not name:
            raise ValueError("name must be provided")
        if bool(namespace) != kind.is_namespaced():
            raise ValueError(
                f"kind {kind!r} does not support namespace, "
                f"but {namespace!r} was provided"
            )
        self.name = name
        self.namespace = namespace
        self.kind = kind
        self._mutable_attributes = self._get_mutable_attributes()

    @abstractmethod
    def _get_mutable_attributes(self):
        """
        Retrieve the attributes of this ResourceDefinition which can be changed
        using its update_resource() method.

        Returns:
            list[str]: list of attributes of this ResourceDefinition which can be
                modified by its update_resource() method.
        """
        pass

    @abstractmethod
    def _get_default_values(self):
        """Returns the default values of all mutable attributes for the
        ResourceDefinition after creation.

        If no default value exists for an attribute, its default value is set to None.

        Returns:
            dict[str, object]: a dict with the mutable attributes as keys and their
                default values as values.
        """
        pass

    @abstractmethod
    def _get_actual_mutable_attribute_values(self):
        """Retrieve the attributes returned by self._get_mutable_attributes() from the
        actual resource.

        Returns:
            dict[str, object]: dict with the attributes returned by
                self._get_mutable_attributes() as keys and the actual resource's values
                of those attributes as values.
        """
        pass

    def create_resource(self, ignore_verification=False, wait=False):
        """Create the resource."""
        # Create the actual resource based on the initial values of this
        # ResourceDefinition, since these are the values which should be used
        # for the creation.
        error_message = f"The {self.kind} {self.name} could not be created."
        run(self.creation_command(wait), condition=check_return_code(error_message))

        # Update this ResourceDefinition with the default values of all mutable
        # attributes for which none was provided. It is important to do this after
        # creating the actual resource since we otherwise would create the resource
        # with the default values, which would be unintended by the test methods.
        self._set_default_values()

        # Verify that the attributes of the actual resource and this ResourceDefinition
        # are equal.
        if not ignore_verification:
            self._verify_resource()

    def _set_default_values(self):
        """Checks which attributes of this resource definition have not yet been set
        and sets them to their default values returned by self._get_default_values().
        Only the attributes returned by self._get_mutable_attributes() are taken into
        account.

        Raises:
            AssertionError: If any of the default values is None.
        """
        default_values = self._get_default_values()
        attrs_needing_defaults = [
            attr for attr in self._mutable_attributes if getattr(self, attr) is None
        ]
        for attr in attrs_needing_defaults:
            msg = f"{self.kind} had default value 'None' for attribute '{attr}'."
            assert default_values[attr] is not None, msg
            setattr(self, attr, default_values[attr])

    @abstractmethod
    def creation_command(self, wait):
        """Get the command for creating the resource.

        Args:
            wait (int): time to wait for the resource creation

        Returns:
            list[str]: the command to create the resource, as a list of its parts.
        """
        pass

    def check_created(self, delay=10, expected_state=None):
        """Run the command for checking if the resource has been created.

        Args:
            delay (int, optional): The number of seconds that should be allowed
                before giving up.
            expected_state (str, optional): The expected state of the to be checked
                resource. Normally converts to an ONLINE or RUNNING state.
        """
        run(
            self.get_command(),
            condition=self.creation_acceptance_criteria(expected_state=expected_state),
            interval=1,
            retry=delay,
        )

    @abstractmethod
    def creation_acceptance_criteria(self, error_message=None, expected_state=None):
        """Verify that the resource has been properly created.

        Args:
            error_message (str, optional): error message to display in case of failure

        Raises:
            AssertionError: if the resource failed to be created properly
        """
        pass

    def delete_resource(self, wait=False):
        """Delete the resource."""
        # The 404 HTTP code is allowed for the cases where the resource has been deleted
        # during the test.
        run(self.delete_command(wait), condition=allow_404)

    @abstractmethod
    def delete_command(self, wait):
        """Get the command for deleting the resource.

        Returns:
            list[str]: the command to delete the resource, as a list of its parts.
        """
        pass

    def check_deleted(self, delay=10):
        """Run the command for checking if the resource has been deleted.

        Args:
            delay (int, optional): The number of seconds that should be allowed
                before giving up.
        """
        run(
            self.get_command(),
            condition=self.deletion_acceptance_criteria(),
            interval=1,
            retry=delay,
        )

    def deletion_acceptance_criteria(self, error_message=None):
        """Verify that the resource has been properly deleted.

        Args:
            error_message (str, optional): error message to display in case of failure

        Raises:
            AssertionError: if the resource failed to be deleted properly
        """
        if not error_message:
            error_message = (
                f"Unable to observe the {self.kind} resource {self.name} being deleted"
            )
        return check_resource_deleted(error_message=error_message)

    def get_resource(self):
        """Get the resource by executing the rok cli command.

        Returns:
            dict: the resource as a dict built from the output of the
                executed command returned by self.get_command().
        """

        response = run(self.get_command())
        return response.json

    @abstractmethod
    def get_command(self):
        """Generate a command for getting the resource.

        Returns:
            list[str]: the command to get the resource, as a list of its parts.
        """
        pass

    def update_resource(self, **kwargs):
        """Update the resource with the provided information.

        Args:
            **kwargs: keyword arguments matching the arguments of update_command().

        Raises:
            AssertionError: if some attributes don't match
        """
        for attr in kwargs:
            # we do not allow updating name and kind attributes
            msg = f"Attribute '{attr}' is immutable"
            assert attr != "kind" and attr != "name", msg
            # we only allow updating existing attributes
            msg = f"'{attr}' is not an attribute of {self.__class__.__name__}"
            assert hasattr(self, attr), msg

        msg = (
            f"The mutable attributes of {self.__class__.__name__} "
            f"({self._mutable_attributes.sort()}) "
            f"are not equal to the update parameters ({list(kwargs.keys()).sort()})"
        )
        assert self._mutable_attributes.sort() == list(kwargs.keys()).sort(), msg

        # update this ResourceDefinition object
        self._update_resource_definition(kwargs)

        # update the actual resource
        msg = f"The {self.kind} {self.name} could not be updated."
        run(self.update_command(**kwargs), condition=check_return_code(msg))

        # After updating the values of the actual resource we want to verify
        # that its values match this ResourceDefinition.
        self._verify_resource()

    def _update_resource_definition(self, attributes):
        """Update this ResourceDefinition object with the given attribute values

        Args:
            attributes (dict[str, object]): dict with the mutable attributes of this
                ResourceDefinition as keys and their new values as values.
                A value of None signalizes that no update should be performed.

        Raises:
            AssertionError: if the update is empty
        """
        # For each attribute in 'attributes', set the corresponding attribute of this
        # ResourceDefinition object.
        empty_update = True
        for attr, attr_val in attributes.items():
            if attr_val is None:
                continue
            empty_update = False
            # FIXME: krake#413: Note that the attributes that are dicts or lists might
            #  contain information needing to be kept. However, the following call to
            #  setattr() overwrites this information, which is unwanted behaviour
            #  (see krake#413).
            setattr(self, attr, attr_val)

        msg = (
            "We were asked to update 0 of the mutable attributes. "
            "Empty updates are not allowed."
        )
        assert not empty_update, msg

    def _verify_resource(self):
        """Verify that the values of the mutable attributes of this ResourceDefinition
        are equal to the values of the attributes of the actual resource.

        Raises:
            AssertionError: if the values of all mutable attributes of this
                ResourceDefinition are not equal to the corresponding values of
                the actual resource.

        """
        # get the values from this resource definition
        expected = dict.fromkeys(self._mutable_attributes)
        for attr in expected:
            expected[attr] = getattr(self, attr)

        # get the attributes from the actual resource
        observed = self._get_actual_mutable_attribute_values()
        msg = (
            f"Mutable attributes of the {self.__class__.__name__} "
            f"({self._mutable_attributes.sort()}) "
            f"are not equal to the observed ({list(observed.keys()).sort()})"
        )
        assert self._mutable_attributes.sort() == list(observed.keys()).sort(), msg

        for attr in expected:
            msg = (
                f"The attribute {attr} of the {self.kind} {self.name} was not "
                f"equal to the one of the actual resource. ResourceDefinition: "
                f"{expected}. Actual resource: {observed}."
            )
            assert self.attribute_is_equal(attr, expected[attr], observed[attr]), msg

    def attribute_is_equal(self, attr_name, expected, observed):
        """Check whether the expected is equal to the observed.

        Expected to be overridden by subclasses in case the comparison is not
        straightforward.

        Args:
            attr_name (str): the name of the attribute for which this comparison
                is taking place
            expected (object): the expected attribute value
            observed (object): the observed attribute value

        Returns:
            bool: indicating whether expected == observed, given that they are
                the values of the attr_name attribute of this ResourceDefintion object.
        """
        return expected == observed

    @abstractmethod
    def update_command(self, **kwargs):
        """Get a command for updating the application.

        Args:
            **kwargs: the arguments necessary to update the resource.

        Returns:
            list[str]: the command to update the resource, as a list of its parts.
        """
        pass

    @staticmethod
    def _get_label_options(labels):
        """
        Convenience method for generating label lists for rok cli commands.

        Example:
            If provided the argument labels={"label1": "value1", "label2": "value2"},
            this method will return the list
            ["-l", "label1=value1", "-l", "label2=value2"],
            which can be used when constructing a cli command like
            "rok kube app create -l label1=value1 -l label2=value2 ..."

        Args:
            labels (dict[str, str]): dict of resource labels and their values

        Returns:
            list[str]:
                ['-l', key_1=value_1, '-l', key_2=value_2, ..., '-l', key_n=value_n]
                for all n key, value pairs in labels.
        """
        labels = [k + "=" + v for k, v in labels.items()] if labels else []
        return ResourceDefinition._get_flag_str_options("-l", labels)

    @staticmethod
    def _get_backoff_options(backoff):
        if backoff is not None:
            return ResourceDefinition._get_flag_str_options("--backoff", str(backoff))
        else:
            return ""

    @staticmethod
    def _get_backoff_delay_options(backoff_delay):
        if backoff_delay is not None:
            return ResourceDefinition._get_flag_str_options(
                "--backoff_delay", str(backoff_delay)
        )
        else:
            return ""

    @staticmethod
    def _get_backoff_limit_options(backoff_limit):
        if backoff_limit is not None:
            return ResourceDefinition._get_flag_str_options(
                "--backoff_limit", str(backoff_limit)
            )
        else:
            return ""

    @staticmethod
    def _get_flag_str_options(flag, values):
        """
        Convenience method for generating option lists for cli commands.

        Example:
            If provided the arguments flag="-L" and
            values=["location is not DE", "foo=bar"], this method will return
            the list ["-L", "location is not DE", "-L", "foo=bar"],
            which can be used when constructing a cli command like
            "rok kube app create -L 'location is not DE' -L foo=bar ..."

        Args:
            flag (str): The cli argument flag. The same flag is used for all values.
            values (list[str]): The values of the cli arguments

        Returns:
            list[str]: [flag, val1, flag, val_2, ..., flag, val_n]
                for all n values in values.
        """
        if not values:
            return []
        return list(itertools.chain(*[[flag, val] for val in values]))

    def get_labels(self):
        """Retrieve the labels from the actual resource.

        Returns:
            dict[str, str]: the labels of the resource
        """
        resource = self.get_resource()
        return resource["metadata"]["labels"]


class ApplicationDefinition(ResourceDefinition):
    """Definition of an Application resource for the test environment
    :class:`Environment`.

    Args:
        name (str): name of the application
        manifest_path (str, optional): path to the manifest file to use for the
            creation.
        tosca (Union[PathLike, str], optional): path to the TOSCA file or URL that
            should be used to create the application.
        csar (str, optional): URL to the CSAR file that should be used to
            create the Application.
        constraints (list[str], optional): list of cluster label constraints
            to use for the creation of the application.
        labels (dict[str, str]): dict of application labels and their values
        hooks (list[str]): list of hooks name to apply to the application.
        migration (bool, optional): migration flag indicating whether the
            application should be able to migrate.
        observer_schema_path (str, optional): path to the observer_schema file to use.
        namespace (str): namespace of the application
    """

    def __init__(
        self,
        name,
        manifest_path=None,
        tosca=None,
        csar=None,
        constraints=None,
        labels=None,
        hooks=None,
        migration=None,
        observer_schema_path=None,
        namespace=DEFAULT_NAMESPACE,
        backoff=None,
        backoff_delay=None,
        backoff_limit=None,
    ):
        super().__init__(name=name, kind=ResourceKind.APPLICATION, namespace=namespace)
        assert (
            manifest_path or tosca or csar
        ), "Resource should be described by Kubernetes manifest, TOSCA or CSAR"
        if manifest_path:
            assert os.path.isfile(manifest_path), f"{manifest_path} is not a file."

        self.manifest_path = manifest_path
        self.tosca = tosca
        self.csar = csar
        self.cluster_label_constraints = constraints or []
        self.labels = labels or {}
        self.hooks = hooks or []
        self.migration = migration
        self.observer_schema_path = observer_schema_path
        self.backoff = backoff
        self.backoff_delay = backoff_delay
        self.backoff_limit = backoff_limit

    def _get_mutable_attributes(self):
        return [
            "cluster_label_constraints", "labels", "migration",
            "backoff", "backoff_delay", "backoff_limit"
        ]

    def _get_default_values(self):
        defaults = dict.fromkeys(self._mutable_attributes)
        defaults.update({"cluster_label_constraints": []})
        defaults.update({"labels": {}})
        defaults.update({"migration": True})
        defaults.update({"backoff": 1})
        defaults.update({"backoff_delay": 1})
        defaults.update({"backoff_limit": -1})
        return defaults

    def _get_actual_mutable_attribute_values(self):
        app = self.get_resource()
        return {
            "cluster_label_constraints": app["spec"]["constraints"]["cluster"][
                "labels"
            ],
            "labels": app["metadata"]["labels"],
            "migration": app["spec"]["constraints"]["migration"],
            "backoff": app["spec"]["backoff"],
            "backoff_delay": app["spec"]["backoff_delay"],
            "backoff_limit": app["spec"]["backoff_limit"],
        }

    def creation_command(self, wait):
        app_definition = self.manifest_path or self.tosca or self.csar
        is_url = (
            True
            if self.csar or (self.tosca and self.tosca.startswith("http"))
            else False
        )
        if wait:
            cmd = (
                f"rok kube app create {'--url' if is_url else '--file'}"
                f" {app_definition} {self.name} --wait".split()
            )
        else:
            cmd = (
                f"rok kube app create {'--url' if is_url else '--file'}"
                f" {app_definition} {self.name}".split()
            )

        cmd += self._get_cluster_label_constraint_options(
            self.cluster_label_constraints
        )
        cmd += self._get_label_options(self.labels)
        cmd += self._get_hook_params(self.hooks)

        if self.migration is not None:
            cmd += [self._get_migration_flag(self.migration)]
        if self.observer_schema_path:
            cmd += f" -O {self.observer_schema_path}".split()

        cmd += self._get_backoff_options(self.backoff)
        cmd += self._get_backoff_delay_options(self.backoff_delay)
        cmd += self._get_backoff_limit_options(self.backoff_limit)

        return cmd

    @staticmethod
    def _get_migration_flag(migration):
        """
        Determines the migration cli option for a 'rok kube app create'
        or 'rok kube app update' command, based on the value of the flag 'migration'.

        Depending on the value of 'migration', the cli option is determined as such:
            True: "--enable-migration"
            False: "--disable-migration"
            None: ""

        Args:
            migration (bool, optional): Flag indicating the desired migration cli option

        Returns:
            str: The migration cli option.

        Raises:
            RuntimeError: if migration has an invalid state
        """
        if migration is False:
            migration_flag = "--disable-migration"
        elif migration is True:
            migration_flag = "--enable-migration"
        elif migration is None:
            migration_flag = ""
        else:
            raise RuntimeError("migration must be None, False or True.")
        return migration_flag

    @staticmethod
    def _get_hook_params(hooks):
        """
        Determines the hook cli options for a 'rok kube app create'
        or 'rok kube app update' command, based on the value of the 'hooks' list.

        Args:
            hooks (list): list containing all hooks

        Returns:
            list: list containing all hook parameters for the cli

        """
        hook_params = []
        if "complete" in hooks:
            hook_params.append("--hook-complete")
        if "shutdown" in hooks:
            hook_params.append("--hook-shutdown")

        return hook_params

    def creation_acceptance_criteria(self, error_message=None, expected_state="RUNNING"):
        if expected_state is None:
            expected_state = "RUNNING"
        return check_app_created_and_up(error_message=error_message,
                                        expected_state=expected_state)

    def delete_command(self, wait):
        if wait:
            return f"rok kube app delete {self.name} --wait".split()
        else:
            return f"rok kube app delete {self.name}".split()

    def delete_command_wait(self):
        return f"rok kube app delete {self.name} --wait".split()

    def update_command(
        self,
        cluster_label_constraints=None,
        migration=None,
        labels=None,
        observer_schema_path=None,
    ):
        """Get a command for updating the application.

        Args:
            cluster_label_constraints (list[str], optional): list of cluster label
                constraints to give the application, e.g. ['location=DE']
            migration (bool, optional): Flag indicating which migration flag should
                be given to the update command.
                    True: --enable-migration
                    False: --disable-migration
                    None: (No flag)
            labels (dict[str, str]): dict of labels with which to update the app.
            observer_schema_path (str): path to the observer schema

        Returns:
            list[str]: the command to update the application, as a list of its parts.
        """
        cmd = f"rok kube app update {self.name}".split()
        cmd += self._get_cluster_label_constraint_options(cluster_label_constraints)
        cmd += self._get_label_options(labels)
        if migration is not None:
            cmd += [self._get_migration_flag(migration)]
        if observer_schema_path:
            cmd += f" -O {observer_schema_path}".split()
        return cmd

    def _get_cluster_label_constraint_options(self, cluster_label_constraints):
        """
        Convenience method for generating cluster label constraints lists for
        rok cli commands.

        Example:
            If provided the argument labels=["constraint1", "constraint2"},
            this method will return the list ["-L", "constraint1", "-L", "constraint2"],
            which can be used when constructing a cli command like
            "rok kube app create -L constraint1 -L constraint2 ..."

        Args:
            cluster_label_constraints (list[str]): list of cluster label constraints
                to give the application, e.g. ['location is DE']

        Returns:
            list[str]: ['-L', constr_1, '-L', constr_2, ..., '-L', constr_n]
                for all n constraints in cluster_label_constraints.

        """
        return self._get_flag_str_options("-L", cluster_label_constraints)

    def check_running_on(
        self, cluster_name, within=10, after_delay=0, error_message=""
    ):
        """Run the command for checking that the application is running on the
        specified cluster.

        The first check occurs after `after_delay` seconds, and rechecks for
        `within` seconds every
        second until the application was observed to run on the cluster
        `cluster_name`.

        An AssertionError is raised if the application is not running on cluster
        `cluster_name` within `within` seconds of the first check.

        Args:
            cluster_name (str): Name of the cluster on which the application is
                expected to run.
            within (int): number of seconds it is allowed to take until the app
                is running on the cluster `cluster_name`.
            after_delay (int): number of seconds to delay before checking.
            error_message (str): displayed error message in case of error.
        """
        if not error_message:
            error_message = (
                f"Unable to observe that the application {self.name} "
                f"is running on cluster {cluster_name}."
            )
        if after_delay:
            time.sleep(after_delay)
        run(
            self.get_command(),
            retry=within,
            interval=1,
            condition=check_app_running_on(cluster_name, error_message),
        )

    def get_command(self):
        return f"rok kube app get {self.name} -o json".split()

    def get_running_on(self, strict=False):
        """Run the command for getting the application and return the name of
        the cluster it is running on.

        Args:
            strict (bool): Flag signaling whether to be strict and only return
            running_on if it is equal to scheduled_to.

        Returns:
            str: the name of the cluster the application is running on or None
            if scheduled_to != running_on
        """
        app_dict = self.get_resource()
        running_on = app_dict["status"]["running_on"]["name"]
        if strict:
            scheduled_to = app_dict["status"]["scheduled_to"]["name"]
            if scheduled_to != running_on:
                # We cannot be sure where it is running right now...
                return None
        return running_on

    def get_scheduled_to(self):
        """Run the command for getting the application and return the name of
        the cluster it is scheduled to.

        Returns:
            str: the name of the cluster the application is scheduled to
        """
        app_dict = self.get_resource()
        return app_dict["status"]["scheduled_to"]["name"]

    def get_state(self):
        """Run the command for getting the application and return its state.

        Returns:
            str: the current state of the application
        """
        app_dict = self.get_resource()
        return app_dict["status"]["state"]


class ClusterDefinition(ResourceDefinition):
    """Definition of a cluster resource for the test environment :class:`Environment`.

    Attributes:
        name (str): name of the cluster
        kubeconfig_path (str, optional): path to the kubeconfig file to use
            for the registration.
        labels (dict[str, str], optional): dict of cluster labels and their values
            to use for the creation.
        metrics (list[WeightedMetrics], optional): list of weighted metrics.
        namespace (str): namespace of the cluster
        register (bool, optional): True if the custer should be registered.
            Defaults to False.
    """

    def __init__(
        self,
        name,
        kubeconfig_path=None,
        labels=None,
        metrics=None,
        namespace=DEFAULT_NAMESPACE,
        backoff=None,
        backoff_delay=None,
        backoff_limit=None,
        register=False,
    ):
        super().__init__(name=name, kind=ResourceKind.CLUSTER, namespace=namespace)
        if register:
            assert os.path.isfile(kubeconfig_path), f"{kubeconfig_path} is not a file."
        self.kubeconfig_path = kubeconfig_path
        self.labels = labels or {}
        if not metrics:
            metrics = []
        self._set_metrics(metrics)
        self.backoff = backoff
        self.backoff_delay = backoff_delay
        self.backoff_limit = backoff_limit
        self.register = register

    def _set_metrics(self, metrics):
        """Change the metric weights this cluster resource definition has
        without updating the actual database resource associated with it.

        Args:
            metrics (list[WeightedMetric]: the new metrics of the cluster
        """
        self._validate_metrics(metrics)
        self.metrics = metrics

    def _validate_metrics(self, metrics):
        """Validate the metrics list based on their weighting.

        Args:
            metrics (list(WeightedMetric)): metrics to validate

        Raises:
            ValueError: if the metrics are a list or the metrics and clusters
                namespace don't match
        """
        if metrics is None:
            raise ValueError("Expected metrics to be a list. Was None.")
        if any(
            [
                weighted_metric.metric.namespace
                and self.namespace != weighted_metric.metric.namespace
                for weighted_metric in metrics
            ]
        ):
            raise ValueError(
                f"Metrics ({metrics}) and cluster's namespace "
                f"{self.namespace} do not match."
            )

    def _get_mutable_attributes(self):
        return ["labels", "metrics"]

    def _get_default_values(self):
        """Returns the default values for all mutable attributes of this resource
        definition.

        Returns:
            dict[str, object]:
                dict with the attributes in self._mutable_attributes as keys and
                their default values as values.
        """
        defaults = dict.fromkeys(self._mutable_attributes)
        defaults.update({"labels": {}})
        defaults.update({"metrics": []})
        defaults.update({"backoff": 1})
        defaults.update({"backoff_delay": 1})
        defaults.update({"backoff_limit": -1})
        return defaults

    def _get_actual_mutable_attribute_values(self):
        cluster = self.get_resource()
        return {
            "labels": cluster["metadata"]["labels"],
            "metrics": cluster["spec"]["metrics"],
        }

    def creation_command(self, wait):
        """TODO: Should be implemented together with
        infrastructure provider implementation.
        """

    def register_resource(self, wait=False, ignore_verification=False):
        """Register the resource."""
        error_message = f"The {self.kind} {self.name} could not be registered."
        run(self.register_command(wait), condition=check_return_code(error_message))
        self._set_default_values()
        if not ignore_verification:
            self._verify_resource()

    def check_registered(self, delay=10):
        """Run the command for checking if the resource has been registered.

        Args:
            delay (int, optional): The number of seconds that should be allowed
                before giving up.
        """
        run(
            self.get_command(),
            condition=self.register_acceptance_criteria(),
            interval=1,
            retry=delay,
        )

    def register_command(self, wait):
        cmd = "rok kube cluster register".split()
        cmd += self._get_label_options(self.labels)
        cmd += self._get_metrics_options(self.metrics)
        cmd += self._get_backoff_options(self.backoff)
        cmd += self._get_backoff_delay_options(self.backoff_delay)
        cmd += self._get_backoff_limit_options(self.backoff_limit)
        cmd += ["-k", self.kubeconfig_path]
        return cmd

    def register_acceptance_criteria(self, error_message=None):
        return self.creation_acceptance_criteria(error_message)

    @staticmethod
    def _get_metrics_options(metrics):
        """Convenience method for generating metric lists for rok cli commands.

        Example:
            If provided the argument metrics=
            [WeightedMetric("metric_name1", True, 1.0),
            WeightedMetric("metric_name2", False, 2.0)],
            this method will return the list
            ["-m", "metric_name1", "1.0", "-gm", "metric_name2", "2.0"],
            which can be used when constructing a cli command like
            rok kube cluster register -m metric_name1 1.0 -gm metric_name2 2.0 ...

        Args:
            metrics (list[WeightedMetric], optional): list of metrics with values.

        Returns:
            list[str]:
                [flag_1, 'key_1', 'value_1', flag_2, 'key_2', 'value_2', ...,
                flag_n, 'key_n', 'value_n'] (where flag_i is either "-m" or "-gm"
                depending on whether the ith item in metrics is namespaced)
                for all n key, value pairs in metrics.
        """
        metrics_options = []
        if metrics is None:
            metrics = []
        for weighted_metric in metrics:
            rok_cli_flag = "--global-metric"
            if weighted_metric.metric.kind.is_namespaced():
                rok_cli_flag = "--metric"
            metrics_options += [
                rok_cli_flag,
                weighted_metric.metric.name,
                str(weighted_metric.weight),
            ]
        return metrics_options

    def creation_acceptance_criteria(self, error_message=None, expected_state="ONLINE"):
        if expected_state is None:
            expected_state = "ONLINE"
        if not error_message:
            error_message = f"The cluster {self.name} was not properly created."
        return check_cluster_created_and_up(error_message=error_message,
                                            expected_state=expected_state)

    def delete_command(self, wait):
        return f"rok kube cluster delete {self.name}".split()

    def update_command(self, labels=None, metrics=None):
        """Get a command for updating the cluster.

        Args:
            labels (dict[str, str], optional): dict of labels and their values to
                give the cluster, e.g. {'location': 'DE'}
            metrics (list[dict[str, object]], optional): list of dicts with metrics
                and their weights to update the cluster with.

        Returns:
             list[str]: the command to update the application, as a list of its parts.

        Raises:
            AssertionError: if the labels or metrics are not present
        """
        if not (labels or metrics):
            msg = (
                "Either labels or metrics must be present in a "
                "cluster update command."
            )
            raise AssertionError(msg)

        cmd = f"rok kube cluster update {self.name}".split()
        cmd += self._get_label_options(labels)
        cmd += self._get_metrics_options(metrics)
        return cmd

    def get_command(self):
        return f"rok kube cluster get {self.name} -o json".split()

    def get_state(self):
        """Run the command for getting the cluster and return its state.

        Returns:
            str: the current state of the cluster, serialized as string.

        """
        cluster_dict = self.get_resource()
        return cluster_dict["status"]["state"]

    def get_metrics_reasons(self):
        """Run the command for getting the cluster and return the reasons for the
        metrics failure if there was any.

        Returns:
            dict[str, dict[str, str]]: the serialized reasons for the metrics failure,
                with the name of the metrics as key, and the deserialized reasons as
                values.

        """
        cluster_dict = self.get_resource()
        return cluster_dict["status"]["metrics_reasons"]

    def get_metrics(self):
        """Run the command for getting the cluster and return its metrics.

        Returns:
            list[dict[str, str]]: list of metrics, where each metric is a dict with
                its name under the key 'name', and its value under the key 'weight'.

        """
        cluster_dict = self.get_resource()
        return cluster_dict["spec"]["metrics"]

    def attribute_is_equal(self, attr_name, expected, observed):
        """Overriding attribute_is_equal() of the ResourceDefinition class,
        since the metrics attribute of ClusterDefinition needs to be compared
        differently.

        Args:
            attr_name (str): the name of the attribute for which this comparison
                is taking place
            expected (list[WeightedMetric]): the expected attribute value
            observed (list[dict[str, object]]): the observed attribute value.
                Each metric dictionary has the three keys 'name', 'namespaced'
                and 'weight' as keys and the metric's corresponding values as values.

        Returns:
            bool: indicating whether expected == observed, given that they are
                the values of the attr_name attribute of this ResourceDefintion object.
        """
        if attr_name != "metrics":
            return super().attribute_is_equal(attr_name, expected, observed)

        expected_names = [m.metric.name for m in expected]
        observed_by_name = {
            m["name"]: {"namespaced": m["namespaced"], "weight": m["weight"]}
            for m in observed
        }
        return (
            len(expected) == len(observed)
            and len(expected) == len(observed_by_name)
            and all(name in expected_names for name in observed_by_name)
            and all(
                observed_by_name[m.metric.name]["namespaced"]
                == bool(m.metric.namespace)
                for m in expected
            )
            and all(
                observed_by_name[m.metric.name]["weight"] == m.weight for m in expected
            )
        )
