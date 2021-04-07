"""core subcommands

.. code:: bash

    python -m rok core --help

"""
from enum import Enum

from .parser import (
    ParserSpec,
    argument,
    arg_namespace,
    arg_formatting,
    MetricAction,
)
from .fixtures import depends
from .formatters import (
    BaseTable,
    Cell,
    printer,
    dict_formatter,
)

# Parsers
core = ParserSpec("core", aliases=[], help="Manage core resources")

metrics_provider = core.subparser(
    "metricsprovider", aliases=["mp"], help="Manage metrics providers"
)
metric = core.subparser("metric", help="Manage metrics")

global_metrics_provider = core.subparser(
    "globalmetricsprovider", aliases=["gmp"], help="Manage global metrics providers"
)
global_metric = core.subparser(
    "globalmetric", aliases=["gm"], help="Manage global metrics"
)


# Base urls for namespaced metrics and metrics providers
NAMESPACE_URL_FORMAT = "/namespaces/{namespace}"
METRICS_PROVIDER_BASE_URL = f"/core{NAMESPACE_URL_FORMAT}/metricsproviders"
METRIC_BASE_URL = f"/core{NAMESPACE_URL_FORMAT}/metrics"

LIST_ALL_METRICS_PROVIDER_BASE_URL = "/core/metricsproviders"
LIST_ALL_METRIC_BASE_URL = "/core/metrics"

# Base urls for global metrics and metrics providers
GLOBAL_METRICS_PROVIDER_BASE_URL = "/core/globalmetricsproviders"
GLOBAL_METRIC_BASE_URL = "/core/globalmetrics"


# CRUD REST API methods for general access


def _create_base_resource(session, base_url, resource, config=None, namespace=None):
    request_url = _get_request_url(base_url, config=config, namespace=namespace)
    resp = session.post(request_url, json=resource)
    return resp.json()


def _list_base_resource(session, base_url, config=None, namespace=None):
    request_url = _get_request_url(base_url, config=config, namespace=namespace)
    resp = session.get(request_url)
    body = resp.json()
    return body["items"]


def _get_base_resource(session, base_url, kind, name, config=None, namespace=None):
    request_url = _get_request_url(
        base_url, config=config, namespace=namespace, url_ext=name
    )
    resp = session.get(request_url, raise_for_status=False)
    return resp.json()


def _update_base_resource(
    session, base_url, resource, name, config=None, namespace=None
):
    request_url = _get_request_url(
        base_url, config=config, namespace=namespace, url_ext=name
    )
    resp = session.put(request_url, json=resource, raise_for_status=False)
    return resp.json()


def _delete_base_resource(session, base_url, kind, name, config=None, namespace=None):
    request_url = _get_request_url(
        base_url, config=config, namespace=namespace, url_ext=name
    )
    resp = session.delete(request_url, raise_for_status=False)

    if resp.status_code == 204:
        return None
    return resp.json()


def _get_request_url(base_url, config=None, namespace="", url_ext=""):
    if namespace and not config:
        raise ValueError(
            f"Expected a config together with namespace '{namespace}'. "
            f"base_url: '{base_url}'. url_ext: '{url_ext}'."
        )
    if config and not namespace:
        namespace = config["user"]
    _validate_namespace(namespace, base_url)
    base_url = base_url.format(namespace=namespace)
    return "/".join([base_url, url_ext]) if url_ext else base_url


def _validate_namespace(namespace, base_url):
    """Validate the provided namespace and base_url against each other.

    Args:
        base_url (str): the base url at which the krake API serves the request
        namespace (str, optional): the namespace within which the resource
            should be created

    Raises:
         SystemExit: if the parameters are invalid
    """
    if NAMESPACE_URL_FORMAT in base_url:
        if not namespace:
            raise ValueError(f"No namespace was provided for the url '{base_url}'")
    else:
        if namespace:
            if base_url not in [
                LIST_ALL_METRICS_PROVIDER_BASE_URL,
                LIST_ALL_METRIC_BASE_URL,
            ]:
                raise ValueError(
                    f"Namespace '{namespace}' was provided for the url '{base_url}'"
                )


# ################ Managing metrics providers


class _MetricsProviderType(Enum):
    PROMETHEUS = "prometheus"
    STATIC = "static"
    KAFKA = "kafka"


class BaseMetricsProviderListTable(BaseTable):
    mp_type = Cell("spec.type", name="type")


class BaseMetricsProviderTable(BaseMetricsProviderListTable):
    def draw(self, table, data, file):
        mp_type_str = _MetricsProviderType(data["spec"]["type"])

        mp_attrs = {
            _MetricsProviderType.PROMETHEUS: {"url": None},
            _MetricsProviderType.STATIC: {"metrics": dict_formatter},
            _MetricsProviderType.KAFKA: dict.fromkeys(
                ["url", "comparison_column", "value_column", "table"]
            ),
        }

        try:
            mp_type = _MetricsProviderType(mp_type_str)
        except ValueError:
            mp_type = None

        if mp_type in mp_attrs:
            for attr, formatter in mp_attrs[mp_type].items():
                if attr in self.cells:
                    raise ValueError(
                        f"Invalid state: '{attr}' attribute was already set."
                    )
                key = f"spec.{mp_type.value}.{attr}"
                self.cells.update({attr: Cell(key, name=attr, formatter=formatter)})
        else:
            data["spec"][
                "type"
            ] = f"ERROR: invalid global metrics provider type: '{mp_type_str}'"

        super().draw(table, data, file)


def _list_base_metrics_providers(session, base_url, config=None, namespace=None):
    return _list_base_resource(session, base_url, config=config, namespace=namespace)


@globalmetricsprovider.command("create", help="Create a global metrics provider")
@argument("--name", required=True, help="Global metrics provider name")
@argument(
    "--url",
    help=f"Global metrics provider url. "
    f"Not valid together with --type {_MetricsProviderType.STATIC}.",
)
@argument(
    "--type",
    dest="mp_type",
    required=True,
    help=f"Global metrics provider type. Valid types: "
    f"{', '.join(t.value for t in _MetricsProviderType)}",
)
@argument(
    "-m",
    "--metric",
    action=MetricAction,
    dest="metrics",
    help=f"Name and value of a global metric the provider provides. "
    f"Can be specified multiple times. "
    f"Only valid together with --type {_MetricsProviderType.STATIC}.",
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid together with "
    f"--type {_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--comparison-column",
    help=f"Name of the column whose value will be compared to the metric name "
    f"when selecting a metric. Only valid together with --type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--value-column",
    help=f"Name of the column where the value of a metric is stored. "
    f"Only valid together with --type {_MetricsProviderType.KAFKA.value}.",
)
@arg_formatting
@depends("session")
@printer(table=BaseMetricsProviderTable())
def _create_base_metrics_provider(
    session,
    base_url,
    kind,
    name,
    url,
    mp_type,
    metrics,
    comparison_column,
    value_column,
    table,
    config=None,
    namespace=None,
):
    _validate_for_create_base_mp(
        mp_type, metrics, url, comparison_column, value_column, table
    )

    mp_type = _MetricsProviderType(mp_type)
    if mp_type == _MetricsProviderType.PROMETHEUS:
        type_dict = {"url": url}
    elif mp_type == _MetricsProviderType.STATIC:
        type_dict = {"metrics": {m["name"]: m["weight"] for m in metrics}}
    elif mp_type == _MetricsProviderType.KAFKA:
        type_dict = {
            "url": url,
            "comparison_column": comparison_column,
            "value_column": value_column,
            "table": table,
        }
    else:
        raise SystemExit(f"Invalid metrics provider type: '{mp_type}'")

    mp = {
        "api": "core",
        "kind": kind,
        "metadata": {
            "name": name,
        },
        "spec": {
            "type": mp_type.value,
            mp_type.value: type_dict,
        },
    }

    return _create_base_resource(
        session, base_url, mp, config=config, namespace=namespace
    )
    # resp = session.post(GLOBAL_METRICS_PROVIDER_BASE_URL, json=mp)
    # return resp.json()


def _validate_for_create_base_mp(
    mp_type_str, metrics, url, comparison_column, value_column, table
):
    """Validate the provided parameters as input parameters for the
    _create_base_metrics_provider() method.

    Args:
        mp_type_str (str): the value provided with the --type argument
        metrics (list[dict[str, float], optional): the value provided with the
            --metric argument
        url (str, optional): the value provided with the --url argument
        comparison_column (str, optional): the value provided with the
            --comparison-column argument
        value_column (str, optional): the value provided with the
            --value-column argument
        table (str, optional): the value provided with the --table argument

    Raises:
         SystemExit: if the parameters are invalid
    """

    try:
        mp_type = _MetricsProviderType(mp_type_str)
    except ValueError:
        raise SystemExit(f"Invalid metrics provider type: '{mp_type_str}'")

    required_parameters = {
        _MetricsProviderType.PROMETHEUS: {
            "url": url,
        },
        _MetricsProviderType.STATIC: {
            "metric": metrics,
        },
        _MetricsProviderType.KAFKA: {
            "url": url,
            "comparison-column": comparison_column,
            "value-column": value_column,
            "table": table,
        },
    }
    err_msg_fmt = (
        "Metrics provider type '{mp_type}' " "requires --{attr} to be specified"
    )
    for var_name, var in required_parameters[mp_type].items():
        if not var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))


def _get_base_metrics_provider(
    session, base_url, kind, name, config=None, namespace=None
):
    return _get_base_resource(
        session, base_url, kind, name, config=config, namespace=namespace
    )


def _validate_for_update_base_mp(
    mp_type_str, metrics, url, comparison_column, value_column, table
):
    """Validate the provided parameters as input parameters for the
    update_base_metrics_provider() method.

    Args:
        mp_type_str (str): the value provided with the --type argument
        metrics (list[dict[str, float], optional): the value provided with the
            --metric argument
        url (str, optional): the value provided with the --url argument
        comparison_column (str, optional): the value provided with the
            --comparison-column argument
        value_column (str, optional): the value provided with the
            --value-column argument
        table (str, optional): the value provided with the --table argument

    Raises:
         SystemExit: if the parameters are invalid
    """
    try:
        mp_type = _MetricsProviderType(mp_type_str)
    except ValueError:
        raise SystemExit(f"Invalid metrics provider type: '{mp_type_str}'")

    required_parameters = {
        _MetricsProviderType.PROMETHEUS: {
            "url": url,
        },
        _MetricsProviderType.STATIC: {
            "metric": metrics,
        },
        _MetricsProviderType.KAFKA: {},
    }
    err_msg_fmt = "Metrics provider type '{mp_type}' requires --{attr} to be specified"
    for var_name, var in required_parameters[mp_type].items():
        if not var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))

    disallowed_parameters = {
        _MetricsProviderType.PROMETHEUS: {
            "metric": metrics,
            "comparison-column": comparison_column,
            "value-column": value_column,
            "table": table,
        },
        _MetricsProviderType.STATIC: {
            "url": url,
            "comparison-column": comparison_column,
            "value-column": value_column,
            "table": table,
        },
        _MetricsProviderType.KAFKA: {
            "metric": metrics,
        },
    }
    err_msg_fmt = (
        "--{attr} is not a valid argument for " "metrics providers of type {mp_type}"
    )
    for var_name, var in disallowed_parameters[mp_type].items():
        if var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))


def _update_base_metrics_provider(
    session,
    base_url,
    kind,
    name,
    mp_url,
    metrics,
    comparison_column,
    value_column,
    table,
    config=None,
    namespace=None,
):
    mp = _get_base_metrics_provider(
        session, base_url, kind, name, config=config, namespace=namespace
    )
    mp_type = mp["spec"]["type"]

    _validate_for_update_base_mp(
        mp_type, metrics, mp_url, comparison_column, value_column, table
    )

    if metrics:
        mp["spec"][mp_type]["metrics"] = {m["name"]: m["weight"] for m in metrics}
    if mp_url:
        mp["spec"][mp_type]["url"] = mp_url
    if comparison_column:
        mp["spec"][mp_type]["comparison_column"] = comparison_column
    if value_column:
        mp["spec"][mp_type]["value_column"] = value_column
    if table:
        mp["spec"][mp_type]["table"] = table
    return _update_base_resource(
        session, base_url, mp, name, config=config, namespace=namespace
    )


def _delete_base_metrics_provider(
    session, base_url, kind, name, config=None, namespace=None
):
    return _delete_base_resource(
        session, base_url, kind, name, config=config, namespace=namespace
    )


# ################ Managing namespaced metrics providers


@metrics_provider.command("list", help="List metrics providers")
@argument(
    "-a", "--all", action="store_true", help="Show metrics providers in all namespaces"
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricsProviderListTable(many=True))
def list_metricsproviders(config, session, namespace, all):
    base_url = LIST_ALL_METRICS_PROVIDER_BASE_URL if all else METRICS_PROVIDER_BASE_URL
    return _list_base_metrics_providers(
        session, base_url, config=config, namespace=namespace
    )


@metrics_provider.command("create", help="Create a metrics provider")
@argument(
    "--url",
    help=f"Metrics provider url. "
    f"Not valid together with --type {_MetricsProviderType.STATIC}.",
)
@argument(
    "--type",
    dest="mp_type",
    required=True,
    help=f"Metrics provider type. Valid types: "
    f"{', '.join(t.value for t in _MetricsProviderType)}",
)
@argument(
    "-m",
    "--metric",
    action=MetricAction,
    dest="metrics",
    help=f"Name and value of a metric the provider provides. "
    f"Can be specified multiple times. "
    f"Only valid together with --type {_MetricsProviderType.STATIC}.",
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid together with "
    f"--type {_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--comparison-column",
    help=f"Name of the column whose value will be compared to the metric name "
    f"when selecting a metric. Only valid together with --type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--value-column",
    help=f"Name of the column where the value of a metric is stored. "
    f"Only valid together with --type {_MetricsProviderType.KAFKA.value}.",
)
@argument("name", help="Name of the metrics provider")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricsProviderTable())
def create_metricsprovider(
    config,
    session,
    namespace,
    url,
    mp_type,
    metrics,
    comparison_column,
    value_column,
    table,
    name,
):
    return _create_base_metrics_provider(
        session,
        METRICS_PROVIDER_BASE_URL,
        "MetricsProvider",
        name,
        url,
        mp_type,
        metrics,
        comparison_column,
        value_column,
        table,
        config=config,
        namespace=namespace,
    )


@metrics_provider.command("get", help="Get a metrics provider")
@argument("name", help="Metrics provider name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricsProviderTable())
def get_metricsprovider(config, session, namespace, name):
    return _get_base_metrics_provider(
        session,
        METRICS_PROVIDER_BASE_URL,
        "MetricsProvider",
        name,
        config=config,
        namespace=namespace,
    )


@metrics_provider.command("update", help="Update metrics provider")
@argument("name", help="Metrics provider name")
@argument(
    "--url",
    dest="mp_url",
    help=f"Metrics provider url. "
    f"Not valid for metrics providers of type "
    f"{_MetricsProviderType.STATIC}",
)
@argument(
    "--metric",
    "-m",
    dest="metrics",
    action=MetricAction,
    help=(
        f"Name and value of a metric to be updated. "
        f"Can be specified multiple times. "
        f"Only valid for metrics providers of type "
        f"{_MetricsProviderType.STATIC}."
    ),
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid for metrics providers of type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--comparison-column",
    help=f"Name of the column whose value will be compared to the metric name "
    f"when selecting a metric. Only valid for metrics providers of type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--value-column",
    help=f"Name of the column where the value of a metric is stored. "
    f"Only valid for metrics providers of type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricsProviderTable())
def update_metricsprovider(
    config,
    session,
    namespace,
    name,
    mp_url,
    metrics,
    comparison_column,
    value_column,
    table,
):
    return _update_base_metrics_provider(
        session,
        METRICS_PROVIDER_BASE_URL,
        "MetricsProvider",
        name,
        mp_url,
        metrics,
        comparison_column,
        value_column,
        table,
        config=config,
        namespace=namespace,
    )


@metrics_provider.command("delete", help="Delete metrics provider")
@argument("name", help="Metrics provider name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricsProviderTable())
def delete_metricsprovider(config, session, namespace, name):
    return _delete_base_metrics_provider(
        session,
        METRICS_PROVIDER_BASE_URL,
        "MetricsProvider",
        name,
        config=config,
        namespace=namespace,
    )


# ################ Managing global metrics providers


@global_metrics_provider.command("list", help="List global metrics providers")
@arg_formatting
@depends("session")
@printer(table=BaseMetricsProviderListTable(many=True))
def list_globalmetricsproviders(session):
    return _list_base_metrics_providers(session, GLOBAL_METRICS_PROVIDER_BASE_URL)


@global_metrics_provider.command("create", help="Create a global metrics provider")
@argument(
    "--url",
    help=f"Global metrics provider url. "
    f"Not valid together with --type {_MetricsProviderType.STATIC}.",
)
@argument(
    "--type",
    dest="mp_type",
    required=True,
    help=f"Global metrics provider type. Valid types: "
    f"{', '.join(t.value for t in _MetricsProviderType)}",
)
@argument(
    "-m",
    "--metric",
    action=MetricAction,
    dest="metrics",
    help=f"Name and value of a global metric the provider provides. "
    f"Can be specified multiple times. "
    f"Only valid together with --type {_MetricsProviderType.STATIC}.",
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid together with "
    f"--type {_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--comparison-column",
    help=f"Name of the column whose value will be compared to the metric name "
    f"when selecting a metric. Only valid together with --type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--value-column",
    help=f"Name of the column where the value of a metric is stored. "
    f"Only valid together with --type {_MetricsProviderType.KAFKA.value}.",
)
@argument("name", help="Name of the global metrics provider")
@arg_formatting
@depends("session")
@printer(table=BaseMetricsProviderTable())
def create_globalmetricsprovider(
    session, url, mp_type, metrics, comparison_column, value_column, table, name
):
    return _create_base_metrics_provider(
        session,
        GLOBAL_METRICS_PROVIDER_BASE_URL,
        "GlobalMetricsProvider",
        name,
        url,
        mp_type,
        metrics,
        comparison_column,
        value_column,
        table,
    )


@global_metrics_provider.command("get", help="Get a global metrics provider")
@argument("name", help="Global metrics provider name")
@arg_formatting
@depends("session")
@printer(table=BaseMetricsProviderTable())
def get_globalmetricsprovider(session, name):
    return _get_base_metrics_provider(
        session, GLOBAL_METRICS_PROVIDER_BASE_URL, "GlobalMetricsProvider", name
    )


@global_metrics_provider.command("update", help="Update global metrics provider")
@argument("name", help="Global metrics provider name")
@argument(
    "--url",
    dest="mp_url",
    help=f"Global metrics provider url. "
    f"Not valid for global metrics providers of type "
    f"{_MetricsProviderType.STATIC}",
)
@argument(
    "--metric",
    "-m",
    dest="metrics",
    action=MetricAction,
    help=(
        f"Name and value of a global metric to be updated. "
        f"Can be specified multiple times. "
        f"Only valid for global metrics providers of type "
        f"{_MetricsProviderType.STATIC}."
    ),
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid for global metrics providers of type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--comparison-column",
    help=f"Name of the column whose value will be compared to the metric name "
    f"when selecting a metric. Only valid for global metrics providers of type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@argument(
    "--value-column",
    help=f"Name of the column where the value of a metric is stored. "
    f"Only valid for global metrics providers of type "
    f"{_MetricsProviderType.KAFKA.value}.",
)
@arg_formatting
@depends("session")
@printer(table=BaseMetricsProviderTable())
def update_globalmetricsprovider(
    session,
    name,
    mp_url,
    metrics,
    comparison_column,
    value_column,
    table,
):
    return _update_base_metrics_provider(
        session,
        GLOBAL_METRICS_PROVIDER_BASE_URL,
        "GlobalMetricsProvider",
        name,
        mp_url,
        metrics,
        comparison_column,
        value_column,
        table,
    )


@global_metrics_provider.command("delete", help="Delete global metrics provider")
@argument("name", help="Global metrics provider name")
@arg_formatting
@depends("session")
@printer(table=BaseMetricsProviderTable())
def delete_globalmetricsprovider(session, name):
    return _delete_base_metrics_provider(
        session, GLOBAL_METRICS_PROVIDER_BASE_URL, "GlobalMetricsProvider", name
    )


# ################ Managing metrics


class BaseMetricListTable(BaseTable):
    provider = Cell("spec.provider.name")
    min = Cell("spec.min")
    max = Cell("spec.max")


class BaseMetricTable(BaseMetricListTable):
    pass


def _list_base_metrics(session, base_url, config=None, namespace=None):
    return _list_base_resource(session, base_url, config=config, namespace=namespace)


def _create_base_metric(
    session,
    base_url,
    kind,
    name,
    mp_name,
    min,
    max,
    metric_name,
    config=None,
    namespace=None,
):
    if not metric_name:
        metric_name = name
    metric = {
        "api": "core",
        "kind": kind,
        "metadata": {
            "name": name,
        },
        "spec": {
            "max": max,
            "min": min,
            "provider": {
                "metric": metric_name,
                "name": mp_name,
            },
        },
    }

    return _create_base_resource(
        session, base_url, metric, config=config, namespace=namespace
    )


def _get_base_metric(session, base_url, kind, name, config=None, namespace=None):
    return _get_base_resource(
        session, base_url, kind, name, config=config, namespace=namespace
    )


def _update_base_metric(
    session,
    base_url,
    kind,
    name,
    max,
    min,
    mp_name,
    metric_name,
    config=None,
    namespace=None,
):
    if not (max or min or mp_name or metric_name):
        raise SystemExit("At least one argument must be specified.")

    metric = _get_base_metric(
        session, base_url, kind, name, config=config, namespace=namespace
    )
    if max:
        metric["spec"]["max"] = max
    if min:
        metric["spec"]["min"] = min
    if mp_name:
        metric["spec"]["provider"]["name"] = mp_name
    if metric_name:
        metric["spec"]["provider"]["metric"] = metric_name

    return _update_base_resource(
        session, base_url, metric, name, config=config, namespace=namespace
    )


def _delete_base_metric(session, base_url, kind, name, config=None, namespace=None):
    return _delete_base_resource(
        session, base_url, kind, name, config=config, namespace=namespace
    )


# ################ Managing namespaced metrics


@metric.command("list", help="List metrics")
@argument("-a", "--all", action="store_true", help="Show metrics in all namespaces")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricListTable(many=True))
def list_metrics(config, session, namespace, all):
    base_url = LIST_ALL_METRIC_BASE_URL if all else METRIC_BASE_URL
    return _list_base_metrics(session, base_url, config=config, namespace=namespace)


@metric.command("create", help="Create a metric")
@argument("--mp-name", required=True, help="Metrics provider name")
@argument("--min", required=True, help="Minimum value of the metric")
@argument("--max", required=True, help="Maximum value of the metric")
@argument(
    "--metric-name",
    help="Name of the metric which the metrics provider provides. "
    "As default the name of the created metric resource is used.",
)
@argument("name", help="Name of the metric")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricTable())
def create_metric(
    config, session, namespace, name, mp_name, min, max, metric_name=None
):
    """Create a Metric resource.

    Args:
        config (dict): the config
        session (requests.Session): the session used to connect to the krake API
        namespace (str): the namespace in which the resource should be created
        name (str): Name of the metric
        mp_name (str): Name of the metrics provider
        min (str): The minimum value of the metric
        max (str): The maximum value of the metric
        metric_name (str): The name used to identify the metric at the endpoint
            of the metrics provider

    Returns:
        dict(str, object): The created Metric resource in json representation
    """
    return _create_base_metric(
        session,
        METRIC_BASE_URL,
        "Metric",
        name,
        mp_name,
        min,
        max,
        metric_name,
        config=config,
        namespace=namespace,
    )


@metric.command("get", help="Get a metric")
@argument("name", help="Metric name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricTable())
def get_metric(config, session, namespace, name):
    return _get_base_metric(
        session, METRIC_BASE_URL, "Metric", name, config=config, namespace=namespace
    )


@metric.command("update", help="Update metric")
@argument("name", help="Metric name")
@argument("--min", help="Minimum value of the metric")
@argument("--max", help="Maximum value of the metric")
@argument("--mp-name", help="Metrics provider name'")
@argument(
    "--metric-name",
    help="Name of the metric which the metrics provider provides.",
)
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricTable())
def update_metric(config, session, namespace, name, max, min, mp_name, metric_name):
    """Update a Metric resource.

    Args:
        config (dict): the config fixture
        session (requests.Session): the session used to connect to the krake API
        namespace (str): the namespace to which the metric belongs
        name (str): Name of the metric
        max (str): The maximum value of the metric
        min (str): The minimum value of the metric
        mp_name (str): Name of the metrics provider
        metric_name (str): The name used to identify the metric at the endpoint
            of the metrics provider

    Returns:
        dict(str, object): The updated Metric resource in json representation
    """
    return _update_base_metric(
        session,
        METRIC_BASE_URL,
        "Metric",
        name,
        max,
        min,
        mp_name,
        metric_name,
        config=config,
        namespace=namespace,
    )


@metric.command("delete", help="Delete metric")
@argument("name", help="Metric name")
@arg_namespace
@arg_formatting
@depends("config", "session")
@printer(table=BaseMetricTable())
def delete_metric(config, session, namespace, name):
    return _delete_base_metric(
        session, METRIC_BASE_URL, "Metric", name, config=config, namespace=namespace
    )


# ################ Managing global metrics


@global_metric.command("list", help="List global metrics")
@arg_formatting
@depends("session")
@printer(table=BaseMetricListTable(many=True))
def list_globalmetrics(session):
    return _list_base_metrics(session, GLOBAL_METRIC_BASE_URL)


@global_metric.command("create", help="Create a global metric")
@argument("--gmp-name", required=True, help="Global metrics provider name")
@argument("--min", required=True, help="Minimum value of the global metric")
@argument("--max", required=True, help="Maximum value of the global metric")
@argument(
    "--metric-name",
    help="Name of the global metric which the global metrics provider provides. "
    "As default the name of the created global metric resource is used.",
)
@argument("name", help="Name of the global metric")
@arg_formatting
@depends("session")
@printer(table=BaseMetricTable())
def create_globalmetric(session, name, gmp_name, min, max, metric_name=None):
    """Create a GlobalMetric resource.

    Args:
        session (requests.Session): the session used to connect to the krake API
        name (str): Name of the global metric
        gmp_name (str): Name of the global metrics provider
        min (str): The minimum value of the global metric
        max (str): The maximum value of the global metric
        metric_name (str): The name used to identify the global metric at the endpoint
            of the global metrics provider

    Returns:
        dict(str, object): The created GlobalMetric resource in json representation
    """
    return _create_base_metric(
        session,
        GLOBAL_METRIC_BASE_URL,
        "GlobalMetric",
        name,
        gmp_name,
        min,
        max,
        metric_name,
    )


@global_metric.command("get", help="Get a global metric")
@argument("name", help="Global metric name")
@arg_formatting
@depends("session")
@printer(table=BaseMetricTable())
def get_globalmetric(session, name):
    return _get_base_metric(session, GLOBAL_METRIC_BASE_URL, "GlobalMetric", name)


@global_metric.command("update", help="Update global metric")
@argument("name", help="Global metric name")
@argument("--min", help="Minimum value of the global metric")
@argument("--max", help="Maximum value of the global metric")
@argument("--gmp-name", help="Global metrics provider name'")
@argument(
    "--metric-name",
    help="Name of the global metric which the global metrics provider provides.",
)
@arg_formatting
@depends("session")
@printer(table=BaseMetricTable())
def update_globalmetric(session, name, max, min, gmp_name, metric_name):
    """Update a GlobalMetric resource.

    Args:
        session (requests.Session): the session used to connect to the krake API
        name (str): Name of the global metric
        max (str): The maximum value of the global metric
        min (str): The minimum value of the global metric
        gmp_name (str): Name of the global metrics provider
        metric_name (str): The name used to identify the global metric at the endpoint
            of the global metrics provider

    Returns:
        dict(str, object): The updated GlobalMetric resource in json representation
    """
    return _update_base_metric(
        session,
        GLOBAL_METRIC_BASE_URL,
        "GlobalMetric",
        name,
        max,
        min,
        gmp_name,
        metric_name,
    )


@global_metric.command("delete", help="Delete global metric")
@argument("name", help="Global metric name")
@arg_formatting
@depends("session")
@printer(table=BaseMetricTable())
def delete_globalmetric(session, name):
    return _delete_base_metric(session, GLOBAL_METRIC_BASE_URL, "GlobalMetric", name)
