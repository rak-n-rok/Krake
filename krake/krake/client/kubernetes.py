"""This module implements all Kubernetes resources for the Krake Python API
client.
"""
from krake.data.serializable import deserialize
from krake.data.kubernetes import Application, Cluster, ApplicationStatus
from .resource import Resource


class KubernetesResource(object):
    """Mediator object for all Kubernetes applications.

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

    async def create(self, manifest):
        """Create a new Kubernetes application.

        Args:
            manifest (str): Kubernetes manifest

        Returns:
            krake.data.kubernetes.Application: Newly created Kubernetes
            application.

        """
        url = self.url.with_path(self.model.__url__)
        resp = await self.session.post(url, json={"manifest": manifest})
        data = await resp.json()
        return deserialize(self.model, data)

    async def update(self, id, manifest):
        """Update an existing Kubernetes application.

        Args:
            manifest (str): New Kubernetes manifest

        Returns:
            krake.data.kubernetes.Application: Updated Kubernetes application

        """
        url = self.url.with_path(f"{self.model.__url__}/{id}")
        resp = await self.session.put(url, json={"manifest": manifest})
        data = await resp.json()
        return deserialize(self.model, data)

    async def update_status(self, id, state, reason=None, cluster=None):
        """Update the status of the Application

        Args:
            state (krake.data.kubernetes.ApplicationState): New state of the
                application.
            reason (str, optional): Explanation for the state. Normally only
                used for FAILED state.
            cluster (str, optional): ID of the assigned Kubernetes cluster
        """
        url = self.url.with_path(f"{self.model.__url__}/{id}/status")
        resp = await self.session.put(
            url, json={"state": state.name, "reason": reason, "cluster": cluster}
        )
        data = await resp.json()
        return deserialize(ApplicationStatus, data)


class ClusterResource(Resource):
    """Resource for managing :class:`krake.data.kubernetes.Cluster` objects."""

    model = Cluster
