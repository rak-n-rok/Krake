import itertools
import os
import time
from abc import ABC, abstractmethod
from enum import Enum

from utils import (
    run,
    check_resource_exists,
    check_app_running_on,
    check_app_created_and_up,
    check_return_code,
    check_resource_deleted,
    allow_404,
)


class ResourceKind(Enum):
    APPLICATION = "application"
    CLUSTER = "cluster"


class ResourceDefinition(ABC):
    """Definition of a resource for the test environment :class:`Environment`.

    Describes how to create, update and delete a resource with the rok utility.
    Also defines checks to perform to test whether these actions were successful.

    Attributes:
        name (str): name of the resource
        kind (ResourceKind): resource kind
        _mutable_attributes (list[str]): list of the attributes of the
            ResourceDefinition which can be modified by its update_resource() method.
    """

    def __init__(self, name, kind):
        assert name
        self.name = name
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

    def create_resource(self, wait=False):
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

        Returns:
            list[str]: the command to create the resource, as a list of its parts.
        """
        pass

    def check_created(self, delay=10):
        """Run the command for checking if the resource has been created.

        Args:
            delay (int, optional): The number of seconds that should be allowed
                before giving up.
        """
        run(
            self.get_command(),
            condition=self.creation_acceptance_criteria(),
            interval=1,
            retry=delay,
        )

    @abstractmethod
    def creation_acceptance_criteria(self, error_message=None):
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

        msg = (
            f"The attributes of the {self.kind} {self.name} was not equal to the "
            f"ones of the actual resource. ResourceDefinition: {expected}. "
            f"Actual resource: {observed}."
        )
        assert expected == observed, msg

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
        manifest_path (str): path to the manifest file to use for the creation.
        constraints (list[str], optional): list of cluster label constraints
            to use for the creation of the application.
        labels (dict[str, str]): dict of application labels and their values
        hooks (list[str]): list of hooks name to apply to the application.
        migration (bool, optional): migration flag indicating whether the
            application should be able to migrate.
        observer_schema_path (str, optional): path to the observer_schema file to use.
    """

    def __init__(
        self,
        name,
        manifest_path,
        constraints=None,
        labels=None,
        hooks=None,
        migration=None,
        observer_schema_path=None,
    ):
        super().__init__(name=name, kind=ResourceKind.APPLICATION)
        assert os.path.isfile(manifest_path), f"{manifest_path} is not a file."
        self.manifest_path = manifest_path
        self.cluster_label_constraints = constraints or []
        self.labels = labels or {}
        self.hooks = hooks or []
        self.migration = migration
        self.observer_schema_path = observer_schema_path

    def _get_mutable_attributes(self):
        return ["cluster_label_constraints", "labels", "migration"]

    def _get_default_values(self):
        defaults = dict.fromkeys(self._mutable_attributes)
        defaults.update({"cluster_label_constraints": []})
        defaults.update({"labels": {}})
        defaults.update({"migration": True})
        return defaults

    def _get_actual_mutable_attribute_values(self):
        app = self.get_resource()
        return {
            "cluster_label_constraints": app["spec"]["constraints"]["cluster"][
                "labels"
            ],
            "labels": app["metadata"]["labels"],
            "migration": app["spec"]["constraints"]["migration"],
        }

    def creation_command(self, wait):

        if wait:
            cmd = (
                f"rok kube app create -f {self.manifest_path} "
                f"{self.name} --wait".split()
            )
        else:
            cmd = f"rok kube app create -f {self.manifest_path} {self.name}".split()

        cmd += self._get_cluster_label_constraint_options(
            self.cluster_label_constraints
        )
        cmd += self._get_label_options(self.labels)
        cmd += self._get_hook_params(self.hooks)

        if self.migration is not None:
            cmd += [self._get_migration_flag(self.migration)]
        if self.observer_schema_path:
            cmd += f" -O {self.observer_schema_path}".split()
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

    def creation_acceptance_criteria(self, error_message=None):
        return check_app_created_and_up(error_message=error_message)

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
        kubeconfig_path (str): path to the kubeconfig file to use for the creation.
        labels (dict[str, str], optional): dict of cluster labels and their values
            to use for the creation.
        metrics (list[dict[str, object]], optional): list of dict of metrics and their
            weights. Each dict has te two keys "name" and "weight".
    """

    def __init__(self, name, kubeconfig_path, labels=None, metrics=None):
        super().__init__(name=name, kind=ResourceKind.CLUSTER)
        assert os.path.isfile(kubeconfig_path), f"{kubeconfig_path} is not a file."
        self.kubeconfig_path = kubeconfig_path
        self.labels = labels or {}
        self.metrics = metrics or []

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
        return defaults

    def _get_actual_mutable_attribute_values(self):
        cluster = self.get_resource()
        return {
            "labels": cluster["metadata"]["labels"],
            "metrics": cluster["spec"]["metrics"],
        }

    def creation_command(self, wait):
        cmd = "rok kube cluster create".split()
        cmd += self._get_label_options(self.labels)
        cmd += self._get_metrics_options(self.metrics)
        cmd += [self.kubeconfig_path]
        return cmd

    @staticmethod
    def _get_metrics_options(metrics):
        """Convenience method for generating metric lists for rok cli commands.

        Example:
            If provided the argument metrics=
            [{"name": "metric_name1", "weight": 1.0},
            {"name": "metric_name2", "weight": 2.0}],
            this method will return the list
            ["-m", "metric_name1", "1.0", "-m", "metric_name2", "2.0"],
            which can be used when constructing a cli command like
            rok kube cluster create -m metric_name1 1.0 -m metric_name2 2.0 ...

        Args:
            metrics (list[dict[str, object]]): list of dicts of metrics names
                and their weights

        Returns:
            list[str]:
                ['-m', 'key_1', 'value_1', '-m', 'key_2', 'value_2', ...,
                '-m', 'key_n', 'value_n']
                for all n key, value pairs in metrics.
        """
        metrics_options = []
        if metrics is None:
            metrics = []
        for metric in metrics:
            metrics_options += ["-m", metric["name"], str(metric["weight"])]
        return metrics_options

    def creation_acceptance_criteria(self, error_message=None):
        if not error_message:
            error_message = f"The cluster {self.name} was not properly created."
        return check_resource_exists(error_message=error_message)

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
