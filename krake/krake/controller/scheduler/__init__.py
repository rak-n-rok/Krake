"""Module for Krake controller responsible for binding Krake
applications to specific backends.
"""
from functools import total_ordering
from typing import NamedTuple

from krake.data.kubernetes import ApplicationState, Cluster
from .. import Controller, Worker


class Scheduler(Controller):
    """The scheduler is a controller watching all pending and updated
    applications and select the "best" backend.
    """

    states = (ApplicationState.PENDING, ApplicationState.UPDATED)

    async def list_and_watch(self):
        # List all Kubernetes applications
        for app in await self.client.kubernetes.application.list():
            if app.status.state in self.states:
                await self.queue.put(app.id, app)

        # Indefinitly watch Kubernetes application resources
        while True:
            async for app in self.client.kubernetes.application.watch():
                if app.status.state in self.states:
                    await self.queue.put(app.id, app)


@total_ordering
class ClusterRank(NamedTuple):
    """Named tuple for ordering clusters based on a rank"""

    rank: float
    cluster: Cluster

    def __lt__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank < o.rank

    def __eq__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank == o.rank


class SchedulerWorker(Worker):
    """Worker for :class:`Scheduler` responsible for selecting the "best"
    backend for each application based on metrics of the backends and
    application specifications.
    """

    async def resource_received(self, app):
        # TODO: Global optimization instead of incremental
        # TODO: API for supporting different application types
        cluster = await self.select_kubernetes_cluster(app)

        if cluster is None:
            await self.client.kubernetes.application.update_status(
                app.id, state=ApplicationState.FAILED, reason="No cluster available"
            )
        else:
            await self.client.kubernetes.application.update_status(
                app.id, state=ApplicationState.SCHEDULED, cluster=cluster.id
            )

    async def select_kubernetes_cluster(self, app):
        # TODO: Evaluate spawning a new cluster
        clusters = await self.client.kubernetes.cluster.list()

        if not clusters:
            return None

        ranked = [await self.rank_kubernetes_cluster(cluster) for cluster in clusters]
        return min(ranked).cluster

    async def rank_kubernetes_cluster(self, cluster):
        # TODO: Implement ranking function
        return ClusterRank(rank=0.5, cluster=cluster)
