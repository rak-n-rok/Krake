"""Some utilities for testing Krake components"""
import asyncio
import re
import json

from itertools import cycle, count
from functools import wraps
from time import time
from aiohttp import web

from krake.controller.kubernetes.application.application import listen
from kubernetes_asyncio.client import ApiClient


def with_timeout(timeout):
    """Decorator function for coroutines

    Example:
        .. code:: python

            from krake.test_utils import with_timeout

            @with_timeout(3)
            async def test_my_coroutine():
                await infinite_coroutine()

    Args:
        timeout (int, float): Timeout interval in seconds

    Returns:
        callable: Decorator that can be used for decorating coroutines.

    """

    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)

        return wrapper

    return decorator


def server_endpoint(server):
    """Return the HTTP endpoint for the given test server.

    Args:
        server (aiohttp.test_utils.TestServer): aiohttp test server instance

    Returns:
        str: HTTP endpoint of the server

    """
    return f"{server.scheme}://{server.host}:{server.port}"


def make_prometheus(metrics):
    """Create an :class:`aiohttp.web.Application` instance mocking the HTTP
    API of Prometheus. The metric names and corresponding values are given as a
    simple dictionary.

    The values are iterables that are advanced for every HTTP call made to the
    server. If the end of an iterable is reached, the API server will respond
    with an empty response for further requests.

    Examples:
        .. code:: python

            async test_my_func(aiohttp_server):
                prometheus = await aiohttp_server(make_prometheus({
                    "my_metric": ["0.42"]
                }))

        If you want to return the same value for every HTTP request, use
        :func:`itertools.cycle`:

        .. code:: python

            from itertools import cycle

            prometheus = await aiohttp_server(make_prometheus({
                "my_metric": cycle(["0.42"])
            }))

    An additional HTTP endpoint ``/-/update`` is created that can be used to
    update the metrics. The request body must be JSON-encoded with the
    following structure:

    .. code:: python

        {
            # Mapping of metric names to list of values
            "metrics": {
                "my_metric": ["100", "500"]
            },
            "cycle": false   # Optional: if true, metrics are repeated
        }

    Args:
        metrics (Dict[str, Iterable]): Mapping of metric names an iterable of
            the corresponding value.

    Returns:

        aiohttp.web.Application: aiohttp application that can be run with the
        `aiohttp_server` fixture.

    """
    routes = web.RouteTableDef()

    @routes.get("/api/v1/query")
    async def _(request):
        name = request.query.get("query")
        if name not in request.app["series"]:
            result = []
        else:
            try:
                value = next(request.app["series"][name])
            except StopIteration:
                del request.app["series"][name]
                result = []
            else:
                result = [
                    {
                        "metric": {
                            "__name__": name,
                            "instance": "unittest",
                            "job": "unittest",
                        },
                        "value": [time(), str(value)],
                    }
                ]

        return web.json_response(
            {"status": "success", "data": {"resultType": "vector", "result": result}}
        )

    @routes.post("/-/update")
    async def _(request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("'metrics' must be a dictionary")
            metrics = body["metrics"]
            if not isinstance(metrics, dict):
                raise ValueError("Metrics must be a dictionary")
            for value in metrics.values():
                if not isinstance(value, list):
                    raise ValueError("Metric values must be a list")
        except (KeyError, ValueError) as err:
            raise web.HTTPBadRequest() from err

        if body.get("cycle", False):
            series = {name: iter(cycle(value)) for name, value in metrics.items()}
        else:
            series = {name: iter(value) for name, value in metrics.items()}

        request.app["series"] = series

        return web.Response(status=200)

    app = web.Application()
    app.add_routes(routes)
    app["series"] = {name: iter(value) for name, value in metrics.items()}

    return app


def parse_ksql_query(query):
    """Read the parameters of the provided KSQL query.

    Args:
        query (str): the query given as string.

    Returns:
        (str, str, str, str): a tuple that contains: the name of the table, the name of
            the column that holds the metrics value, the name of the column that is used
            for comparison with the metric name, and the name to compare to.

    """
    query_pattern = "SELECT (\\w+) FROM (\\w+) WHERE (\\w+) *= *'(.+)';"
    match_group = re.match(query_pattern, query, re.IGNORECASE)

    assert match_group is not None, f"The query {query!r} has an invalid format."
    value_column, table, comparison_column, metric_name = match_group.groups()

    message = (
        "The column for the metric names and the one for the metrics values"
        " cannot be the same."
    )
    assert value_column != comparison_column, message

    return table, value_column, comparison_column, metric_name


def make_kafka(table, columns, rows):
    """Create a KSQL mock instance, with a single table. The name of the columns of the
    table as well as its name are provided as parameters. Then, the provided rows are
    inserted into the table. For each element of a row, several values can be specified
    in a list. Each query for the value will fetch the next element in this list.

    Example:
        To create the following mock "my_metrics" table:

        metric_names | value
        -------------+-------------------
           met_1     | 0.5
           met_2     | 10 (then value 55)
           met_3     | 1 (then value 2)

        The following code can be used:

        .. code:: python

            columns = ["metric_names", "value"]
            rows = [
                ["met_1", [0.5]],
                ["met_2", [10, 55]],
                ["met_3", [1, 2]],
            ]
            kafka = await aiohttp_server(make_kafka("my_metrics", columns, rows))

        To get the values of the metric, a query must be sent like the following:

        .. code:: python

            # To fetch the value of the first metric:
            query = "SELECT value FROM my_metrics where metric_name = 'met_1';"
            request = {"ksql": query, "streamsProperties": {}}
            resp = await client.post("/query", json=request)
            body = await resp.json()

            expected_resp = [
              {
                "header": {
                  "queryId": "query_<counter>",
                  "schema": "`VALUE` STRING"
                }
              },
              {
                "row": {
                  "columns": [0.5]  # <-- the expected value.
                }
              }
            ]
            assert body == expected_resp

            # To fetch the value of the second metric, the value returned will be `10`:
            query = "SELECT value FROM my_metrics where metric_name = 'met_2';"

            # With a second call: of the same query, the returned value will be `55`
            # A third call will only return the "header" part (thus be "empty").

    Args:
        table (str): name to give to the table.
        columns (list[str]): list of the names of the columns to add in the table.
        rows (list[list[str|list[Any]]]): list of the rows to add in the table. Each row
            is then a list of value. Each value can be either a simple element, or a
            list of values.

    Returns:
        web.Application: the aiohttp Application created as KSQL mock database.

    """

    counter = count()

    routes = web.RouteTableDef()

    @routes.post("/query")
    async def _(request):
        data = await request.json()

        assert (
            request.headers["Content-Type"] == "application/json"
        ), "The content type in the query's headers should be JSON."
        assert "ksql" in data, "The 'ksql' parameter is missing from the query's data."

        query = data["ksql"]
        table_name, value_column, comparison_column, metric_name = parse_ksql_query(
            query
        )
        assert table_name == request.app["table_name"]

        header = {
            "header": {
                "queryId": f"query_{next(counter)}",
                "schema": f"`{value_column.upper()}` STRING",
            }
        }

        rows = request.app["rows"]
        columns = request.app["columns"]

        if value_column not in columns:
            result = {
                "@type": "statement_error",
                "error_code": 40001,
                "message": f"SELECT column '{value_column}' " f"cannot be resolved.",
                "statementText": query,
                "entities": [],
            }
            raise web.HTTPBadRequest(reason=json.dumps(result))

        elif comparison_column not in columns:
            result = {
                "@type": "statement_error",
                "error_code": 40001,
                "message": (
                    f"WHERE column '{comparison_column}' " f"cannot be resolved."
                ),
                "statementText": query,
                "entities": [],
            }
            raise web.HTTPBadRequest(reason=json.dumps(result))

        else:
            comp_index = columns.index(comparison_column)
            value_index = columns.index(value_column)

            try:
                for i, row in enumerate(rows):
                    if row[comp_index] == metric_name:
                        stored_value = next(row[value_index])
                        break
                else:
                    raise ValueError()
            except (StopIteration, ValueError):
                # StopIteration is raised when all values for the requested metrics have
                # been returned already (i.e. the corresponding row iterator).
                result = [header]
            else:
                resp_row = {"row": {"columns": [stored_value]}}
                result = [header, resp_row]

        return web.json_response(result)

    app = web.Application()
    app.add_routes(routes)

    # Create a iterator for each element of each row which has been given as list.
    # Otherwise, simply the value will be given directly without iteration.
    iter_rows = [
        [iter(value) if type(value) is list else value for value in row] for row in rows
    ]

    app["rows"] = iter_rows
    app["columns"] = columns
    app["table_name"] = table

    return app


async def aenumerate(iterable):
    i = 0
    async for item in iterable:
        yield i, item
        i += 1


class HandlerDeactivator(object):
    """Context manager used in the tests to temporarly remove a Handler from a Hook.

    Args:
        hook (krake.controller.hooks.HookType): HookType for which the handler should be
            temporarly disabled.
        handler (callable): The handler to deactivate

    """

    def __init__(self, hook, handler):
        self.hook = hook
        self.handler = handler

    def __enter__(self):
        listen.registry[self.hook].remove(self.handler)

    def __exit__(self, *exc):
        listen.registry[self.hook].append(self.handler)


def get_first_container(deployment):
    return deployment["spec"]["template"]["spec"]["containers"][0]


async def serialize_k8s_object(manifest, object_type):
    """Create a Kubernetes object from a dictionary.

    This is useful to test functions which only accept Kubernetes objects.

    This is a temporary implementation, as a proper deserialization function hasn't yet
    been implemented in the kubernetes_client package. See
    https://github.com/kubernetes-client/python/pull/989

    This solution is inspired by
    https://github.com/kubernetes-client/python/issues/977#issuecomment-592030030
    """

    api_client = ApiClient()

    class FakeKubeResponse:
        def __init__(self, obj):
            self.data = json.dumps(obj)

    fake_kube_response = FakeKubeResponse(manifest)
    return api_client.deserialize(fake_kube_response, object_type)
