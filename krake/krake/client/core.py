from krake.client import Watcher, ApiClient
from krake.data.core import (
    RoleList,
    RoleBindingList,
    GlobalMetricsProvider,
    GlobalMetricsProviderList,
    GlobalMetric,
    Role,
    GlobalMetricList,
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
                in form a an empty newline. Passing 0 disables the heartbeat. Default:
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
                in form a an empty newline. Passing 0 disables the heartbeat. Default:
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
        """Read the specified GlobalMetricsProvider.

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
