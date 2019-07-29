"""This module implements all Kubernetes resources for the Krake Python API
client.
"""
from krake.data.serializable import serialize, deserialize
from krake.data.kubernetes import (
    Application,
    Cluster,
    ApplicationStatus,
    ClusterBinding,
)
from .resource import Resource


class KubernetesAPI(object):
    """API summarizing all Kubernetes resources.

    Attributes:
        application (ApplicationResource): Resource for managing
            :class:`krake.data.kubernetes.Application` objects
        cluster (ClusterResource): Resource for managing
            :class:`krake.data.kubernetes.Cluster` objects
    """

    def __init__(self, session, url):
        self.application = ApplicationResource(session, url)
        self.cluster = ClusterResource(session, url)


class ApplicationResource(Resource):
    """Resource for managing :class:`krake.data.kubernetes.Application`
    objects.
    """

    model = Application
    endpoints = {
        "list": "/kubernetes/namespaces/{namespace}/applications",
        "create": "/kubernetes/namespaces/{namespace}/applications",
        "get": "/kubernetes/namespaces/{namespace}/applications/{name}",
        "status": "/kubernetes/namespaces/{namespace}/applications/{name}/status",
        "binding": "/kubernetes/namespaces/{namespace}/applications/{name}/binding",
    }

    async def create(self, app):
        """Create a new Kubernetes application.

        Args:
            namespace (str): Namespace of the Kubernetes application
            manifest (str): Kubernetes manifest

        Returns:
            krake.data.kubernetes.Application: Newly created Kubernetes
            application.

        """
        url = self.url.with_path(
            self.endpoints["create"].format(namespace=app.metadata.namespace)
        )
        resp = await self.session.post(url, json=serialize(app))
        data = await resp.json()
        return deserialize(self.model, data)

    async def update(self, app):
        """Update an existing Kubernetes application.

        Args:
            namespace (str): Namespace of the Kubernetes application
            name (str): Name of the Kubernetes application
            manifest (str): New Kubernetes manifest

        Returns:
            krake.data.kubernetes.Application: Updated Kubernetes application

        """
        url = self.url.with_path(
            self.endpoints["get"].format(
                namespace=app.metadata.namespace, name=app.metadata.name
            )
        )
        resp = await self.session.put(url, json=serialize(app))
        data = await resp.json()
        return deserialize(self.model, data)

    async def update_binding(self, namespace, name, cluster):
        """Update the cluster binding of the Kubernetes application

        Args:
            namespace (str): Namespace of the Kubernetes application
            name (str): Name of the Kubernetes application
            cluster (krake.data.kubernetes.Cluster): Assigned
                Kubernetes cluster
        """
        ref = ClusterResource.endpoints["get"].format(
            namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        url = self.url.with_path(
            self.endpoints["binding"].format(namespace=namespace, name=name)
        )
        resp = await self.session.put(url, json={"cluster": ref})
        data = await resp.json()
        return deserialize(ClusterBinding, data)

    async def update_status(self, namespace, name, cluster, state, reason=None):
        """Update the status of the Application

        Args:
            namespace (str): Namespace of the Kubernetes application
            name (str): Name of the Kubernetes application
            cluster (str, None): API link to the Kubernetes cluster the
                application is currently running on.
            state (krake.data.kubernetes.ApplicationState): New state of the
                application.
            reason (str, optional): Explanation for the state. Normally only
                used for FAILED state.
        """
        url = self.url.with_path(
            self.endpoints["status"].format(namespace=namespace, name=name)
        )
        resp = await self.session.put(
            url, json={"state": state.name, "reason": reason, "cluster": cluster}
        )
        data = await resp.json()
        return deserialize(ApplicationStatus, data)


class ClusterResource(Resource):
    """Resource for managing :class:`krake.data.kubernetes.Cluster` objects."""

    model = Cluster
    endpoints = {
        "list": "/kubernetes/namespaces/{namespace}/clusters",
        "create": "/kubernetes/namespaces/{namespace}/clusters",
        "get": "/kubernetes/namespaces/{namespace}/clusters/{name}",
    }
