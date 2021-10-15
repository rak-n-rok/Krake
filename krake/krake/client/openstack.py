from krake.client import Watcher, ApiClient
from krake.data.openstack import MagnumCluster, ProjectList, MagnumClusterList, Project


class OpenStackApi(ApiClient):
    """Openstack API client

    Example:
        .. code:: python

            from krake.client import Client

            with Client(url="http://localhost:8080") as client:
                openstack_api = OpenStackApi(client)

    Args:
        client (krake.client.Client): API client for accessing the Krake HTTP API

    """

    plurals = {"MagnumCluster": "MagnumClusters", "Project": "Projects"}

    async def create_magnum_cluster(self, body, namespace):
        """Creates the specified MagnumCluster.

        Args:
            body (MagnumCluster): Body of the HTTP request.
            namespace (str): namespace in which the MagnumCluster will be updated.

        Returns:
            MagnumCluster: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters".format(
            namespace=namespace
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return MagnumCluster.deserialize(data)

    async def delete_magnum_cluster(self, namespace, name):
        """Deletes the specified MagnumCluster.

        Args:
            namespace (str): namespace in which the MagnumCluster will be updated.
            name (str): name of the MagnumCluster.

        Returns:
            MagnumCluster: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return MagnumCluster.deserialize(data)

    async def list_magnum_clusters(self, namespace):
        """Lists the MagnumClusters in the namespace.

        Args:
            namespace (str): namespace in which the MagnumCluster will be updated.

        Returns:
            MagnumClusterList: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters".format(
            namespace=namespace
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MagnumClusterList.deserialize(data)

    def watch_magnum_clusters(self, namespace, heartbeat=None):
        """Generates a watcher for the MagnumClusters in the namespace.

        Args:
            namespace (str): namespace in which the MagnumCluster will be updated.
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            MagnumClusterList: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters".format(
            namespace=namespace
        )

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, MagnumCluster)

    async def list_all_magnum_clusters(self):
        """Lists all MagnumClusters.

        Returns:
            MagnumClusterList: Body of the HTTP response.

        """
        path = "/openstack/magnumclusters"
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MagnumClusterList.deserialize(data)

    def watch_all_magnum_clusters(self, heartbeat=None):
        """Generates a watcher for all MagnumClusters.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            MagnumClusterList: Body of the HTTP response.

        """
        path = "/openstack/magnumclusters"

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat
        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, MagnumCluster)

    async def read_magnum_cluster(self, namespace, name):
        """Reads the specified MagnumCluster.

        Args:
            namespace (str): namespace in which the MagnumCluster will be updated.
            name (str): name of the MagnumCluster.

        Returns:
            MagnumCluster: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return MagnumCluster.deserialize(data)

    async def update_magnum_cluster(self, body, namespace, name):
        """Updates the specified MagnumCluster.

        Args:
            body (MagnumCluster): Body of the HTTP request.
            namespace (str): namespace in which the MagnumCluster will be updated.
            name (str): name of the MagnumCluster.

        Returns:
            MagnumCluster: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return MagnumCluster.deserialize(data)

    async def update_magnum_cluster_binding(self, body, namespace, name):
        """Updates the specified MagnumCluster.

        Args:
            body (MagnumClusterBinding): Body of the HTTP request.
            namespace (str): namespace in which the MagnumCluster will be updated.
            name (str): name of the MagnumCluster.

        Returns:
            MagnumCluster: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}/binding".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return MagnumCluster.deserialize(data)

    async def update_magnum_cluster_status(self, body, namespace, name):
        """Updates the specified MagnumCluster.

        Args:
            body (MagnumCluster): Body of the HTTP request.
            namespace (str): namespace in which the MagnumCluster will be updated.
            name (str): name of the MagnumCluster.

        Returns:
            MagnumCluster: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}/status".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return MagnumCluster.deserialize(data)

    async def create_project(self, body, namespace):
        """Creates the specified Project.

        Args:
            body (Project): Body of the HTTP request.
            namespace (str): namespace in which the Project will be updated.

        Returns:
            Project: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/projects".format(namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("POST", url, json=body.serialize())
        data = await resp.json()
        return Project.deserialize(data)

    async def delete_project(self, namespace, name):
        """Deletes the specified Project.

        Args:
            namespace (str): namespace in which the Project will be updated.
            name (str): name of the Project.

        Returns:
            Project: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/projects/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("DELETE", url)
        if resp.status == 204:
            return None
        data = await resp.json()
        return Project.deserialize(data)

    async def list_projects(self, namespace):
        """Lists the Projects in the namespace.

        Args:
            namespace (str): namespace in which the Project will be updated.

        Returns:
            ProjectList: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/projects".format(namespace=namespace)
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return ProjectList.deserialize(data)

    def watch_projects(self, namespace, heartbeat=None):
        """Generates a watcher for the Projects in the namespace.

        Args:
            namespace (str): namespace in which the Project will be updated.
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            ProjectList: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/projects".format(namespace=namespace)

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat

        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Project)

    async def list_all_projects(self):
        """Lists all Projects.

        Returns:
            ProjectList: Body of the HTTP response.

        """
        path = "/openstack/projects"
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return ProjectList.deserialize(data)

    def watch_all_projects(self, heartbeat=None):
        """Generates a watcher for all Projects.

        Args:
            heartbeat (int): Number of seconds after which the server sends a heartbeat
                in form of an empty newline. Passing 0 disables the heartbeat. Default:
                10 seconds

        Returns:
            ProjectList: Body of the HTTP response.

        """
        path = "/openstack/projects"

        query = {"watch": ""}
        if heartbeat is not None:
            query["heartbeat"] = heartbeat
        url = self.client.url.with_path(path).with_query(query)

        return Watcher(self.client.session, url, Project)

    async def read_project(self, namespace, name):
        """Reads the specified Project.

        Args:
            namespace (str): namespace in which the Project will be updated.
            name (str): name of the Project.

        Returns:
            Project: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/projects/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("GET", url)
        data = await resp.json()
        return Project.deserialize(data)

    async def update_project(self, body, namespace, name):
        """Updates the specified Project.

        Args:
            body (Project): Body of the HTTP request.
            namespace (str): namespace in which the Project will be updated.
            name (str): name of the Project.

        Returns:
            Project: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/projects/{name}".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Project.deserialize(data)

    async def update_project_status(self, body, namespace, name):
        """Updates the specified Project.

        Args:
            body (Project): Body of the HTTP request.
            namespace (str): namespace in which the Project will be updated.
            name (str): name of the Project.

        Returns:
            Project: Body of the HTTP response.

        """
        path = "/openstack/namespaces/{namespace}/projects/{name}/status".format(
            namespace=namespace, name=name
        )
        url = self.client.url.with_path(path)

        resp = await self.client.session.request("PUT", url, json=body.serialize())
        data = await resp.json()
        return Project.deserialize(data)
