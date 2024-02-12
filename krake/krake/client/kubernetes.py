from functools import cached_property

from aiohttp import ClientResponseError

from krake.client import Watcher, ApiClient, InvalidResourceError
from krake.client.infrastructure import InfrastructureApi
from krake.data.infrastructure import Cloud, GlobalCloud
from krake.data.kubernetes import Cluster, ClusterList, ApplicationList, Application


class KubernetesApi(ApiClient):
    """Kubernetes API client

    Example:
        .. code:: python

            from krake.client import Client

            with Client(url="http://localhost:8080") as client:
                kubernetes_api = KubernetesApi(client)

    Args:
        client (krake.client.Client): API client for accessing the Krake HTTP API
        infrastructure_api (krake.client.infrastructure.InfrastructureApi, optional):
            Infrastructure API client to use. If not given it is created from the given
            :arg:`client` on first use.

    """

    plurals = {
        "Application": "Applications",
        "Cluster": "Clusters",
    }

    def __init__(self, *args, infrastructure_api=None, **kwargs):
        super().__init__(*args, **kwargs)

        if infrastructure_api is not None:
            self._infrastructure_api = infrastructure_api

    @cached_property
    def _infrastructure_api(self):
        return InfrastructureApi(self.client)

    async def create_application(self, body, namespace):
        """Creates the specified Application.

        Args:
            body (Application): Body of the HTTP request.
            namespace (str): namespace in which the Application will be updated.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return Application.deserialize(data)

    async def delete_application(self, namespace, name):
        """Deletes the specified Application.

        Args:
            namespace (str): namespace in which the Application will be updated.
            name (str): name of the Application.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return Application.deserialize(data)

    async def list_applications(self, namespace):
        """Lists the Applications in the namespace.

        Args:
            namespace (str): namespace in which the Application will be updated.

        Returns:
            ApplicationList: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return ApplicationList.deserialize(data)

    def watch_applications(self, namespace, heartbeat=None):
        """Generates a watcher for the Applications in the namespace.

        Args:
            namespace (str): namespace in which the Application will be updated.
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds.

        Returns:
            ApplicationList: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications".format(
            namespace=namespace,
        )

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Application)

    async def list_all_applications(self):
        """Lists all Applications.

        Returns:
            ApplicationList: Body of the HTTP response.

        """
        path = "/kubernetes/applications"
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return ApplicationList.deserialize(data)

    def watch_all_applications(self, heartbeat=None):
        """Generates a watcher for all Applications.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds.

        Returns:
            ApplicationList: Body of the HTTP response.

        """
        path = "/kubernetes/applications"

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat
        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Application)

    async def read_application(self, namespace, name):
        """Reads the specified Application.

        Args:
            namespace (str): namespace in which the Application will be updated.
            name (str): name of the Application.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return Application.deserialize(data)

    async def update_application(self, body, namespace, name):
        """Updates the specified Application.

        Args:
            body (Application): Body of the HTTP request.
            namespace (str): namespace in which the Application will be updated.
            name (str): name of the Application.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Application.deserialize(data)

    async def update_application_binding(self, body, namespace, name):
        """Updates the specified Application.

        Args:
            body (ClusterBinding): Body of the HTTP request.
            namespace (str): namespace in which the Application will be updated.
            name (str): name of the Application.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications/{name}/binding".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Application.deserialize(data)

    async def update_application_complete(self, body, namespace, name):
        """Updates the specified Application.

        Args:
            body (ApplicationComplete): Body of the HTTP request.
            namespace (str): namespace in which the Application will be updated.
            name (str): name of the Application.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications/{name}/complete".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Application.deserialize(data)

    async def update_application_shutdown(self, body, namespace, name):
        """Updates the specified Application.

        Args:
            body (ApplicationShutdown): Body of the HTTP request.
            namespace (str): namespace in which the Application will be updated.
            name (str): name of the Application.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications/{name}/shutdown".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Application.deserialize(data)

    async def update_application_status(self, body, namespace, name):
        """Updates the specified Application.

        Args:
            body (Application): Body of the HTTP request.
            namespace (str): namespace in which the Application will be updated.
            name (str): name of the Application.

        Returns:
            Application: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/applications/{name}/status".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Application.deserialize(data)

    async def create_cluster(self, body, namespace):
        """Creates the specified Cluster.

        Args:
            body (Cluster): Body of the HTTP request.
            namespace (str): namespace in which the Cluster will be updated.

        Returns:
            Cluster: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)
        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return Cluster.deserialize(data)

    async def delete_cluster(self, namespace, name):
        """Deletes the specified Cluster.

        Args:
            namespace (str): namespace in which the Cluster will be updated.
            name (str): name of the Cluster.

        Returns:
            Cluster: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return Cluster.deserialize(data)

    async def list_clusters(self, namespace):
        """Lists the Clusters in the namespace.

        Args:
            namespace (str): namespace in which the Cluster will be updated.

        Returns:
            ClusterList: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters".format(
            namespace=namespace,
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return ClusterList.deserialize(data)

    def watch_clusters(self, namespace, heartbeat=None):
        """Generates a watcher for the Clusters in the namespace.

        Args:
            namespace (str): namespace in which the Cluster will be updated.
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds.

        Returns:
            ClusterList: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters".format(
            namespace=namespace,
        )

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Cluster)

    async def list_all_clusters(self):
        """Lists all Clusters.

        Returns:
            ClusterList: Body of the HTTP response.

        """
        path = "/kubernetes/clusters"
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return ClusterList.deserialize(data)

    def watch_all_clusters(self, heartbeat=None):
        """Generates a watcher for all Clusters.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds.

        Returns:
            ClusterList: Body of the HTTP response.

        """
        path = "/kubernetes/clusters"

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat
        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Cluster)

    async def read_cluster(self, namespace, name):
        """Reads the specified Cluster.

        Args:
            namespace (str): namespace in which the Cluster will be updated.
            name (str): name of the Cluster.

        Returns:
            Cluster: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return Cluster.deserialize(data)

    async def get_cloud(self, cluster):
        """Get the cloud to which a cluster is bound.

        Returns the cloud object that is referenced in the given cluster object.

        Args:
            cluster (krake.data.kubernetes.Cluster): the Cluster with a cloud binding.

        Delegates to:
            :meth:`self._infrastructure_api.read_global_cloud`
            :meth:`self._infrastructure_api.read_cloud`

        Returns:
            Union[krake.data.infrastructure.Cloud,
                krake.data.infrastructure.GlobalCloud]: The cloud to which the given
                cluster is bound.

        Raises:
            InvalidResourceError: When the cluster binding type is unsupported.
        """
        if cluster.status.scheduled_to.kind == GlobalCloud.kind:
            try:
                return await self._infrastructure_api.read_global_cloud(
                    name=cluster.status.scheduled_to.name,
                )
            except ClientResponseError as err:
                if err.status == 404:
                    raise InvalidResourceError(
                        message="Unable to find bound global cloud: "
                        f"{cluster.status.scheduled_to.name}."
                    )

                raise

        if cluster.status.scheduled_to.kind == Cloud.kind:
            try:
                return await self._infrastructure_api.read_cloud(
                    namespace=cluster.status.scheduled_to.namespace,
                    name=cluster.status.scheduled_to.name,
                )
            except ClientResponseError as err:
                if err.status == 404:
                    raise InvalidResourceError(
                        message="Unable to find bound cloud: "
                        f"{cluster.status.scheduled_to.name}."
                    )

                raise

        raise InvalidResourceError(
            message="Unsupported cluster binding type"
            f": {cluster.status.scheduled_to.kind}."
        )

    async def update_cluster(self, body, namespace, name):
        """Updates the specified Cluster.

        Args:
            body (Cluster): Body of the HTTP request.
            namespace (str): namespace in which the Cluster will be updated.
            name (str): name of the Cluster.

        Returns:
            Cluster: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Cluster.deserialize(data)

    async def update_cluster_binding(self, body, namespace, name):
        """Update the specified Cluster.

        Args:
            body (CloudBinding): Body of the HTTP request.
            namespace (str): namespace in which the Cluster will be updated.
            name (str): name of the Cluster.

        Returns:
            Cluster: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}/binding".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Cluster.deserialize(data)

    async def update_cluster_status(self, body, namespace, name):
        """Updates the specified Cluster.

        Args:
            body (Cluster): Body of the HTTP request.
            namespace (str): namespace in which the Cluster will be updated.
            name (str): name of the Cluster.

        Returns:
            Cluster: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}/status".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Cluster.deserialize(data)

    async def update_cluster_infra_data(self, body, namespace, name):
        """Update the infrastructure data of the specified Cluster.

        Args:
            body (Cluster): Body of the HTTP request.
            namespace (str): namespace in which the Cluster will be updated.
            name (str): name of the Cluster.

        Returns:
            Cluster: Body of the HTTP response.

        """
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}/infrastructure".\
            format(namespace=namespace, name=name)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Cluster.deserialize(data)
