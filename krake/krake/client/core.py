from krake.client import Watcher, ApiClient
from krake.data.core import (
    Role,
    GlobalMetric,
    RoleList,
    RoleBindingList,
    GlobalMetricList,
    RoleBinding,
    GlobalMetricsProviderList,
    GlobalMetricsProvider,
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
        "GlobalMetric": "GlobalMetrics",
        "GlobalMetricsProvider": "GlobalMetricsProviders",
        "Role": "Roles",
        "RoleBinding": "RoleBindings",
    }

    async def create_global_metric(self, body):
        """Creates the specified GlobalMetric.

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
        """Deletes the specified GlobalMetric.

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
        """Lists the GlobalMetrics in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

        Returns:
            GlobalMetricList: Body of the HTTP response.

        """
        path = "/core/globalmetrics".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalMetricList.deserialize(data)

    def watch_global_metrics(self, heartbeat=None):
        """Generates a watcher for the GlobalMetrics in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

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
        """Reads the specified GlobalMetric.

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
        """Updates the specified GlobalMetric.

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
        """Creates the specified GlobalMetricsProvider.

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
        """Deletes the specified GlobalMetricsProvider.

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
        """Lists the GlobalMetricsProviders in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

        Returns:
            GlobalMetricsProviderList: Body of the HTTP response.

        """
        path = "/core/globalmetricsproviders".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalMetricsProviderList.deserialize(data)

    def watch_global_metrics_providers(self, heartbeat=None):
        """Generates a watcher for the GlobalMetricsProviders in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

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
        """Updates the specified GlobalMetricsProvider.

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
        """Creates the specified Role.

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
        """Deletes the specified Role.

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
        """Lists the Roles in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

        Returns:
            RoleList: Body of the HTTP response.

        """
        path = "/core/roles".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return RoleList.deserialize(data)

    def watch_roles(self, heartbeat=None):
        """Generates a watcher for the Roles in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

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
        """Reads the specified Role.

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
        """Updates the specified Role.

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
        """Creates the specified RoleBinding.

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
        """Deletes the specified RoleBinding.

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
        """Lists the RoleBindings in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

        Returns:
            RoleBindingList: Body of the HTTP response.

        """
        path = "/core/rolebindings".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return RoleBindingList.deserialize(data)

    def watch_role_bindings(self, heartbeat=None):
        """Generates a watcher for the RoleBindings in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat in form of an empty newline. Passing 0 disables the heartbeat. Default: 10 seconds
            watch (str): Watches for changes to the described resources and return them as a stream of :class:`krake.data.core.WatchEvent`

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
        """Reads the specified RoleBinding.

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
        """Updates the specified RoleBinding.

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

