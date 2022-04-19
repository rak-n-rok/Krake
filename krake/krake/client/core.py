from krake.client import Watcher, ApiClient
from krake.data.core import (
    Role,
    RoleList,
    RoleBinding,
    RoleBindingList,
    GlobalMetric,
    GlobalMetricList,
    GlobalMetricsProvider,
    GlobalMetricsProviderList,
    Metric,
    MetricsProvider,
    MetricsProviderList,
    MetricList,
)


class CoreApi(ApiClient):
    """Core API client

    Example:
        .. code:: python

            from krake.client import Client

            with Client(url="http://localhost:8080") as client:
                core_api = CoreApi(client)

    Args:
        client (krake.client.Client): API client for accessing the Krake HTTP API

    """

    plurals = {
        "Role": "Roles",
        "RoleBinding": "RoleBindings",
        "GlobalMetric": "GlobalMetrics",
        "GlobalMetricsProvider": "GlobalMetricsProviders",
        "Metric": "Metrics",
        "MetricsProvider": "MetricsProviders"
    }

    async def create_global_metric(self, body):
        """Create the specified GlobalMetric.

        Args:
            body (GlobalMetric): Body of the HTTP request.

        Returns:
            GlobalMetric: Body of the HTTP response.

        """
        path = "/core/globalmetrics".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return GlobalMetric.deserialize(data)

    async def delete_global_metric(self, name):
        """Delete the specified GlobalMetric.

        Args:
            name (str): name of the GlobalMetric.

        Returns:
            GlobalMetric: Body of the HTTP response.

        """
        path = "/core/globalmetrics/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return GlobalMetric.deserialize(data)

    async def list_global_metrics(self):
        """List the GlobalMetrics in the namespace.

        Returns:
            GlobalMetricList: Body of the HTTP response.

        """
        path = "/core/globalmetrics".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalMetricList.deserialize(data)

    def watch_global_metrics(self, heartbeat=None):
        """Generate a watcher for the GlobalMetrics in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            GlobalMetricList: Body of the HTTP response.

        """
        path = "/core/globalmetrics".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, GlobalMetric)

    async def read_global_metric(self, name):
        """Read the specified GlobalMetric.

        Args:
            name (str): name of the GlobalMetric.

        Returns:
            GlobalMetric: Body of the HTTP response.

        """
        path = "/core/globalmetrics/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalMetric.deserialize(data)

    async def update_global_metric(self, body, name):
        """Update the specified GlobalMetric.

        Args:
            body (GlobalMetric): Body of the HTTP request.
            name (str): name of the GlobalMetric.

        Returns:
            GlobalMetric: Body of the HTTP response.

        """
        path = "/core/globalmetrics/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return GlobalMetric.deserialize(data)

    async def create_global_metrics_provider(self, body):
        """Create the specified GlobalMetricsProvider.

        Args:
            body (GlobalMetricsProvider): Body of the HTTP request.

        Returns:
            GlobalMetricsProvider: Body of the HTTP response.

        """
        path = "/core/globalmetricsproviders".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return GlobalMetricsProvider.deserialize(data)

    async def delete_global_metrics_provider(self, name):
        """Delete the specified GlobalMetricsProvider.

        Args:
            name (str): name of the GlobalMetricsProvider.

        Returns:
            GlobalMetricsProvider: Body of the HTTP response.

        """
        path = "/core/globalmetricsproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return GlobalMetricsProvider.deserialize(data)

    async def list_global_metrics_providers(self):
        """List the GlobalMetricsProviders in the namespace.

        Returns:
            GlobalMetricsProviderList: Body of the HTTP response.

        """
        path = "/core/globalmetricsproviders".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalMetricsProviderList.deserialize(data)

    def watch_global_metrics_providers(self, heartbeat=None):
        """Generate a watcher for the GlobalMetricsProviders in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds
        Returns:
            GlobalMetricsProviderList: Body of the HTTP response.

        """
        path = "/core/globalmetricsproviders".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, GlobalMetricsProvider)

    async def read_global_metrics_provider(self, name):
        """Reads the specified GlobalMetricsProvider.

        Args:
            name (str): name of the GlobalMetricsProvider.

        Returns:
            GlobalMetricsProvider: Body of the HTTP response.

        """
        path = "/core/globalmetricsproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalMetricsProvider.deserialize(data)

    async def update_global_metrics_provider(self, body, name):
        """Update the specified GlobalMetricsProvider.

        Args:
            body (GlobalMetricsProvider): Body of the HTTP request.
            name (str): name of the GlobalMetricsProvider.

        Returns:
            GlobalMetricsProvider: Body of the HTTP response.

        """
        path = "/core/globalmetricsproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return GlobalMetricsProvider.deserialize(data)

    async def create_metric(self, body, namespace):
        """Create the specified Metric.

        Args:
            body (Metric): Body of the HTTP request.
            namespace (str): namespace of the Metric

        Returns:
            Metric: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metrics".format(namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return Metric.deserialize(data)

    async def delete_metric(self, name, namespace):
        """Delete the specified Metric.

        Args:
            name (str): name of the Metric.
            namespace (str): namespace of the Metric

        Returns:
            Metric: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metrics/{name}"\
            .format(name=name, namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return Metric.deserialize(data)

    async def list_metrics(self, namespace=None):
        """List the Metrics in the namespace.

        Args:
            namespace (str): namespace of the Metric

        Returns:
            MetricList: Body of the HTTP response.

        """
        if namespace:
            path = "/core/namespaces/{namespace}/metrics".format(namespace=namespace)
        else:
            path = "/core/metrics".format()

        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MetricList.deserialize(data)

    def watch_metrics(self, namespace=None, heartbeat=None):
        """Generate a watcher for the Metrics in the namespace.

        Args:
            namespace (str): namespace of the Metric
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            MetricList: Body of the HTTP response.

        """
        if namespace:
            path = "/core/namespaces/{namespace}/metrics".format(namespace=namespace)
        else:
            path = "/core/metrics".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Metric)

    async def read_metric(self, name, namespace):
        """Read the specified Metric.

        Args:
            name (str): name of the Metric.
            namespace (str): namespace of the Metric

        Returns:
            Metric: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metrics/{name}"\
            .format(name=name, namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return Metric.deserialize(data)

    async def update_metric(self, body, name, namespace):
        """Update the specified GlobalMetric.

        Args:
            body (GlobalMetric): Body of the HTTP request.
            name (str): name of the Metric.
            namespace (str): namespace of the Metric

        Returns:
            GlobalMetric: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metrics/{name}"\
            .format(name=name, namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Metric.deserialize(data)

    async def create_metrics_provider(self, body, namespace):
        """Create the specified MetricsProvider.

        Args:
            body (MetricsProvider): Body of the HTTP request.
            namespace (str): Namespace of the MetricsProvider.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metricsproviders"\
            .format(namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return MetricsProvider.deserialize(data)

    async def delete_metrics_provider(self, name, namespace):
        """Delete the specified MetricsProvider.

        Args:
            name (str): name of the MetricsProvider.
            namespace (str): namespace of the MetricsProvider.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metricsproviders/{name}"\
            .format(name=name, namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return MetricsProvider.deserialize(data)

    async def list_metrics_providers(self, namespace=None):
        """List the MetricsProviders in the namespace.

        Args:
            namespace (str): namespace of the MetricsProvider.

        Returns:
            MetricsProviderList: Body of the HTTP response.

        """
        if namespace:
            path = "/core/namespaces/{namespace}/metricsproviders"\
                .format(namespace=namespace)
        else:
            path = "/core/metricsproviders".format()

        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MetricsProviderList.deserialize(data)

    def watch_metrics_providers(self, namespace=None, heartbeat=None):
        """Generate a watcher for the MetricsProviders in the namespace.

        Args:
            namespace (str): namespace of the MetricsProvider.
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds
        Returns:
            MetricsProviderList: Body of the HTTP response.

        """
        if namespace:
            path = "/core/namespaces/{namespace}/metricsproviders"\
                .format(namespace=namespace)
        else:
            path = "/core/metricsproviders".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, MetricsProvider)

    async def read_metrics_provider(self, name, namespace):
        """Read the specified MetricsProvider.

        Args:
            name (str): name of the MetricsProvider.
            namespace (str): namespace of the MetricsProvider.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metricsproviders/{name}"\
            .format(name=name, namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MetricsProvider.deserialize(data)

    async def update_metrics_provider(self, body, name, namespace):
        """Update the specified MetricsProvider.

        Args:
            body (MetricsProvider): Body of the HTTP request.
            name (str): name of the MetricsProvider.
            namespace (str): namespace of the MetricsProvider.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/namespaces/{namespace}/metricsproviders/{name}"\
            .format(name=name, namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return MetricsProvider.deserialize(data)

    async def create_role(self, body):
        """Create the specified Role.

        Args:
            body (Role): Body of the HTTP request.

        Returns:
            Role: Body of the HTTP response.

        """
        path = "/core/roles".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return Role.deserialize(data)

    async def delete_role(self, name):
        """Delete the specified Role.

        Args:
            name (str): name of the Role.

        Returns:
            Role: Body of the HTTP response.

        """
        path = "/core/roles/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return Role.deserialize(data)

    async def list_roles(self):
        """List the Roles in the namespace.

        Returns:
            RoleList: Body of the HTTP response.

        """
        path = "/core/roles".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return RoleList.deserialize(data)

    def watch_roles(self, heartbeat=None):
        """Generate a watcher for the Roles in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            RoleList: Body of the HTTP response.

        """
        path = "/core/roles".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Role)

    async def read_role(self, name):
        """Read the specified Role.

        Args:
            name (str): name of the Role.

        Returns:
            Role: Body of the HTTP response.

        """
        path = "/core/roles/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return Role.deserialize(data)

    async def update_role(self, body, name):
        """Update the specified Role.

        Args:
            body (Role): Body of the HTTP request.
            name (str): name of the Role.

        Returns:
            Role: Body of the HTTP response.

        """
        path = "/core/roles/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Role.deserialize(data)

    async def create_role_binding(self, body):
        """Create the specified RoleBinding.

        Args:
            body (RoleBinding): Body of the HTTP request.

        Returns:
            RoleBinding: Body of the HTTP response.

        """
        path = "/core/rolebindings".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return RoleBinding.deserialize(data)

    async def delete_role_binding(self, name):
        """Delete the specified RoleBinding.

        Args:
            name (str): name of the RoleBinding.

        Returns:
            RoleBinding: Body of the HTTP response.

        """
        path = "/core/rolebindings/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return RoleBinding.deserialize(data)

    async def list_role_bindings(self):
        """List the RoleBindings in the namespace.

        Returns:
            RoleBindingList: Body of the HTTP response.

        """
        path = "/core/rolebindings".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return RoleBindingList.deserialize(data)

    def watch_role_bindings(self, heartbeat=None):
        """Generate a watcher for the RoleBindings in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            RoleBindingList: Body of the HTTP response.

        """
        path = "/core/rolebindings".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, RoleBinding)

    async def read_role_binding(self, name):
        """Read the specified RoleBinding.

        Args:
            name (str): name of the RoleBinding.

        Returns:
            RoleBinding: Body of the HTTP response.

        """
        path = "/core/rolebindings/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return RoleBinding.deserialize(data)

    async def update_role_binding(self, body, name):
        """Update the specified RoleBinding.

        Args:
            body (RoleBinding): Body of the HTTP request.
            name (str): name of the RoleBinding.

        Returns:
            RoleBinding: Body of the HTTP response.

        """
        path = "/core/rolebindings/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return RoleBinding.deserialize(data)
