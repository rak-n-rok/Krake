from krake.client import Watcher, ApiClient
from krake.data.core import (
    RoleList,
    RoleBindingList,
    MetricsProvider,
    MetricsProviderList,
    Metric,
    Role,
    MetricList,
    RoleBinding,
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
        "Metric": "Metrics",
        "MetricsProvider": "MetricsProviders",
        "Role": "Roles",
        "RoleBinding": "RoleBindings",
    }

    async def create_metric(self, body):
        """Create the specified Metric.

        Args:
            body (Metric): Body of the HTTP request.

        Returns:
            Metric: Body of the HTTP response.

        """
        path = "/core/metrics".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return Metric.deserialize(data)

    async def delete_metric(self, name):
        """Delete the specified Metric.

        Args:
            name (str): name of the Metric.

        Returns:
            Metric: Body of the HTTP response.

        """
        path = "/core/metrics/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return Metric.deserialize(data)

    async def list_metrics(self):
        """List the Metrics in the namespace.

        Returns:
            MetricList: Body of the HTTP response.

        """
        path = "/core/metrics".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MetricList.deserialize(data)

    def watch_metrics(self, heartbeat=None):
        """Generate a watcher for the Metrics in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form a an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            MetricList: Body of the HTTP response.

        """
        path = "/core/metrics".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Metric)

    async def read_metric(self, name):
        """Read the specified Metric.

        Args:
            name (str): name of the Metric.

        Returns:
            Metric: Body of the HTTP response.

        """
        path = "/core/metrics/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return Metric.deserialize(data)

    async def update_metric(self, body, name):
        """Update the specified Metric.

        Args:
            body (Metric): Body of the HTTP request.
            name (str): name of the Metric.

        Returns:
            Metric: Body of the HTTP response.

        """
        path = "/core/metrics/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Metric.deserialize(data)

    async def create_metrics_provider(self, body):
        """Create the specified MetricsProvider.

        Args:
            body (MetricsProvider): Body of the HTTP request.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/metricsproviders".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return MetricsProvider.deserialize(data)

    async def delete_metrics_provider(self, name):
        """Delete the specified MetricsProvider.

        Args:
            name (str): name of the MetricsProvider.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/metricsproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return MetricsProvider.deserialize(data)

    async def list_metrics_providers(self):
        """List the MetricsProviders in the namespace.

        Returns:
            MetricsProviderList: Body of the HTTP response.

        """
        path = "/core/metricsproviders".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MetricsProviderList.deserialize(data)

    def watch_metrics_providers(self, heartbeat=None):
        """Generate a watcher for the MetricsProviders in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form a an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds
        Returns:
            MetricsProviderList: Body of the HTTP response.

        """
        path = "/core/metricsproviders".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, MetricsProvider)

    async def read_metrics_provider(self, name):
        """Read the specified MetricsProvider.

        Args:
            name (str): name of the MetricsProvider.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/metricsproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MetricsProvider.deserialize(data)

    async def update_metrics_provider(self, body, name):
        """Update the specified MetricsProvider.

        Args:
            body (MetricsProvider): Body of the HTTP request.
            name (str): name of the MetricsProvider.

        Returns:
            MetricsProvider: Body of the HTTP response.

        """
        path = "/core/metricsproviders/{name}".format(name=name)
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
                in form a an empty newline. Passing 0 disables the heartbeat. Default:
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
                in form a an empty newline. Passing 0 disables the heartbeat. Default:
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
