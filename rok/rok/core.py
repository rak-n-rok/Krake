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
from .fixtures import depends
from .formatters import (
    BaseTable,
    Cell,
    printer,
    dict_formatter,
)

MP_BASE_URL = "/core/metricsprovider"
METRIC_BASE_URL = "/core/metric"


class _MetricsProviderType(Enum):
    PROMETHEUS = "prometheus"
    STATIC = "static"
    KAFKA = "kafka"


core = ParserSpec("core", aliases=[], help="Manage core resources")


# ################ Managing metrics providers


metricsprovider = core.subparser(
    "metricsprovider", aliases=["mp"], help="Manage metrics providers"
)


class MetricsProviderListTable(BaseTable):
    mp_type = Cell("spec.type", name="type")


class MetricsProviderTable(MetricsProviderListTable):
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
            ] = f"ERROR: invalid metrics provider type: '{mp_type_str}'"

        super().draw(table, data, file)


@metricsprovider.command("list", help="List metrics providers")
@arg_formatting
@depends("session")
@printer(table=MetricsProviderListTable(many=True))
def list_metricsproviders(session):
    url = MP_BASE_URL
    resp = session.get(url)
    body = resp.json()
    return body["items"]


@metricsprovider.command("create", help="Create a metrics provider")
@argument("--name", required=True, help="Metrics provider name")
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
    help=f"Metric name and value. Can be specified multiple times. "
    f"Only valid together with --type {_MetricsProviderType.STATIC}.",
)
@argument(
    "--table",
    help=f"Name of the KSQL table. Only valid together with --type "
    f"{_MetricsProviderType.KAFKA.value}.",
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
@printer(table=MetricsProviderTable())
def create_metricsprovider(
    session, name, url, mp_type, metrics, comparison_column, value_column, table
):
    _validate_for_create_mp(
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
        "kind": "MetricsProvider",
        "metadata": {
            "name": name,
        },
        "spec": {
            "type": mp_type.value,
            mp_type.value: type_dict,
        },
    }

    resp = session.post(MP_BASE_URL, json=mp)
    return resp.json()


def _validate_for_create_mp(
    mp_type_str, metrics, url, comparison_column, value_column, table
):
    """Validate the provided parameters as input parameters for the
    create_metricsprovider() method.

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
    err_msg_fmt = "Metrics provider type '{mp_type}' requires --{attr} to be specified"
    for var_name, var in required_parameters[mp_type].items():
        if not var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))


@metricsprovider.command("get", help="Get a metrics provider")
@argument("name", help="Metrics provider name")
@arg_formatting
@depends("session")
@printer(table=MetricsProviderTable())
def get_metricsprovider(session, name):
    resp = session.get(f"{MP_BASE_URL}/{name}", raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Metrics provider {name!r} not found")
    resp.raise_for_status()
    return resp.json()


def _validate_for_update_mp(
    mp_type_str, metrics, url, comparison_column, value_column, table
):
    """Validate the provided parameters as input parameters for the
    update_metricsprovider() method.

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
        "--{attr} is not a valid argument for metrics providers of type {mp_type}"
    )
    for var_name, var in disallowed_parameters[mp_type].items():
        if var:
            raise SystemExit(err_msg_fmt.format(mp_type=mp_type_str, attr=var_name))


@metricsprovider.command("update", help="Update metrics provider")
@argument("name", help="Metrics provider name")
@argument(
    "--url",
    dest="mp_url",
    help=f"Metrics provider url. "
    f"Not valid for metrics providers of type {_MetricsProviderType.STATIC}",
)
@argument(
    "--metric",
    "-m",
    dest="metrics",
    action=MetricAction,
    help=(
        f"Metric name and value. Can be specified multiple times. "
        f"Only valid for metrics providers of type {_MetricsProviderType.STATIC}."
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
@arg_formatting
@depends("session")
@printer(table=MetricsProviderTable())
def update_metricsprovider(
    session,
    name,
    mp_url,
    metrics,
    comparison_column,
    value_column,
    table,
):
    url = f"{MP_BASE_URL}/{name}"
    resp = session.get(url, raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: Metrics provider {name!r} not found")
    resp.raise_for_status()
    mp = resp.json()
    mp_type = mp["spec"]["type"]

    _validate_for_update_mp(
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


@metricsprovider.command("delete", help="Delete metrics provider")
@argument("name", help="Metrics provider name")
@arg_formatting
@depends("session")
@printer(table=MetricsProviderTable())
def delete_metricsprovider(session, name):
    resp = session.delete(
        f"{MP_BASE_URL}/{name}",
        raise_for_status=False,
    )
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Metrics provider {name!r} not found")
    resp.raise_for_status()

    if resp.status_code == 204:
        return None
    return resp.json()


# ################ Managing metrics


metric = core.subparser("metric", help="Manage metrics")


class MetricListTable(BaseTable):
    provider = Cell("spec.provider.name")
    min = Cell("spec.min")
    max = Cell("spec.max")


class MetricTable(MetricListTable):
    pass


@metric.command("list", help="List metrics")
@arg_formatting
@depends("session")
@printer(table=MetricListTable(many=True))
def list_metrics(session):
    resp = session.get(METRIC_BASE_URL)
    body = resp.json()
    return body["items"]


@metric.command("create", help="Create a metric")
@argument("--name", required=True, help="Metric name")
@argument("--mp-name", required=True, help="Metrics provider name")
@argument("--min", required=True, help="Metric minimum value")
@argument("--max", required=True, help="Metric maximum value")
@argument(
    "--metric-name",
    help="Name of the metric which the metrics provider provides. "
    "As default the name of the created metric resource is used.",
)
@arg_formatting
@depends("session")
@printer(table=MetricTable())
def create_metric(session, name, mp_name, min, max, metric_name=None):
    """Create a Metric resource.

    Args:
        session (requests.Session): the session used to connect to the krake API
        name (str): Name of the metric
        mp_name (str): Name of the metrics provider
        min (str): The minimum value of the metric
        max (str): The maximum value of the metric
        metric_name (str): The name used to identify the metric at the endpoint
            of the metrics provider

    Returns:
        dict(str, object): The created Metric resource in json representation
    """
    if not metric_name:
        metric_name = name
    metric = {
        "api": "core",
        "kind": "Metric",
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

    resp = session.post(METRIC_BASE_URL, json=metric)
    return resp.json()


@metric.command("get", help="Get a metric")
@argument("name", help="Metric name")
@arg_formatting
@depends("session")
@printer(table=MetricTable())
def get_metric(session, name):
    resp = session.get(f"{METRIC_BASE_URL}/{name}", raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Metric {name!r} not found")
    resp.raise_for_status()
    return resp.json()


@metric.command("update", help="Update metric")
@argument("name", help="Metric name")
@argument("--max", help="Metric maximum value'")
@argument("--min", help="Metric minimum value'")
@argument("--mp-name", help="Metrics provider name'")
@argument(
    "--metric-name",
    help="Name of the metric which the metrics provider provides. ",
)
@arg_formatting
@depends("session")
@printer(table=MetricTable())
def update_metric(session, name, max, min, mp_name, metric_name):
    """Update a Metric resource.

    Args:
        session (requests.Session): the session used to connect to the krake API
        name (str): Name of the metric
        max (str): The maximum value of the metric
        min (str): The minimum value of the metric
        mp_name (str): Name of the metrics provider
        metric_name (str): The name used to identify the metric at the endpoint
            of the metrics provider

    Returns:
        dict(str, object): The updated Metric resource in json representation
    """
    if not (max or min or mp_name or metric_name):
        raise SystemExit(
            "Either --mp-name, --metric-name, --min or --max must be specified."
        )

    url = f"{METRIC_BASE_URL}/{name}"
    resp = session.get(url, raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"HttpError 404: Metric {name!r} not found")
    resp.raise_for_status()
    metric = resp.json()
    if max:
        metric["spec"]["max"] = max
    if min:
        metric["spec"]["min"] = min
    if mp_name:
        metric["spec"]["provider"]["name"] = mp_name
    if metric_name:
        metric["spec"]["provider"]["metric"] = metric_name

    resp = session.put(url, json=metric, raise_for_status=False)
    if resp.status_code != 200:
        raise SystemExit(
            f"HttpError {resp.status_code}: {resp.content.decode('utf-8')}"
        )
    resp.raise_for_status()
    return resp.json()


@metric.command("delete", help="Delete metric")
@argument("name", help="Metric name")
@arg_formatting
@depends("session")
@printer(table=MetricTable())
def delete_metric(session, name):
    resp = session.delete(f"{METRIC_BASE_URL}/{name}", raise_for_status=False)
    if resp.status_code == 404:
        raise SystemExit(f"Error 404: Metric {name!r} not found")
    resp.raise_for_status()

    if resp.status_code == 204:
        return None
    return resp.json()
