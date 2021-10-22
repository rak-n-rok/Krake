"""core subcommands

.. code:: bash

    python -m rok core --help

"""
from enum import Enum

from .parser import (
    ParserSpec,
    argument,
    arg_formatting,
    MetricAction,
)
from .fixtures import depends, rok_response_handler
from .formatters import (
    BaseTable,
    Cell,
    printer,
    dict_formatter,
)

GLOBAL_METRICS_PROVIDER_BASE_URL = "/core/globalmetricsproviders"
GLOBAL_METRIC_BASE_URL = "/core/globalmetrics"


class _GlobalMetricsProviderType(Enum):
    PROMETHEUS = "prometheus"
    STATIC = "static"
    KAFKA = "kafka"


core = ParserSpec("core", aliases=[], help="Manage core resources")


# ################ Managing global metrics providers


globalmetricsprovider = core.subparser(
    "globalmetricsprovider", aliases=["gmp"], help="Manage global metrics providers"
)


class GlobalMetricsProviderListTable(BaseTable):
    mp_type = Cell("spec.type", name="type")


class GlobalMetricsProviderTable(GlobalMetricsProviderListTable):
    def draw(self, table, data, file):
        mp_type_str = _GlobalMetricsProviderType(data["spec"]["type"])

        mp_attrs = {
            _GlobalMetricsProviderType.PROMETHEUS: {"url": None},
            _GlobalMetricsProviderType.STATIC: {"metrics": dict_formatter},
            _GlobalMetricsProviderType.KAFKA: dict.fromkeys(
                ["url", "comparison_column", "value_column", "table"]
            ),
        }

        try:
            mp_type = _GlobalMetricsProviderType(mp_type_str)
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


@globalmetricsprovider.command("list", help="List global metrics providers")
@arg_formatting
@depends("session")
@printer(table=GlobalMetricsProviderListTable(many=True))
def list_globalmetricsproviders(session):
    url = GLOBAL_METRICS_PROVIDER_BASE_URL
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@globalmetricsprovider.command("create", help="Create a global metrics provider")
@argument("--name", required=True, help="Global metrics provider name")
@argument(
    "--url",
    help=f"Global metrics provider url. "
    f"Not valid together with --type {_GlobalMetricsProviderType.STATIC}.",
)
@argument(
    "--type",
    dest="mp_type",
    required=True,
    help=f"Global metrics provider type. Valid types: "
    f"{', '.join(t.value for t in _GlobalMetricsProviderType)}",
)
@argument(
    "-m",
    "--metric",
    action=MetricAction,
    dest="metrics",
    help=f"Name and value of a global metric the provider provides. "
    f"Can be specified multiple times. "
    f"Only valid together with --type {_GlobalMetricsProviderType.STATIC}.",
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid together with "
    f"--type {_GlobalMetricsProviderType.KAFKA.value}.",
)
@argument(
    "--comparison-column",
    help=f"Name of the column whose value will be compared to the metric name "
    f"when selecting a metric. Only valid together with --type "
    f"{_GlobalMetricsProviderType.KAFKA.value}.",
)
@argument(
    "--value-column",
    help=f"Name of the column where the value of a metric is stored. "
    f"Only valid together with --type {_GlobalMetricsProviderType.KAFKA.value}.",
)
@arg_formatting
@depends("session")
@printer(table=GlobalMetricsProviderTable())
@rok_response_handler
def create_globalmetricsprovider(
    session, name, url, mp_type, metrics, comparison_column, value_column, table
):
    _validate_for_create_gmp(
        mp_type, metrics, url, comparison_column, value_column, table
    )

    mp_type = _GlobalMetricsProviderType(mp_type)
    if mp_type == _GlobalMetricsProviderType.PROMETHEUS:
        type_dict = {"url": url}
    elif mp_type == _GlobalMetricsProviderType.STATIC:
        type_dict = {"metrics": {m["name"]: m["weight"] for m in metrics}}
    elif mp_type == _GlobalMetricsProviderType.KAFKA:
        type_dict = {
            "url": url,
            "comparison_column": comparison_column,
            "value_column": value_column,
            "table": table,
        }
    else:
        raise SystemExit(f"Invalid global metrics provider type: '{mp_type}'")

    mp = {
        "api": "core",
        "kind": "GlobalMetricsProvider",
        "metadata": {
            "name": name,
        },
        "spec": {
            "type": mp_type.value,
            mp_type.value: type_dict,
        },
    }

    resp = session.post(GLOBAL_METRICS_PROVIDER_BASE_URL, json=mp)
    return resp, name


def _validate_for_create_gmp(
    mp_type_str, metrics, url, comparison_column, value_column, table
):
    """Validate the provided parameters as input parameters for the
    create_globalmetricsprovider() method.

    Args:
        mp_type_str (str): the value provided with the --type argument
        name (str): the value provided with the --name argument
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
        mp_type = _GlobalMetricsProviderType(mp_type_str)
    except ValueError:
        raise SystemExit(f"Invalid global metrics provider type: '{mp_type_str}'")

    required_parameters = {
        _GlobalMetricsProviderType.PROMETHEUS: {
            "url": url,
        },
        _GlobalMetricsProviderType.STATIC: {
            "metric": metrics,
        },
        _GlobalMetricsProviderType.KAFKA: {
            "url": url,
            "comparison-column": comparison_column,
            "value-column": value_column,
            "table": table,
        },
    }
    err_msg_fmt = (
        "Global metrics provider type '{mp_type}' " "requires --{attr} to be specified"
    )
    for var_name, var in required_parameters[mp_type].items():
        if not var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))


@globalmetricsprovider.command("get", help="Get a global metrics provider")
@argument("name", help="Global metrics provider name")
@arg_formatting
@depends("session")
@printer(table=GlobalMetricsProviderTable())
def get_globalmetricsprovider(session, name):
    resp = session.get(
        f"{GLOBAL_METRICS_PROVIDER_BASE_URL}/{name}", raise_for_status=False
    )
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: GlobalMetricsProvider {name!r} not found")
    resp.raise_for_status()
    return resp.json()


def _validate_for_update_gmp(
    mp_type_str, metrics, url, comparison_column, value_column, table
):
    """Validate the provided parameters as input parameters for the
    update_globalmetricsprovider() method.

    Args:
        mp_type_str (str): the value provided with the --type argument
        name (str): the value provided with the --name argument
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
        mp_type = _GlobalMetricsProviderType(mp_type_str)
    except ValueError:
        raise SystemExit(f"Invalid global metrics provider type: '{mp_type_str}'")

    required_parameters = {
        _GlobalMetricsProviderType.PROMETHEUS: {
            "url": url,
        },
        _GlobalMetricsProviderType.STATIC: {
            "metric": metrics,
        },
        _GlobalMetricsProviderType.KAFKA: {},
    }
    err_msg_fmt = (
        "Global metrics provider type '{mp_type}' requires --{attr} to be specified"
    )
    for var_name, var in required_parameters[mp_type].items():
        if not var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))

    disallowed_parameters = {
        _GlobalMetricsProviderType.PROMETHEUS: {
            "metric": metrics,
            "comparison-column": comparison_column,
            "value-column": value_column,
            "table": table,
        },
        _GlobalMetricsProviderType.STATIC: {
            "url": url,
            "comparison-column": comparison_column,
            "value-column": value_column,
            "table": table,
        },
        _GlobalMetricsProviderType.KAFKA: {
            "metric": metrics,
        },
    }
    err_msg_fmt = (
        "--{attr} is not a valid argument for "
        "global metrics providers of type {mp_type}"
    )
    for var_name, var in disallowed_parameters[mp_type].items():
        if var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))


@globalmetricsprovider.command("update", help="Update global metrics provider")
@argument("name", help="Global metrics provider name")
@argument(
    "--url",
    dest="mp_url",
    help=f"Global metrics provider url. "
    f"Not valid for global metrics providers of type "
    f"{_GlobalMetricsProviderType.STATIC}",
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
        f"{_GlobalMetricsProviderType.STATIC}."
    ),
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid for global metrics providers of type "
    f"{_GlobalMetricsProviderType.KAFKA.value}.",
)
@argument(
    "--comparison-column",
    help=f"Name of the column whose value will be compared to the metric name "
    f"when selecting a metric. Only valid for global metrics providers of type "
    f"{_GlobalMetricsProviderType.KAFKA.value}.",
)
@argument(
    "--value-column",
    help=f"Name of the column where the value of a metric is stored. "
    f"Only valid for global metrics providers of type "
    f"{_GlobalMetricsProviderType.KAFKA.value}.",
)
@arg_formatting
@depends("session")
@printer(table=GlobalMetricsProviderTable())
def update_globalmetricsprovider(
    session,
    name,
    mp_url,
    metrics,
    comparison_column,
    value_column,
    table,
):
    url = f"{GLOBAL_METRICS_PROVIDER_BASE_URL}/{name}"
    resp = session.get(url, raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: GlobalMetricsProvider {name!r} not found")
    resp.raise_for_status()
    mp = resp.json()
    mp_type = mp["spec"]["type"]

    _validate_for_update_gmp(
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

    resp = session.put(url, json=mp, raise_for_status=False)
    if resp.status_code != 200:
        raise SystemExit(
            f"HttpError {resp.status_code}: {resp.content.decode('utf-8')}"
        )
    resp.raise_for_status()
    return resp.json()


@globalmetricsprovider.command("delete", help="Delete global metrics provider")
@argument("name", help="Global metrics provider name")
@arg_formatting
@depends("session")
@printer(table=GlobalMetricsProviderTable())
def delete_globalmetricsprovider(session, name):
    resp = session.delete(
        f"{GLOBAL_METRICS_PROVIDER_BASE_URL}/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: GlobalMetricsProvider {name!r} not found")
    resp.raise_for_status()

    if resp.status_code == 204:
        return None
    return resp.json()


# ################ Managing global metrics


global_metric = core.subparser(
    "globalmetric", aliases=["gm"], help="Manage global metrics"
)


class GlobalMetricListTable(BaseTable):
    provider = Cell("spec.provider.name")
    min = Cell("spec.min")
    max = Cell("spec.max")


class GlobalMetricTable(GlobalMetricListTable):
    pass


@global_metric.command("list", help="List global metrics")
@arg_formatting
@depends("session")
@printer(table=GlobalMetricListTable(many=True))
def list_globalmetrics(session):
    resp = session.get(GLOBAL_METRIC_BASE_URL)
    body = resp.json()
    return body["items"]


@global_metric.command("create", help="Create a global metric")
@argument("--name", required=True, help="Global metric name")
@argument("--gmp-name", required=True, help="Global metrics provider name")
@argument("--min", required=True, help="Minimum value of the global metric")
@argument("--max", required=True, help="Maximum value of the global metric")
@argument(
    "--metric-name",
    help="Name of the global metric which the global metrics provider provides. "
    "As default the name of the created global metric resource is used.",
)
@arg_formatting
@depends("session")
@printer(table=GlobalMetricTable())
@rok_response_handler
def create_globalmetric(session, name, gmp_name, min, max, metric_name=None):
    """Create a GlobalMetric resource.

    Args:
        session (requests.Session): the session used to connect to the krake API
        name (str): Name of the global metric
        mp_name (str): Name of the global metrics provider
        min (str): The minimum value of the global metric
        max (str): The maximum value of the global metric
        metric_name (str): The name used to identify the global metric at the endpoint
            of the global metrics provider

    Returns:
        dict(str, object): The created GlobalMetric resource in json representation
    """
    if not metric_name:
        metric_name = name
    metric = {
        "api": "core",
        "kind": "GlobalMetric",
        "metadata": {
            "name": name,
        },
        "spec": {
            "max": max,
            "min": min,
            "provider": {
                "metric": metric_name,
                "name": gmp_name,
            },
        },
    }

    resp = session.post(GLOBAL_METRIC_BASE_URL, json=metric)
    return resp, name


@global_metric.command("get", help="Get a global metric")
@argument("name", help="Global metric name")
@arg_formatting
@depends("session")
@printer(table=GlobalMetricTable())
def get_globalmetric(session, name):
    resp = session.get(f"{GLOBAL_METRIC_BASE_URL}/{name}", raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: GlobalMetric {name!r} not found")
    resp.raise_for_status()
    return resp.json()


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
@printer(table=GlobalMetricTable())
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
    if not (max or min or gmp_name or metric_name):
        raise SystemExit(
            "Either --mp-name, --metric-name, --min or --max must be specified."
        )

    url = f"{GLOBAL_METRIC_BASE_URL}/{name}"
    resp = session.get(url, raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: GlobalMetric {name!r} not found")
    resp.raise_for_status()
    metric = resp.json()
    if max:
        metric["spec"]["max"] = max
    if min:
        metric["spec"]["min"] = min
    if gmp_name:
        metric["spec"]["provider"]["name"] = gmp_name
    if metric_name:
        metric["spec"]["provider"]["metric"] = metric_name

    resp = session.put(url, json=metric, raise_for_status=False)
    if resp.status_code != 200:
        raise SystemExit(
            f"HttpError {resp.status_code}: {resp.content.decode('utf-8')}"
        )
    resp.raise_for_status()
    return resp.json()


@global_metric.command("delete", help="Delete global metric")
@argument("name", help="Global metric name")
@arg_formatting
@depends("session")
@printer(table=GlobalMetricTable())
def delete_globalmetric(session, name):
    resp = session.delete(f"{GLOBAL_METRIC_BASE_URL}/{name}", raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: GlobalMetric {name!r} not found")
    resp.raise_for_status()

    if resp.status_code == 204:
        return None
    return resp.json()
