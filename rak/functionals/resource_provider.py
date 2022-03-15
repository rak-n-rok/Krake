from abc import ABC, abstractmethod
from enum import Enum
import random
import uuid

from functionals.utils import Singleton, check_resource_exists
from functionals.utils import DEFAULT_NAMESPACE as NAMESPACE
from functionals.resource_definitions import ResourceKind, ResourceDefinition


class MetricsProviderType(Enum):
    PROMETHEUS = "prometheus"
    STATIC = "static"
    KAFKA = "kafka"


class BaseMetricsProviderDefinition(ResourceDefinition, ABC):
    """base class for both namespaced and global metrics provider
    resource definitions.

    Attributes:
        name (str): name of the metrics provider
        kind (ResourceKind): kind of metrics provider. Must be either
            ResourceKind.METRICSPROVIDER or ResourceKind.GLOBALMETRICSPROVIDER
        namespace (str, optional): the namespace of the metrics provider.
            None if kind == ResourceKind.GLOBALMETRICSPROVIDER
        mp_type (functionals.resource_provider.MetricsProviderType): type of
            metrics provider
        _base_metrics (list[BaseMetricDefinition]): list of metric resource definitions
            that this provider provides.

    Raises:
        ValueError: if kind is incorrect or does not match the namespace
    """

    def __init__(self, name, kind, namespace, mp_type):
        if kind not in [
            ResourceKind.METRICSPROVIDER,
            ResourceKind.GLOBALMETRICSPROVIDER,
        ]:
            raise ValueError(f"Unexpected metrics provider kind: {kind}")
        super().__init__(name, kind, namespace=namespace)
        self.type = mp_type
        self._valued_metrics = []

    @abstractmethod
    def _get_mutable_attributes(self):
        raise NotImplementedError("Not yet implemented")

    def _get_default_values(self):
        return dict.fromkeys(self._mutable_attributes, None)

    def _get_actual_mutable_attribute_values(self):
        metrics_provider = self.get_resource()
        return {
            attr: metrics_provider["spec"][self.type.value][attr]
            for attr in self._mutable_attributes
        }

    @abstractmethod
    def creation_command(self, wait):
        raise NotImplementedError("Not yet implemented")

    def creation_acceptance_criteria(self, error_message=None):
        if not error_message:
            error_message = (
                f"The {self.kind.value} {self.name} was not properly created."
            )
        return check_resource_exists(error_message=error_message)

    def delete_command(self, wait):
        return f"rok core {self.kind.value} delete {self.name}".split()

    def get_command(self):
        return f"rok core {self.kind.value} get {self.name} -o json".split()

    @abstractmethod
    def update_command(self, **kwargs):
        raise NotImplementedError()

    @abstractmethod
    def read_metrics(self):
        """Read the metrics the actual resource provides

        Returns:
            dict[str, float]: dictionary with the metric names and values as
                keys and values.
        """
        raise NotImplementedError()

    def get_valued_metrics(self):
        """Retrieve the valued metrics of this metrics provider resource definition.

        Returns:
            list(ValuedMetric): list of the metrics this metrics provider provides,
                together with their values.
        """
        return self._valued_metrics

    def set_valued_metrics(self, metrics):
        """Set the valued metrics of this metrics provider

        Of the krake metrics provider resources, only the static metrics provider
        keeps the values of the metrics it provides. However, during the tests
        we need to be able to 'predict' which values a metrics provider will provide
        during the tests. Therefore, we provide the valued metrics to all types of
        metrics providers using this method.
        The values are however never used and can only be retrieved using the
        get_valued_metrics() method.

        For metrics providers of type MetricsProviderType.STATIC, calling this
        method changes the metrics which the metrics providers resource definition
        uses, without updating the actual database resource associated with it.
        This is useful when the provider needs to be set with a correct value already
        at creation of the actual database resource.
        (Otherwise, the initial values of the provider resource definition would be used
        when an application is scheduled to a cluster at the entry of an
        environment.Environment, which could contain incorrect information.)

        Args:
            metrics (list[ValuedMetric]):
                list of metrics that this metrics provider provides
        """
        self._validate_metrics(metrics)
        self._valued_metrics = metrics

    def _validate_metrics(self, metrics):
        """Validate the metrics list based on their namespaces.

        Args:
            metrics (list(StaticMetric)): metrics to validate

        """
        if metrics is None:
            raise ValueError("Expected metrics to be a list. Was None.")
        if any([self.namespace != m.metric.namespace for m in metrics]):
            raise ValueError(
                f"Metrics ({metrics}) and metrics provider namespace "
                f"{self.namespace} do not match."
            )


class BaseKafkaMetricsProviderDefinition(BaseMetricsProviderDefinition):
    """Base class for all kafka metrics provider resource definitions.

    Args:
        name (str): name of the metrics provider
        kind (ResourceKind): kind of metrics provider. Valid values are
            ResourceKind.METRICSPROVIDER and ResourceKind.GLOBALMETRICSPROVIDER
        namespace (str, optional): the namespace of the metrics provider.
            None if kind == ResourceKind.GLOBALMETRICSPROVIDER
        url (str): url at which this metrics provider provides.
        table (str): name of the ksql table.
        comparison_column (str): Name of the column whose value will be compared
            to the metric name when selecting a metric.
        value_column (str): Name of the column where the value of a metric is stored.


    Raises:
        ValueError: if kind is incorrect or does not match the namespace
    """

    def __init__(
        self, name, kind, namespace, url, table, comparison_column, value_column
    ):
        super().__init__(name, kind, namespace, mp_type=MetricsProviderType.KAFKA)
        self.url = url
        self.table = table
        self.comparison_column = comparison_column
        self.value_column = value_column

    def _get_mutable_attributes(self):
        return ["url", "table", "comparison_column", "value_column"]

    def creation_command(self, wait):
        return (
            f"rok core {self.kind.value} create --type {self.type.value} "
            f"--url {self.url} --comparison-column {self.comparison_column} "
            f"--value-column {self.value_column} --table {self.table} "
            f"{self.name}".split()
        )

    def update_command(
        self, url=None, table=None, comparison_column=None, value_column=None
    ):
        cmd = f"rok core {self.kind.value} update {self.name}".split()
        if url:
            cmd += ["--url", url]
        if table:
            cmd += ["--table", table]
        if comparison_column:
            cmd += ["--comparison-column", comparison_column]
        if value_column:
            cmd += ["--value-column", value_column]
        return cmd

    def read_metrics(self):
        raise NotImplementedError()


class BasePrometheusMetricsProviderDefinition(BaseMetricsProviderDefinition):
    """Base class for all prometheus metrics provider resource definitions.

    Args:
        name (str): name of the metrics provider
        kind (ResourceKind): kind of metrics provider. Valid values are
            ResourceKind.METRICSPROVIDER and ResourceKind.GLOBALMETRICSPROVIDER
        namespace (str, optional): the namespace of the metrics provider.
            None iff kind == ResourceKind.GLOBALMETRICSPROVIDER
        url (str): url at which this metrics provider provides.

    Raises:
        ValueError: if kind is incorrect or does not match the namespace
    """

    def __init__(self, name, kind, namespace, url):
        super().__init__(name, kind, namespace, mp_type=MetricsProviderType.PROMETHEUS)
        self.url = url

    def _get_mutable_attributes(self):
        return ["url"]

    def creation_command(self, wait):
        return (
            f"rok core {self.kind.value} create --type {self.type.value} "
            f"--url {self.url} {self.name}".split()
        )

    def update_command(self, url=None):
        return f"rok core {self.kind.value} update --url {url} {self.name}".split()

    def read_metrics(self):
        raise NotImplementedError()


class BaseStaticMetricsProviderDefinition(BaseMetricsProviderDefinition):
    """Base class for all static metrics provider resource definitions.

    Attributes:
        name (str): name of the metrics provider
        kind (ResourceKind): kind of metrics provider. Valid values are
            ResourceKind.METRICSPROVIDER and ResourceKind.GLOBALMETRICSPROVIDER
        namespace (str, optional): the namespace of the metrics provider.
            None iff kind == ResourceKind.GLOBALMETRICSPROVIDER
        metrics (list[StaticMetric]): list of static metrics that this
            metrics provider provides.

    Raises:
        ValueError: if kind is incorrect or does not match the namespace
    """

    def __init__(self, name, kind, namespace, metrics=None):
        super().__init__(name, kind, namespace, mp_type=MetricsProviderType.STATIC)
        if metrics is None:
            metrics = []
        self.set_valued_metrics(metrics)

    def _get_mutable_attributes(self):
        return ["metrics"]

    def creation_command(self, wait):
        cmd = (
            f"rok core {self.kind.value} create --type {self.type.value} "
            f"{self.name}".split()
        )
        cmd += self._get_metrics_options(self.metrics)
        return cmd

    def update_command(self, metrics=None):
        cmd = f"rok core {self.kind.value} update {self.name}".split()
        cmd += self._get_metrics_options(metrics)
        return cmd

    @staticmethod
    def _get_metrics_options(metrics):
        """Convenience method for generating metric lists for rok cli commands.

        Example:
            If provided the argument metrics=
            [StaticMetric("metric_name1", True, 1.0),
            StaticMetric("metric_name2", False, 2.0)],
            this method will return the list
            ["-m", "metric_name1", "1.0", "-m", "metric_name2", "2.0"],
            which can be used when constructing a cli command like
            rok kube cluster create -m metric_name1 1.0 -m metric_name2 2.0 ...

        Args:
            metrics (list[StaticMetric], optional): list of metrics with values.

        Returns:
            list[str]:
                ['-m', 'key_1', 'value_1', '-m', 'key_2', 'value_2', ...,
                '-m', 'key_n', 'value_n']
                for all n key, value pairs in metrics.
        """
        metrics_options = []
        if metrics is None:
            metrics = []
        for static_metric in metrics:
            metrics_options += [
                "-m",
                static_metric.metric.mp_metric_name,
                str(static_metric.value),
            ]
        return metrics_options

    def set_valued_metrics(self, metrics):
        super().set_valued_metrics(metrics)
        self.metrics = metrics

    def attribute_is_equal(self, attr_name, expected, observed):
        """Overriding attribute_is_equal() of the ResourceDefinition class,
        since the metrics attribute needs to be compared differently.

        Args:
            attr_name (str): the name of the attribute for which this comparison
                is taking place
            expected (list[StaticMetric]): the expected attribute value
            observed (dict[str, float]): the observed attribute value

        Returns:
            bool: indicating whether expected == observed, given that they are
                the values of the attr_name attribute of this ResourceDefintion object.
        """
        if attr_name != "metrics":
            return super().attribute_is_equal(attr_name, expected, observed)

        expected_names = [m.metric.mp_metric_name for m in expected]
        return (
            len(expected) == len(observed)
            and all(name in expected_names for name in observed)
            and all(m.value == observed.get(m.metric.mp_metric_name) for m in expected)
        )

    def read_metrics(self):
        actual_mutable_attrs = self._get_actual_mutable_attribute_values()
        return actual_mutable_attrs["metrics"]


class BaseMetricDefinition(ResourceDefinition, ABC):
    """Base class for namespaced and global metrics.

    Args:
        name (str): name of the metric
        kind (ResourceKind): kind of the metric. Must be either
            ResourceKind.METRIC or ResourceKind.GLOBALMETRIC
        namespace (str, optional): namespace of the metric.
            None iff kind == ResourceKind.GLOBALMETRIC
        min (float): minimum value of this metric
        max (float): maximum value of this metric
        mp_name (str): name of the metrics provider which privides this metric.
        mp_metric_name (str, optional): metric name for a specific metrics provider

    Raises:
        ValueError: if kind is incorrect or does not match the namespace
    """

    def __init__(self, name, kind, namespace, min, max, mp_name, mp_metric_name):
        super().__init__(name, kind, namespace)
        if kind not in [ResourceKind.METRIC, ResourceKind.GLOBALMETRIC]:
            raise ValueError(f"Unexpected type of metric: {kind}")
        self.kind = kind
        self.min = min
        self.max = max
        self.mp_name = mp_name
        self.mp_metric_name = mp_metric_name if mp_metric_name else name
        self._mp_name_param = (
            "--mp-name" if kind == ResourceKind.METRIC else "--gmp-name"
        )

    def _get_mutable_attributes(self):
        return ["min", "max", "mp_name", "mp_metric_name"]

    def _get_default_values(self):
        default_values = dict.fromkeys(self._mutable_attributes, None)
        default_values["mp_metric_name"] = self.name
        return default_values

    def _get_actual_mutable_attribute_values(self):
        metric = self.get_resource()
        return {
            "min": metric["spec"]["min"],
            "max": metric["spec"]["max"],
            "mp_name": metric["spec"]["provider"]["name"],
            "mp_metric_name": metric["spec"]["provider"]["metric"],
        }

    def creation_command(self, wait):
        cmd = (
            f"rok core {self.kind.value} create --min {self.min} --max {self.max} "
            f"{self._mp_name_param} {self.mp_name} --metric-name {self.mp_metric_name} "
            f"{self.name}".split()
        )
        if self.mp_metric_name:
            cmd += ["--metric-name", self.mp_metric_name]
        return cmd

    def creation_acceptance_criteria(self, error_message=None):
        if not error_message:
            error_message = (
                f"The {self.kind.value} {self.name} was not " f"properly created."
            )
        return check_resource_exists(error_message=error_message)

    def delete_command(self, wait):
        return f"rok core {self.kind.value} delete {self.name}".split()

    def get_command(self):
        return f"rok core {self.kind.value} get {self.name} -o json".split()

    def update_command(self, min=None, max=None, mp_name=None, mp_metric_name=None):
        cmd = f"rok core {self.kind.value} update {self.name}".split()
        if min:
            cmd += ["--min", min]
        if max:
            cmd += ["--max", max]
        if mp_name:
            cmd += [self._mp_name_param, mp_name]
        if mp_metric_name:
            cmd += ["--metric-name", self.mp_metric_name]
        return cmd

    def get_metrics_provider(self):
        """
        Returns:
            BaseMetricsProviderDefinition:
                The resource definition of the metrics proivder which provides
                this metric
        """
        return provider.get_metrics_provider(self)


class NonExistentMetric(BaseMetricDefinition):
    """Used by tests which require a metric that is not in the database.

    Raises:
        ValueError: whenever one tries to access the metric.
            Only create_resource(), check_created(), delete_resource() and
            check_deleted() will silently fail, since these will be called
            whenever entering and exiting an Environment.
    """

    def __init__(self):
        suffix = str(uuid.uuid4())
        name = "non-existent-metric-" + suffix
        mp_name = "non-existent-metrics-provider-" + suffix
        super().__init__(
            name,
            ResourceKind.GLOBALMETRIC,
            None,
            min=0,
            max=1,
            mp_name=mp_name,
            mp_metric_name=name,
        )

    def _get_mutable_attributes(self):
        return []

    def _get_default_values(self):
        raise ValueError("This metric does not exist and has no default values.")

    def _get_actual_mutable_attribute_values(self):
        raise ValueError("This metric does not exist and has no mutable attributes.")

    def create_resource(self):
        pass

    def check_created(self, delay=10):
        pass

    def creation_command(self, wait):
        raise ValueError("This metric does not exist and cannot be created.")

    def creation_acceptance_criteria(self, error_message=None):
        msg = (
            f"This metric does not exist and cannot be created. "
            f"error_message = {error_message}"
        )
        raise ValueError(msg)

    def delete_resource(self):
        pass

    def delete_command(self, wait):
        raise ValueError("This metric does not exist and cannot be deleted.")

    def check_deleted(self, delay=10):
        pass

    def get_command(self):
        raise ValueError("This metric does not exist and cannot be retrieved.")

    def update_command(self, min=None, max=None, mp_name=None, mp_metric_name=None):
        raise ValueError("This metric does not exist and cannot be updated.")

    def get_metrics_provider(self):
        return None


class WrappedMetric(ABC):
    """A wrapper around a BaseMetricDefinition object with kind
    ResourceKind.Metric or ResourceKind.GlobalMetric.

    Args:
        metric (BaseMetricDefinition): metric resource definition
    """

    def __init__(self, metric):
        super().__init__()
        self.metric = metric

    def __repr__(self):
        return self.metric.name + f"(provider '{self.metric.mp_name}')"

    def get_metrics_provider(self):
        return self.metric.get_metrics_provider()


class ValuedMetric(WrappedMetric, ABC):
    """A wrapper around a BaseMetricDefinition object and a value.

    Used by metrics providers.

    Args:
        metric (BaseMetricDefinition): metric resource definition
        value (float): value of the metric.
    """

    def __init__(self, metric, value):
        super().__init__(metric)
        self.value = value

    def __repr__(self):
        super_repr = super().__repr__()
        return super_repr + " = " + str(self.value)


class StaticMetric(ValuedMetric):
    """Used by the static metrics providers."""

    pass


class PrometheusMetric(ValuedMetric):
    """Used by the prometheus metrics providers."""

    pass


class WeightedMetric(WrappedMetric):
    """A wrapper around a BaseMetricDefinition object and a weight.

    Used by clusters.

    Args:
        metric (BaseMetricDefinition): metric resource definition
        weight (float): a cluster's weight of the metric.
    """

    def __init__(self, metric, weight):
        super().__init__(metric)
        self.weight = weight

    def __repr__(self):
        super_repr = super().__repr__()
        return super_repr + " = " + str(self.weight)


class ResourceProvider(Singleton):
    """Resource provider class, which contains data for the resource provider as well
    as useful functions.

    """

    def __init__(self):
        self._metric_to_metrics_provider = {}
        prometheus_metrics_providers = {
            None: self._init_metrics_providers(MetricsProviderType.PROMETHEUS, None),
        }
        static_metrics_providers = {
            NAMESPACE: self._init_metrics_providers(
                MetricsProviderType.STATIC, NAMESPACE
            ),
            None: self._init_metrics_providers(MetricsProviderType.STATIC, None),
        }
        self.metrics_providers = {
            MetricsProviderType.STATIC: static_metrics_providers,
            MetricsProviderType.PROMETHEUS: prometheus_metrics_providers,
        }

        self.unreachable_metrics_providers = {
            MetricsProviderType.PROMETHEUS: {
                None: self._init_metrics_providers(
                    MetricsProviderType.PROMETHEUS, None, unreachable=True
                )
            },
        }

        static_metrics = {
            NAMESPACE: self._init_metrics(MetricsProviderType.STATIC, NAMESPACE),
            None: self._init_metrics(MetricsProviderType.STATIC, None),
        }
        prometheus_metrics = {
            None: self._init_metrics(MetricsProviderType.PROMETHEUS, None),
        }
        self.metrics = {
            MetricsProviderType.STATIC: static_metrics,
            MetricsProviderType.PROMETHEUS: prometheus_metrics,
        }

        self.unreachable_metrics = {
            MetricsProviderType.PROMETHEUS: {
                None: self._init_metrics(
                    MetricsProviderType.PROMETHEUS, None, unreachable=True
                )
            }
        }

    # Metrics providers
    _METRICS_PROVIDER_INFO = {
        MetricsProviderType.STATIC: {
            # Namespace name
            None: {
                "providers": [
                    {
                        "name": "static_provider",
                        "provided_metrics": [
                            # (metric name at mp, metric value)
                            ("electricity_cost_1", 0.9),
                            ("green_energy_ratio_1", 0.1),
                        ],
                    },
                ],
                "metrics": [
                    {
                        "name": "electricity_cost_1",
                        "mp_name": "static_provider",
                        "min": 0,
                        "max": 1,
                    },
                    {
                        "name": "green_energy_ratio_1",
                        "mp_name": "static_provider",
                        "min": 0,
                        "max": 1,
                    },
                ],
            },
            NAMESPACE: {
                "providers": [
                    {
                        "name": "static_provider_w_namespace",
                        "provided_metrics": [
                            # (metric name at mp, metric value)
                            ("existing_nsed_metric", 0.9),
                        ],
                    },
                ],
                "metrics": [
                    {
                        "name": "existing_namespaced_metric",
                        "mp_name": "static_provider_w_namespace",
                        # metric name at mp
                        "mp_metric_name": "existing_nsed_metric",
                        "min": 0,
                        "max": 1,
                    },
                ],
            },
        },
        MetricsProviderType.PROMETHEUS: {
            # Namespace name
            None: {
                "providers": [
                    {
                        "name": "prometheus",
                        "provided_metrics": [
                            # (metric name at mp, metric value)
                            ("heat_demand_zone_1", 1),
                            ("heat_demand_zone_2", 2),
                            ("heat_demand_zone_3", 3),
                            ("heat_demand_zone_4", 4),
                            ("heat_demand_zone_5", 5),
                        ],
                        "url": "http://prometheus:9090",
                    },
                    {
                        "name": "prometheus-unreachable",
                        "provided_metrics": [
                            ("heat_demand_zone_unreachable", None),
                        ],
                        "url": "1.2.3.4:9090",
                    },
                ],
                "metrics": [
                    {
                        "name": "heat_demand_zone_1",
                        "mp_name": "prometheus",
                        "min": 0,
                        "max": 5,
                    },
                    {
                        "name": "heat_demand_zone_2",
                        "mp_name": "prometheus",
                        "min": 0,
                        "max": 5,
                    },
                    {
                        "name": "heat_demand_zone_3",
                        "mp_name": "prometheus",
                        "min": 0,
                        "max": 5,
                    },
                    {
                        "name": "heat_demand_zone_4",
                        "mp_name": "prometheus",
                        "min": 0,
                        "max": 5,
                    },
                    {
                        "name": "heat_demand_zone_5",
                        "mp_name": "prometheus",
                        "min": 0,
                        "max": 5,
                    },
                    {
                        "name": "heat_demand_zone_unreachable",
                        "mp_name": "prometheus-unreachable",
                        "min": 0,
                        "max": 5,
                    },
                ],
            },
        },
        MetricsProviderType.KAFKA: {},
    }

    @classmethod
    def _add_metrics_to_metrics_provider(cls, mp, metrics):
        """
        Add valued metrics to the metrics provider.

        Although only static metrics providers resources know about the values of the
        metrics they provide, we need to add valued metrics to metrics providers
        of all types, since they also need to be able to 'predict' which behaviour
        the actual metrics provider will have during the tests.

        Args:
            mp (BaseMetricsProviderDefinition): the metrics provider
            metrics (list[BaseMetricDefinition): the metrics
        """
        providers_info = cls._METRICS_PROVIDER_INFO[mp.type][mp.namespace]["providers"]
        provided_metrics = next(
            provider_info["provided_metrics"]
            for provider_info in providers_info
            if provider_info["name"] == mp.name
        )

        # Check if the provided metrics are equal to the metrics
        num_metrics = len(metrics)
        if len(provided_metrics) != num_metrics:
            raise ValueError(
                f"Found {len(provided_metrics)} metrics for metrics provider "
                f"{mp.name}. Expected {num_metrics}."
            )

        # Check what type of provider is used at the moment
        if mp.type == MetricsProviderType.STATIC:
            valued_metric_class = StaticMetric
        elif mp.type == MetricsProviderType.PROMETHEUS:
            valued_metric_class = PrometheusMetric
        else:
            raise NotImplementedError()
        # Iterate through the provided metrics
        valued_metrics = []
        for i, (metric_name, metric_value) in enumerate(provided_metrics):
            metric = metrics[i]
            if metric.mp_metric_name != metric_name:
                msg = (
                    f"Unexpected name {metric.mp_metric_name}. Expected: {metric_name}."
                )
                raise ValueError(msg)
            valued_metric = valued_metric_class(metric, metric_value)
            valued_metrics.append(valued_metric)
        mp.set_valued_metrics(valued_metrics)

    @classmethod
    def _init_metrics_providers(cls, mp_type, namespace, unreachable=False):
        """
        Create and return the metrics provider resource definition which
        matches the type and namespace parameters given.

        Args:
            mp_type (MetricsProviderType): the type of metrics provider to create.
            namespace (str, optional): the namespace of the metrics provider to create.
            unreachable (bool): flag indicating whether the metrics provider should be
                unreachable

        Returns:
            BaseMetricsProviderDefinition:
                The resource definition created.
        """
        kind = (
            ResourceKind.METRICSPROVIDER
            if namespace
            else ResourceKind.GLOBALMETRICSPROVIDER
        )
        providers_info = (
            cls._METRICS_PROVIDER_INFO.get(mp_type, {})
            .get(namespace, {})
            .get("providers", [])
        )
        mps = []
        for provider_info in providers_info:
            provider_is_unreachable = any(
                metric_value is None
                for (metric_name, metric_value) in provider_info["provided_metrics"]
            )
            if unreachable == provider_is_unreachable:
                mp_name = provider_info["name"]
                if mp_type == MetricsProviderType.STATIC:
                    # We do not add the metrics here since we need the metric resource
                    # definitions for that, and they are not yet instantiated.
                    # They are added later by calling _add_metrics_to_metrics_provider()
                    # in _init_metrics().
                    mps.append(
                        BaseStaticMetricsProviderDefinition(mp_name, kind, namespace)
                    )
                elif mp_type == MetricsProviderType.PROMETHEUS:
                    url = provider_info["url"]
                    mps.append(
                        BasePrometheusMetricsProviderDefinition(
                            mp_name, kind, namespace, url
                        )
                    )
                else:
                    raise NotImplementedError()
        return mps

    def _init_metrics(self, mp_type, namespace, unreachable=False):
        """
        Create and return the metric resource definitions which
        matches the type and namespace parameters given.

        Args:
            mp_type (MetricsProviderType): the type of the metrics provider providing
                the metrics to create
            namespace (str, optional): the namespace of the metrics to create.
            unreachable (bool): flag indicating whether the metrics provider providing
                these metrics is unreachable

        Returns:
            list(BaseMetricDefinition):
                list of the created metric resource definitions

        Raises:
            ValueError: if ResourceProvider.metrics_providers has not been initialized.
        """
        kind = ResourceKind.METRIC if namespace else ResourceKind.GLOBALMETRIC
        metrics_info = (
            self._METRICS_PROVIDER_INFO.get(mp_type, {})
            .get(namespace, {})
            .get("metrics", [])
        )

        # We will collect metrics from all metrics providers of the correct type
        # and in the correct namespace in the metrics list.
        metrics = []

        # all metrics providers of the correct type in the correct namespace
        if unreachable:
            mps_list = self.unreachable_metrics_providers
        else:
            mps_list = self.metrics_providers
        mps = mps_list.get(mp_type, {}).get(namespace, {})

        # Mapping from metrics provider resource definition to its metrics.
        # Initially empty.
        metrics_for_mp = dict.fromkeys([mp for mp in mps], [])
        for metric_info in metrics_info:
            # check if metric has the correct reachability. Skip if not.
            mp_name = metric_info["mp_name"]
            reachability_matches = True if mp_name in [mp.name for mp in mps] else False
            if reachability_matches:
                # Create and collect the metric
                metric_name = metric_info["name"]
                mp_metric_name = metric_info.get("mp_metric_name", None)
                metric = BaseMetricDefinition(
                    metric_name,
                    kind,
                    namespace,
                    metric_info["min"],
                    metric_info["max"],
                    mp_name,
                    mp_metric_name=mp_metric_name,
                )
                metrics.append(metric)

                # remember its metrics provider for performance reasons
                mps_w_correct_name = [mp for mp in mps if mp.name == mp_name]
                if len(mps_w_correct_name) != 1:
                    msg = (
                        f"Expected 1 metrics provider with the name {mp_name}. "
                        f"Found {len(mps_w_correct_name)}."
                    )
                    raise ValueError(msg)
                mp = mps_w_correct_name[0]
                self._metric_to_metrics_provider[metric] = mp

                # save this metric to the metrics provider so it can be added later.
                metrics_for_mp[mp].append(metric)

        # The metrics providers need their metrics, so we add them here - also for
        # non-static metrics providers, since information about the metrics they
        # provide is needed in the tests.
        sanity_check_number_of_metrics = 0
        for mp, mp_metrics in metrics_for_mp.items():
            sanity_check_number_of_metrics += len(mp_metrics)
            self._add_metrics_to_metrics_provider(mp, mp_metrics)
        if len(metrics) != sanity_check_number_of_metrics:
            msg = (
                f"Expected {len(metrics)} and {sanity_check_number_of_metrics} "
                f"to be equal."
            )
            raise ValueError(msg)

        return metrics


    def get_metrics_provider(self, metric):
        """
        Return the metrics provider resource definition which
        matches the type and namespace parameters given.

        Args:
            metric (BaseMetricDefinition): the resource definition of the metric
                which metrics provider is sought

        Returns:
            BaseMetricsProviderDefinition:
                The metrics provider resource definition.
        """
        return self._metric_to_metrics_provider[metric]

    def get_metrics_in_namespace(
        self, sample_size, namespace, mp_type, unreachable=False
    ):
        """
        Return list of sample_size random metrics provided by a metrics provider
        of the given type.

        Args:
            sample_size (int): the number of metrics
            namespace (str, optional): the namespace of the desired metrics
            mp_type (MetricsProviderType): the type of the metrics provider that
                should be providing the metrics
            unreachable (bool): flag indicating whether the metrics should be
                unreachable

        Returns:
            list(BaseMetricDefinition):
                list of sample_size randomly selected metric resource definitions.

        Raises:
            ValueError:
                if fewer than sample_size metrics were found
        """
        metrics = list(self.metrics.get(mp_type, {}).get(namespace, {}))
        desired_metrics = [
            m for m in metrics if unreachable == self._is_unreachable(m, mp_type)
        ]
        if len(desired_metrics) < sample_size:
            unreachable_str = "unreachable" if unreachable else "reachable"
            msg = (
                f"There are not enough {unreachable_str} metrics. Needed "
                f"{sample_size}, found {len(desired_metrics)}: {desired_metrics}."
            )
            raise ValueError(msg)
        return random.sample(desired_metrics, sample_size)

    def get_metrics(
        self,
        sample_size,
        namespaced=False,
        mp_type=MetricsProviderType.STATIC,
        unreachable=False,
    ):
        """
        Return list of sample_size random metrics provided by a metrics provider
        of the given type.

        Args:
            sample_size (int): the number of metrics
            namespaced (bool): flag indicating whether the metrics should be
                namespaced
            mp_type (MetricsProviderType): the type of the metrics provider that
                should be providing the metrics
            unreachable (bool): flag indicating whether unreachable metrics
                should be included

        Returns:
            list(BaseMetricDefinition):
                list of sample_size randomly selected metric resource definitions.

        Raises:
            ValueError:
                if fewer than sample_size metrics were found
        """
        namespace = NAMESPACE if namespaced else None
        return self.get_metrics_in_namespace(
            namespace, sample_size, mp_type, unreachable
        )

    def _is_unreachable(self, m, mp_type):
        return m in self.unreachable_metrics.get(mp_type, {}).get(m.namespace, {})

    def get_global_static_metrics_provider(self):
        mps = self.metrics_providers[MetricsProviderType.STATIC][None]
        if len(mps) != 1:
            raise ValueError(
                f"Expected 1 global static metrics provider. " f"Found {len(mps)}."
            )
        return mps[0]

    def get_namespaced_static_metrics_provider(self):
        mps = self.metrics_providers[MetricsProviderType.STATIC][NAMESPACE]
        if len(mps) != 1:
            raise ValueError(
                f"Expected 1 namespaced static metrics provider. " f"Found {len(mps)}."
            )
        return mps[0]

    def get_global_prometheus_metrics_provider(self, reachable=True):
        if reachable:
            mps = self.metrics_providers[MetricsProviderType.PROMETHEUS][None]
        else:
            mps = self.unreachable_metrics_providers[MetricsProviderType.PROMETHEUS][
                None
            ]
        if len(mps) != 1:
            raise ValueError(
                f"Expected 1 global prometheus metrics provider "
                f"(reachable={reachable}). Found {len(mps)}."
            )
        return mps[0]


provider = ResourceProvider()
