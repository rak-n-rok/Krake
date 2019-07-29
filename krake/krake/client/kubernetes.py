"""This module implements all Kubernetes resources for the Krake Python API
client.
"""
from krake.data import Key
from krake.data.serializable import deserialize
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
        "list": Key("/kubernetes/namespaces/{namespace}/applications"),
        "create": Key("/kubernetes/namespaces/{namespace}/applications"),
        "get": Key("/kubernetes/namespaces/{namespace}/applications/{name}"),
        "status": Key("/kubernetes/namespaces/{namespace}/applications/{name}/status"),
        "binding": Key(
            "/kubernetes/namespaces/{namespace}/applications/{name}/binding"
        ),
    }

    async def update_binding(self, namespace, name, cluster):
        """Update the cluster binding of the Kubernetes application

        Args:
            namespace (str): Namespace of the Kubernetes application
            name (str): Name of the Kubernetes application
            cluster (krake.data.kubernetes.Cluster): Assigned
                Kubernetes cluster
        """
        ref = ClusterResource.endpoints["get"].format_kwargs(
            namespace=cluster.metadata.namespace, name=cluster.metadata.name
        )
        url = self.url.with_path(
            self.endpoints["binding"].format_kwargs(namespace=namespace, name=name)
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
            self.endpoints["status"].format_kwargs(namespace=namespace, name=name)
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
        "list": Key("/kubernetes/namespaces/{namespace}/clusters"),
        "create": Key("/kubernetes/namespaces/{namespace}/clusters"),
        "get": Key("/kubernetes/namespaces/{namespace}/clusters/{name}"),
    }
