import asyncio
import logging
import random
from typing import NamedTuple

from functools import total_ordering
from aiohttp import ClientError

from krake.data.openstack import Project, MagnumClusterState
from krake.client.openstack import OpenStackApi
from krake.client.core import CoreApi
from krake.client.kubernetes import KubernetesApi
from krake.data.core import ReasonCode, resource_ref, Reason
from krake.data.kubernetes import ApplicationState, Cluster, ClusterBinding

from .constraints import match_cluster_constraints
from .metrics import MetricError, fetch_query
from .. import Controller, ControllerError, Reflector, WorkQueue

logger = logging.getLogger(__name__)


class NoClusterFound(ControllerError):
    """Raised in case when there is not enough resources for spawning an application
    on any of the deployments.
    """

    code = ReasonCode.NO_SUITABLE_RESOURCE


class NoProjectFound(ControllerError):
    code = ReasonCode.NO_SUITABLE_RESOURCE


@total_ordering
class RankMixin(object):
    """Mixin class for ranking objects based on their ``rank`` attribute.

    This mixin class is used by the :func:`ranked` decorator.
    """

    def __lt__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank < o.rank

    def __eq__(self, o):
        if not hasattr(o, "rank"):
            return NotImplemented
        return self.rank == o.rank


def order_by_rank(cls):
    """Decorator for making a class orderable based on the ``rank`` attribute.

    We cannot use :func:`functools.total_ordering` in
    :class:`typing.NamedTuple` because tuple already implements rich
    comparison operators preventing the decorator from generating the
    comparators. Furthermore, mixins are also not respected by
    :class:`typing.NamedTuple`.

    Hence, this decorator injects :class:`RankMixin` as an additional base
    class into the passed class.

    Args:
        cls (type): Class that should get :class:`RankMixin` as base class.

    Returns:
        type: Class with injected :class:`RankMixin` base class

    """
    if RankMixin not in cls.__mro__:
        cls.__bases__ = (RankMixin,) + cls.__bases__
    return cls


@order_by_rank
class ClusterRank(NamedTuple):
    """Named tuple for ordering Kubernetes clusters based on a rank"""

    rank: float
    cluster: Cluster


@order_by_rank
class ProjectRank(NamedTuple):
    """Named tuple for ordering OpenStack projects based on a rank"""

    rank: float
    project: Project


class Stickiness(NamedTuple):
    """Additional metric added clusters."""

    weight: float
    value: float


class Scheduler(Controller):
    """The scheduler is a controller that receives all pending and updated
    applications and selects the "best" backend for each one of them based
    on metrics of the backends and application specifications.

    Args:
        worker_count (int, optional): the amount of worker function that
            should be run as background tasks.
        reschedule_after (float, optional): number of seconds after which a resource
            should be rescheduled.
        ssl_context (ssl.SSLContext, optional): SSL context that should be
            used to communicate with the API server.
        debounce (float, optional): number of seconds the scheduler should wait
            before it reacts to a state change.
        loop (asyncio.AbstractEventLoop, optional): Event loop that should be
            used.

    """

    def __init__(
        self,
        api_endpoint,
        worker_count=10,
        reschedule_after=60,
        stickiness=0.1,
        ssl_context=None,
        debounce=0,
        loop=None,
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.magnum_queue = WorkQueue(loop=self.loop, debounce=debounce)
        self.kubernetes_api = None
        self.openstack_api = None
        self.core_api = None
        self.kubernetes_reflector = None
        self.openstack_reflector = None
        self.worker_count = worker_count
        self.reschedule_after = reschedule_after
        self.stickiness = stickiness

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.kubernetes_api = KubernetesApi(self.client)
        self.openstack_api = OpenStackApi(self.client)
        self.core_api = CoreApi(self.client)

        for i in range(self.worker_count):
            self.register_task(
                self.handle_kubernetes_applications, name=f"kubernetes_worker_{i}"
            )

        for i in range(self.worker_count):
            self.register_task(self.handle_magnum_clusters, name=f"magnum_worker_{i}")

        self.kubernetes_reflector = Reflector(
            listing=self.kubernetes_api.list_all_applications,
            watching=self.kubernetes_api.watch_all_applications,
            on_list=self.received_kubernetes_app,
            on_add=self.received_kubernetes_app,
            on_update=self.received_kubernetes_app,
            on_delete=self.received_kubernetes_app,
        )
        self.openstack_reflector = Reflector(
            listing=self.openstack_api.list_all_magnum_clusters,
            watching=self.openstack_api.watch_all_magnum_clusters,
            on_list=self.received_magnum_cluster,
            on_add=self.received_magnum_cluster,
            on_update=self.received_magnum_cluster,
            on_delete=self.received_magnum_cluster,
        )
        self.register_task(self.kubernetes_reflector, name="Kubernetes reflector")
        self.register_task(self.openstack_reflector, name="OpenStack reflector")

    async def cleanup(self):
        self.kubernetes_reflector = None
        self.openstack_reflector = None
        self.kubernetes_api = None
        self.core_api = None

    async def received_kubernetes_app(self, app):
        """Handler for Kubernetes application reflector.

        Args:
            app (krake.data.kubernetes.Application): Application received from the API

        """
        if app.metadata.deleted:
            # TODO: If an application is deleted, the scheduling of other
            #   applications should potentially revised.
            logger.debug("Cancel rescheduling of deleted %r", app)
            await self.queue.cancel(app.metadata.uid)
        elif app.status.scheduled and app.metadata.modified <= app.status.scheduled:
            await self.reschedule_kubernetes_application(app)
        elif app.status.state == ApplicationState.FAILED:
            logger.debug("Reject failed %r", app)
        else:
            logger.debug("Accept %r", app)
            await self.queue.put(app.metadata.uid, app)

    async def received_magnum_cluster(self, cluster):
        """Handler for Kubernetes application reflector.

        Args:
            cluster (krake.data.openstack.MagnumCluster): MagnumCLuster received from
                the API.

        """
        # For now, we do not reschedule Magnum clusters. Hence, not enqueuing
        # for rescheduling and not "scheduled" timestamp.
        if cluster.metadata.deleted:
            logger.debug("Ignore deleted %r", cluster)
        elif cluster.status.project is None:
            logger.debug("Accept unbound %r", cluster)
            await self.magnum_queue.put(cluster.metadata.uid, cluster)
        else:
            logger.debug("Ignore bound %r", cluster)

    async def handle_kubernetes_applications(self, run_once=False):
        """Infinite loop which fetches and hands over the Kubernetes Application
        resources to the right coroutine. The specific exceptions and error handling
        have to be added here.

        This function is meant to be run as background task. Lock the handling of a
        resource with the :attr:`lock` attribute.

        Args:
            run_once (bool, optional): if True, the function only handles one resource,
                then stops. Otherwise, continue to handle each new resource on the
                queue indefinitely.

        """
        while True:
            key, app = await self.queue.get()
            try:
                # TODO: API for supporting different application types
                logger.debug("Handling %r", app)
                await self.kubernetes_application_received(app)
            except ControllerError as error:
                app.status.reason = Reason(code=error.code, message=error.message)
                app.status.state = ApplicationState.FAILED

                await self.kubernetes_api.update_application_status(
                    namespace=app.metadata.namespace, name=app.metadata.name, body=app
                )
            finally:
                await self.queue.done(key)
            if run_once:
                break  # TODO: should we keep this? Only useful for tests

    async def handle_magnum_clusters(self, run_once=False):
        """Infinite loop which fetches and hands over the MagnumCluster resources to the
        right coroutine. The specific exceptions and error handling have to be added
        here.

        This function is meant to be run as background task. Lock the handling of a
        resource with the :attr:`lock` attribute.

        Args:
            run_once (bool, optional): if True, the function only handles one resource,
                then stops. Otherwise, continue to handle each new resource on the
                queue indefinitely.

        """
        while True:
            key, cluster = await self.magnum_queue.get()
            try:
                # TODO: API for supporting different application types
                logger.debug("Handling %r", cluster)
                await self.schedule_magnum_cluster(cluster)
            except ControllerError as error:
                cluster.status.reason = Reason(code=error.code, message=error.message)
                cluster.status.state = MagnumClusterState.FAILED

                await self.openstack_api.update_magnum_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
            finally:
                await self.magnum_queue.done(key)

            if run_once:
                break

    async def kubernetes_application_received(self, app):
        """Process a Kubernetes Application: schedule the Application on a Kubernetes
        cluster and initiate its rescheduling.

        Args:
            app (krake.data.kubernetes.Application): the Application to process.

        """
        # TODO: Evaluate spawning a new cluster
        await self.schedule_kubernetes_application(app)
        await self.reschedule_kubernetes_application(app)

    async def schedule_kubernetes_application(self, app):
        """Choose a suitable Kubernetes cluster for the given Application and bound them
        together.

        Args:
            app (krake.data.kubernetes.Application): the Application that needs to be
                scheduled to a Cluster.

        """
        logger.info("Schedule %r", app)

        clusters = await self.kubernetes_api.list_all_clusters()
        cluster = await self.select_kubernetes_cluster(app, clusters.items)

        scheduled_to = resource_ref(cluster)

        # Check if the scheduling decision changed
        if app.status.scheduled_to == scheduled_to:
            logger.debug("No change for %r", app)
            return

        if app.status.scheduled_to:
            logger.info(
                "Migrate %r from %s to %s", app, app.status.scheduled_to, scheduled_to
            )
        else:
            logger.info("Scheduled %r to %r", app, cluster)
        await self.kubernetes_api.update_application_binding(
            namespace=app.metadata.namespace,
            name=app.metadata.name,
            body=ClusterBinding(cluster=scheduled_to),
        )

    async def schedule_magnum_cluster(self, cluster):
        """Choose a suitable OpenStack Project for the given MagnumCluster and bound
        them together.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the MagnumCluster that needs
                to be scheduled to a Project.
        """
        assert cluster.status.project is None, "Magnum cluster is already bound"

        logger.info("Schedule %r", cluster)

        projects = await self.openstack_api.list_all_projects()
        project = await self.select_openstack_project(cluster, projects.items)

        if project is None:
            logger.info("No matching OpenStack project found for %r", cluster)
            raise NoProjectFound("No matching OpenStack project found")

        logger.info("Scheduled %r to %r", cluster, project)

        cluster.status.project = resource_ref(project)
        if cluster.status.project not in cluster.metadata.owners:
            cluster.metadata.owners.append(cluster.status.project)

        # TODO: How to support and compare different cluster templates?
        cluster.status.template = project.spec.template

        # TODO: Instead of copying labels and metrics, refactor the scheduler
        #   to support transitive labels and metrics.
        cluster.metadata.labels = {**project.metadata.labels, **cluster.metadata.labels}

        # If a metric with the same name is already specified in the Magnum
        # cluster spec, this takes precedence.
        metric_names = set(metric.name for metric in cluster.spec.metrics)
        for metric in project.spec.metrics:
            if metric.name not in metric_names:
                cluster.spec.metrics.append(metric)

        # Update owners and status of Magnum cluster
        #
        # TODO: Should we introduce another operation of binding the Magnum
        #   cluster to a project (like for Kubernetes applications)? This would
        #   give us the possibility to execute this as one operation.
        await self.openstack_api.update_magnum_cluster(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )
        await self.openstack_api.update_magnum_cluster_status(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

    async def reschedule_kubernetes_application(self, app):
        """Ensure that the given Application will go through the scheduling process
        after a certain interval. This allows an Application to be rescheduled to a
        more suitable Cluster if a better one is found.

        Args:
            app (krake.data.kubernetes.Application): the Application to reschedule.

        """
        # Put the application into the work queue with a certain delay. This
        # ensures the rescheduling of the application. Only put it if there is
        # not already another version of the resource in the queue. This check
        # is needed to ensure that we do not overwrite state changes with the
        # current one which might be outdated.
        if app.metadata.uid not in self.queue.dirty:
            logger.debug("Reschedule %r in %s secs", app, self.reschedule_after)
            await self.queue.put(app.metadata.uid, app, delay=self.reschedule_after)

    @staticmethod
    def match_cluster_constraints(app, cluster):
        """Evaluate if all application constraints labels match cluster labels.

        Args:
            app (krake.data.kubernetes.Application): Application that should be
                bound.
            cluster (krake.data.kubernetes.Cluster): Cluster to which the
                application should be bound.

        Returns:
            bool: True if the cluster fulfills all application cluster constraints

        """
        if not app.spec.constraints:
            return True

        # Cluster constraints
        if app.spec.constraints.cluster:
            # Label constraints for the cluster
            if app.spec.constraints.cluster.labels:
                for constraint in app.spec.constraints.cluster.labels:
                    if constraint.match(cluster.metadata.labels or {}):
                        logger.debug(
                            "Cluster %s matches constraint %r",
                            resource_ref(cluster),
                            constraint,
                        )
                    else:
                        logger.debug(
                            "Cluster %s does not match constraint %r",
                            resource_ref(cluster),
                            constraint,
                        )
                        return False

        logger.debug(
            "Cluster %s fulfills constraints of application %r",
            resource_ref(cluster),
            resource_ref(app),
        )

        return True

    @staticmethod
    def match_project_constraints(cluster, project):
        """Evaluate if all application constraints labels match project labels.

        Args:
            cluster (krake.data.openstack.MagnumCluster): Cluster that is scheduled
            project (krake.data.kubernetes.project): Project to which the
                cluster should be bound.

        Returns:
            bool: True if the project fulfills all project constraints

        """
        if not cluster.spec.constraints:
            return True

        # project constraints
        if cluster.spec.constraints.project:
            # Label constraints for the project
            if cluster.spec.constraints.project.labels:
                for constraint in cluster.spec.constraints.project.labels:
                    if constraint.match(project.metadata.labels or {}):
                        logger.debug(
                            "Project %s matches constraint %r",
                            resource_ref(project),
                            constraint,
                        )
                    else:
                        logger.debug(
                            "Project %s does not match constraint %r",
                            resource_ref(project),
                            constraint,
                        )
                        return False

        logger.debug("Project %s fulfills constraints of %r", project, cluster)

        return True

    @staticmethod
    def select_maximum(ranked):
        """From a list of ClusterRank, get the one with the best rank. If several
        ClusterRank have the same rank, one of them is chosen randomly.

        Args:
            ranked (List[ClusterRank]): the best rank will be taken from this list.

        Returns:
            ClusterRank: an element of the given list with the maximum rank.

        """
        # Find all maxima
        best = max(ranked)
        maximum = [rank for rank in ranked if rank == best]

        # Select randomly between best projects
        return random.choice(maximum)

    async def select_kubernetes_cluster(self, app, clusters):
        """Select suitable kubernetes cluster for application binding.

        Args:
            app (krake.data.kubernetes.Application): Application object for binding
            clusters (List[krake.data.kubernetes.Cluster]): Clusters between which
                the "best" one should be chosen.

        Returns:
            Cluster: Cluster suitable for application binding

        """
        matching = [
            cluster for cluster in clusters if match_cluster_constraints(app, cluster)
        ]

        if not matching:
            logger.info("No matching Kubernetes cluster for %r found", app)
            raise NoClusterFound("No matching Kubernetes cluster found")

        # Partition list if matching clusters into a list if clusters with
        # metrics and without metrics. Clusters with metrics are preferred
        # over clusters without metrics.
        with_metrics = [cluster for cluster in matching if cluster.spec.metrics]

        # Only use clusters without metrics when there are no clusters with
        # metrics.
        if not with_metrics:
            ranked = [
                self.calculate_kubernetes_cluster_rank((), cluster, app)
                for cluster in clusters
            ]
        else:
            # Rank the clusters based on their metric and return the cluster with
            # a minimal rank.
            ranked = await self.rank_kubernetes_clusters(app, with_metrics)

        if not ranked:
            logger.info("Unable to rank any Kubernetes cluster")
            raise NoClusterFound("No Kubernetes cluster available")

        return self.select_maximum(ranked).cluster

    async def select_openstack_project(self, cluster, projects):
        """Select "best" OpenStack project for the Magnum cluster.

        Args:
            cluster (krake.data.openstack.MagnumCluster): Cluster that should
                be bound to a project
            projects (List[krake.data.openstack.Project]): Projects between the
                "best" one is chosen.

        Returns:
            krake.data.openstack.Project, None: Best project matching the
            constraints of the Magnum cluster. None if no project can be found.

        """
        matching = [
            project
            for project in projects
            if self.match_project_constraints(cluster, project)
        ]

        if not matching:
            logger.info("No matching OpenStack project found for %r", cluster)
            raise NoProjectFound("No matching OpenStack project found")

        # Filter projects with metrics which are preferred over projects
        # without metrics.
        with_metrics = [project for project in matching if project.spec.metrics]

        # Only use projects without metrics when there are no projects with
        # metrics.
        if not with_metrics:
            ranked = [
                self.calculate_openstack_project_rank((), project)
                for project in projects
            ]
        else:
            # Rank the projects based on their metric and return the project with
            # a minimal rank.
            ranked = await self.rank_openstack_projects(cluster, with_metrics)

        if not ranked:
            logger.info("Unable to rank any project")
            raise NoProjectFound("No OpenStack project available")

        return self.select_maximum(ranked).project

    async def rank_kubernetes_clusters(self, app, clusters):
        """Rank kubernetes clusters based on metrics values and weights.

        Args:
            app (krake.data.kubernetes.Application): Application object for binding
            clusters (List[Cluster]): List of clusters to rank

        Returns:
            List[ClusterRank]: Ranked list of clusters

        """
        return [
            self.calculate_kubernetes_cluster_rank(metrics, cluster, app)
            for cluster in clusters
            async for metrics in self.fetch_metrics(cluster, cluster.spec.metrics)
        ]

    async def rank_openstack_projects(self, cluster, projects):
        """Rank OpenStack projects based on metric values and weights.

        Args:
            cluster (krake.data.openstack.MagnumCluster): Cluster that is scheduled
            projects (List[krake.data.openstack.Project]): List of projects to rank

        Returns:
            List[ProjectRank]: Ranked list of projects
        """
        return [
            self.calculate_openstack_project_rank(metrics, project)
            for project in projects
            async for metrics in self.fetch_metrics(project, project.spec.metrics)
        ]

    async def fetch_metrics(self, resource, metrics):
        """Async generator for fetching metrics by the given list of metric
        references.

        If a :class:`MetricError` or `ClientError` occurs, the generator stops
        which means resources where an error during metric fetching occurs can
        be skipped by:

        .. code:: python

            ranked = [
                self.rank_foo()
                for foo in foos
                async for metrics in self.fetch_metrics(foo, foo.spec.metrics)
            ]

        Args:
            resource (krake.data.serializable.ApiObject): API resource to which
                the metrics belong.
            metrics (List[krake.data.core.MetricRef]): References to metrics
                that should be fetched.

        Yields:
            List[Tuple[krake.core.Metric, float, float]]: List of fetched
                metrics with their value and weight.

        """
        assert metrics, "Got empty list of metric references"

        fetching = []
        try:
            for metric_spec in metrics:
                metric = await self.core_api.read_metric(name=metric_spec.name)
                metrics_provider = await self.core_api.read_metrics_provider(
                    name=metric.spec.provider.name
                )
                fetching.append(
                    fetch_query(
                        self.client.session,
                        metric,
                        metrics_provider,
                        metric_spec.weight,
                    )
                )
            fetched = await asyncio.gather(*fetching)
        except (MetricError, ClientError) as err:
            # If there is any issue with a metric, skip stop the generator.
            logger.error(err)
            return

        for metric, value, weight in fetched:
            logger.debug(
                "Received metric %r with value %r for %r", metric, value, resource
            )

        yield fetched

    def calculate_kubernetes_cluster_rank(self, metrics, cluster, app):
        """Calculate weighted sum of metrics values.

        Args:
            metrics (List[.metrics.QueryResult]): List of metric query results
            cluster (krake.data.kubernetes.Cluster): Cluster that is ranked
            app (krake.data.kubernetes.Application): Application object that
                should be scheduled.

        Returns:
            ClusterRank: rank of the passed cluster based on metrics and
            application.

        """
        sticky = self.calculate_kubernetes_cluster_stickiness(cluster, app)

        if not metrics:
            return ClusterRank(rank=sticky.weight * sticky.value, cluster=cluster)

        norm = sum(metric.weight for metric in metrics) + sticky.weight
        rank = (
            sum(metric.value * metric.weight for metric in metrics)
            + (sticky.value * sticky.weight)
        ) / norm

        return ClusterRank(rank=rank, cluster=cluster)

    def calculate_kubernetes_cluster_stickiness(self, cluster, app):
        """Return extra metric for clusters to make the application "stick" to
        it by increasing its rank.

        If the application is already scheduled to the passed cluster, a
        stickiness of ``1.0`` with a configurable weight is returned.
        Otherwise, a stickiness of ``0`` is returned.

        Args:
            cluster (krake.data.kubernetes.Cluster): Cluster that is ranked
            app (krake.data.kubernetes.Application): Application object that
                should be scheduled.

        Returns:
            Stickiness: Value and its weight that should be added to the
            cluster rank.

        """
        if resource_ref(cluster) != app.status.scheduled_to:
            return Stickiness(weight=0, value=0)

        return Stickiness(weight=self.stickiness, value=1.0)

    def calculate_openstack_project_rank(self, metrics, project):
        """Calculate rank of OpenStack project based on the given metrics.

        Args:
            metrics (List[krake.metrics.QueryResult]): List of metric query results
            project (krake.data.openstack.Project): Project that is ranked

        Returns:
            ProjectRank: Rank of the passed project based on metrics and
            Magnum cluster.

        """
        # Rank for a OpenStack project without any metrics
        if not metrics:
            return ProjectRank(rank=0, project=project)

        norm = sum(metric.weight for metric in metrics)
        rank = sum(metric.value * metric.weight for metric in metrics) / norm

        return ProjectRank(rank=rank, project=project)
