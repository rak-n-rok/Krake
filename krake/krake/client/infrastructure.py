from aiohttp import ClientResponseError

from krake.client import Watcher, ApiClient, InvalidResourceError
from krake.data.infrastructure import (
    GlobalInfrastructureProvider,
    GlobalCloud,
    CloudList,
    InfrastructureProvider,
    InfrastructureProviderList,
    GlobalCloudList,
    Cloud,
    GlobalInfrastructureProviderList,
)


class InfrastructureApi(ApiClient):
    """Infrastructure API client

    Example:
        .. code:: python

            from krake.client import Client

            with Client(url="http://localhost:8080") as client:
                infrastructure_api = InfrastructureApi(client)

    Args:
        client (krake.client.Client): API client for accessing the Krake HTTP API

    """

    plurals = {
        "GlobalInfrastructureProvider": "GlobalInfrastructureProviders",
        "InfrastructureProvider": "InfrastructureProviders",
        "GlobalCloud": "GlobalClouds",
        "Cloud": "Clouds",
    }

    async def create_global_infrastructure_provider(self, body):
        """Create the specified GlobalInfrastructureProvider.

        Args:
            body (GlobalInfrastructureProvider): Body of the HTTP request.

        Returns:
            GlobalInfrastructureProvider: Body of the HTTP response.

        """
        path = "/infrastructure/globalinfrastructureproviders".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return GlobalInfrastructureProvider.deserialize(data)

    async def delete_global_infrastructure_provider(self, name):
        """Delete the specified GlobalInfrastructureProvider.

        Args:
            name (str): name of the GlobalInfrastructureProvider.

        Returns:
            GlobalInfrastructureProvider: Body of the HTTP response.

        """
        path = "/infrastructure/globalinfrastructureproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return GlobalInfrastructureProvider.deserialize(data)

    async def list_global_infrastructure_providers(self):
        """List the GlobalInfrastructureProviders in the namespace.

        Returns:
            GlobalInfrastructureProviderList: Body of the HTTP response.

        """
        path = "/infrastructure/globalinfrastructureproviders".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalInfrastructureProviderList.deserialize(data)

    def watch_global_infrastructure_providers(self, heartbeat=None):
        """Generate a watcher for the GlobalInfrastructureProviders in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends
                a heartbeat in form of an empty newline.
                Passing 0 disables the heartbeat. Default: 10 seconds

        Returns:
            GlobalInfrastructureProviderList: Body of the HTTP response.

        """
        path = "/infrastructure/globalinfrastructureproviders".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, GlobalInfrastructureProvider)

    async def read_global_infrastructure_provider(self, name):
        """Read the specified GlobalInfrastructureProvider.

        Args:
            name (str): name of the GlobalInfrastructureProvider.

        Returns:
            GlobalInfrastructureProvider: Body of the HTTP response.

        """
        path = "/infrastructure/globalinfrastructureproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalInfrastructureProvider.deserialize(data)

    async def update_global_infrastructure_provider(self, body, name):
        """Update the specified GlobalInfrastructureProvider.

        Args:
            body (GlobalInfrastructureProvider): Body of the HTTP request.
            name (str): name of the GlobalInfrastructureProvider.

        Returns:
            GlobalInfrastructureProvider: Body of the HTTP response.

        """
        path = "/infrastructure/globalinfrastructureproviders/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return GlobalInfrastructureProvider.deserialize(data)

    async def create_infrastructure_provider(self, body, namespace):
        """Create the specified InfrastructureProvider.

        Args:
            body (InfrastructureProvider): Body of the HTTP request.
            namespace (str): namespace in which the InfrastructureProvider
                will be updated.

        Returns:
            InfrastructureProvider: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return InfrastructureProvider.deserialize(data)

    async def delete_infrastructure_provider(self, namespace, name):
        """Delete the specified InfrastructureProvider.

        Args:
            namespace (str): namespace in which the InfrastructureProvider
                will be updated.
            name (str): name of the InfrastructureProvider.

        Returns:
            InfrastructureProvider: Body of the HTTP response.

        """
        path = (
            "/infrastructure/namespaces/{namespace}/"
            "infrastructureproviders/{name}".format(namespace=namespace, name=name)
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return InfrastructureProvider.deserialize(data)

    async def list_infrastructure_providers(self, namespace):
        """List the InfrastructureProviders in the namespace.

        Args:
            namespace (str): namespace in which the InfrastructureProvider
                will be updated.

        Returns:
            InfrastructureProviderList: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return InfrastructureProviderList.deserialize(data)

    def watch_infrastructure_providers(self, namespace, heartbeat=None):
        """Generate a watcher for the InfrastructureProviders in the namespace.

        Args:
            namespace (str): namespace in which the InfrastructureProvider
                will be updated.
            heartbeat (int): Number of seconds after which the server sends a
                heartbeat in form of an empty newline.
                Passing 0 disables the heartbeat. Default: 10 seconds

        Returns:
            InfrastructureProviderList: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders".format(
            namespace=namespace,
        )

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, InfrastructureProvider)

    async def list_all_infrastructure_providers(self):
        """List all InfrastructureProviders.

        Returns:
            InfrastructureProviderList: Body of the HTTP response.

        """
        path = "/infrastructure/infrastructureproviders"
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return InfrastructureProviderList.deserialize(data)

    def watch_all_infrastructure_providers(self, heartbeat=None):
        """Generate a watcher for all InfrastructureProviders.

        Args:
            heartbeat (int): Number of seconds after which the server sends a
                heartbeat in form of an empty newline.
                Passing 0 disables the heartbeat. Default: 10 seconds

        Returns:
            InfrastructureProviderList: Body of the HTTP response.

        """
        path = "/infrastructure/infrastructureproviders"

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat
        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, InfrastructureProvider)

    async def read_infrastructure_provider(self, namespace, name):
        """Read the specified InfrastructureProvider.

        Args:
            namespace (str): namespace in which the InfrastructureProvider
                will be updated.
            name (str): name of the InfrastructureProvider.

        Returns:
            InfrastructureProvider: Body of the HTTP response.

        """
        path = (
            "/infrastructure/namespaces/{namespace}/"
            "infrastructureproviders/{name}".format(namespace=namespace, name=name)
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return InfrastructureProvider.deserialize(data)

    async def update_infrastructure_provider(self, body, namespace, name):
        """Update the specified InfrastructureProvider.

        Args:
            body (InfrastructureProvider): Body of the HTTP request.
            namespace (str): namespace in which the InfrastructureProvider
                will be updated.
            name (str): name of the InfrastructureProvider.

        Returns:
            InfrastructureProvider: Body of the HTTP response.

        """
        path = (
            "/infrastructure/namespaces/{namespace}/"
            "infrastructureproviders/{name}".format(namespace=namespace, name=name)
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return InfrastructureProvider.deserialize(data)

    async def create_global_cloud(self, body):
        """Create the specified GlobalCloud.

        Args:
            body (GlobalCloud): Body of the HTTP request.

        Returns:
            GlobalCloud: Body of the HTTP response.

        """
        path = "/infrastructure/globalclouds".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return GlobalCloud.deserialize(data)

    async def delete_global_cloud(self, name):
        """Delete the specified GlobalCloud.

        Args:
            name (str): name of the GlobalCloud.

        Returns:
            GlobalCloud: Body of the HTTP response.

        """
        path = "/infrastructure/globalclouds/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return GlobalCloud.deserialize(data)

    async def list_global_clouds(self):
        """List the GlobalClouds in the namespace.

        Returns:
            GlobalCloudList: Body of the HTTP response.

        """
        path = "/infrastructure/globalclouds".format()
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalCloudList.deserialize(data)

    def watch_global_clouds(self, heartbeat=None):
        """Generate a watcher for the GlobalClouds in the namespace.

        Args:
            heartbeat (int): Number of seconds after which the server sends a
                heartbeat in form of an empty newline.
                Passing 0 disables the heartbeat. Default: 10 seconds

        Returns:
            GlobalCloudList: Body of the HTTP response.

        """
        path = "/infrastructure/globalclouds".format()

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, GlobalCloud)

    async def read_global_cloud(self, name):
        """Read the specified GlobalCloud.

        Args:
            name (str): name of the GlobalCloud.

        Returns:
            GlobalCloud: Body of the HTTP response.

        """
        path = "/infrastructure/globalclouds/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return GlobalCloud.deserialize(data)

    async def update_global_cloud(self, body, name):
        """Update the specified GlobalCloud.

        Args:
            body (GlobalCloud): Body of the HTTP request.
            name (str): name of the GlobalCloud.

        Returns:
            GlobalCloud: Body of the HTTP response.

        """
        path = "/infrastructure/globalclouds/{name}".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return GlobalCloud.deserialize(data)

    async def update_global_cloud_status(self, body, name):
        """Update the specified GlobalCloud.

        Args:
            body (GlobalCloud): Body of the HTTP request.
            name (str): name of the GlobalCloud.

        Returns:
            GlobalCloud: Body of the HTTP response.

        """
        path = "/infrastructure/globalclouds/{name}/status".format(name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return GlobalCloud.deserialize(data)

    async def create_cloud(self, body, namespace):
        """Create the specified Cloud.

        Args:
            body (Cloud): Body of the HTTP request.
            namespace (str): namespace in which the Cloud will be updated.

        Returns:
            Cloud: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/clouds".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return Cloud.deserialize(data)

    async def delete_cloud(self, namespace, name):
        """Delete the specified Cloud.

        Args:
            namespace (str): namespace in which the Cloud will be updated.
            name (str): name of the Cloud.

        Returns:
            Cloud: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/clouds/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return Cloud.deserialize(data)

    async def list_clouds(self, namespace):
        """List the Clouds in the namespace.

        Args:
            namespace (str): namespace in which the Cloud will be updated.

        Returns:
            CloudList: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/clouds".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return CloudList.deserialize(data)

    def watch_clouds(self, namespace, heartbeat=None):
        """Generate a watcher for the Clouds in the namespace.

        Args:
            namespace (str): namespace in which the Cloud will be updated.
            heartbeat (int): Number of seconds after which the server sends a
                heartbeat in form of an empty newline.
                Passing 0 disables the heartbeat. Default: 10 seconds

        Returns:
            CloudList: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/clouds".format(
            namespace=namespace,
        )

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Cloud)

    async def list_all_clouds(self):
        """List all Clouds.

        Returns:
            CloudList: Body of the HTTP response.

        """
        path = "/infrastructure/clouds"
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return CloudList.deserialize(data)

    def watch_all_clouds(self, heartbeat=None):
        """Generate a watcher for all Clouds.

        Args:
            heartbeat (int): Number of seconds after which the server sends a
                heartbeat in form of an empty newline.
                Passing 0 disables the heartbeat. Default: 10 seconds

        Returns:
            CloudList: Body of the HTTP response.

        """
        path = "/infrastructure/clouds"

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat
        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Cloud)

    async def read_cloud(self, namespace, name):
        """Read the specified Cloud.

        Args:
            namespace (str): namespace in which the Cloud will be updated.
            name (str): name of the Cloud.

        Returns:
            Cloud: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/clouds/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return Cloud.deserialize(data)

    async def update_cloud(self, body, namespace, name):
        """Update the specified Cloud.

        Args:
            body (Cloud): Body of the HTTP request.
            namespace (str): namespace in which the Cloud will be updated.
            name (str): name of the Cloud.

        Returns:
            Cloud: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/clouds/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Cloud.deserialize(data)

    async def update_cloud_status(self, body, namespace, name):
        """Update the specified Cloud.

        Args:
            body (Cloud): Body of the HTTP request.
            namespace (str): namespace in which the Cloud will be updated.
            name (str): name of the Cloud.

        Returns:
            Cloud: Body of the HTTP response.

        """
        path = "/infrastructure/namespaces/{namespace}/clouds/{name}/status".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Cloud.deserialize(data)

    async def get_infrastructure_provider(self, cloud):
        """Get the infrastructure provider referenced in the given cloud.

        Args:
            cloud (Union[Cloud, GlobalCLoud]): the cloud with the
                infrastructure provider reference.

        Raises:
            InvalidResourceError: When the cluster reference to
                the infrastructure provider is wrong.

        Returns:
            Union[InfrastructureProvider, GlobalInfrastructureProvider]:
                Infrastructure provider referenced in the given cloud.
        """
        if cloud.spec.type == "openstack":
            try:
                return await self.read_infrastructure_provider(
                    namespace=cloud.metadata.namespace,
                    name=cloud.spec.openstack.infrastructure_provider.name,
                )
            except ClientResponseError as err:
                if err.status == 404:
                    try:
                        return await self.read_global_infrastructure_provider(  # noqa: E501
                            name=cloud.spec.openstack.infrastructure_provider.name
                        )
                    except ClientResponseError as err:
                        if err.status == 404:
                            raise InvalidResourceError(
                                message=(
                                    "Unable to find infrastructure provider "
                                    f"{cloud.spec.openstack.infrastructure_provider.name} "  # noqa: E501
                                    f"referenced in the bound cloud `{cloud.metadata.name}"  # noqa: E501
                                )
                            )

                        raise
                raise
        else:
            raise InvalidResourceError(
                message=f"Unsupported cloud type: {cloud.spec.type}."
            )
