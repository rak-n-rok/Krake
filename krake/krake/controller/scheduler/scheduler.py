import asyncio
from datetime import timedelta
import logging
import random
from typing import NamedTuple

from functools import total_ordering
from aiohttp import ClientError

from krake import utils
from krake.data.openstack import (
    Project,
    MagnumClusterState,
    MagnumClusterBinding,
    ProjectState,
)
from krake.client.openstack import OpenStackApi
from krake.client.core import CoreApi
from krake.client.kubernetes import KubernetesApi
from krake.data.core import ReasonCode, resource_ref, Reason
from krake.data.kubernetes import (
    ApplicationState,
    Cluster,
    ClusterBinding,
    ClusterState,
)

from .constraints import match_cluster_constraints, match_project_constraints
from .metrics import MetricError, fetch_query, MetricsProviderError
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
    """Mixin class for ranking objects based on their ``score`` attribute.

    This mixin class is used by the :func:`order_by_score` decorator.
    """

    def __lt__(self, o):
        if not hasattr(o, "score"):
            return NotImplemented
        return self.score < o.score

    def __eq__(self, o):
        if not hasattr(o, "score"):
            return NotImplemented
        return self.score == o.score


def orderable_by_score(cls):
    """Decorator for making a class orderable based on the ``score`` attribute.

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


@orderable_by_score
class ClusterScore(NamedTuple):
    """Named tuple for ordering Kubernetes clusters based on a score"""

    score: float
    cluster: Cluster


@orderable_by_score
class ProjectScore(NamedTuple):
    """Named tuple for ordering OpenStack projects based on a score"""

    score: float
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

        self.kubernetes = None
        self.openstack = None

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.kubernetes_api = KubernetesApi(self.client)
        self.openstack_api = OpenStackApi(self.client)
        self.core_api = CoreApi(self.client)

        self.openstack = OpenstackHandler(
            self.client, self.magnum_queue, self.openstack_api, self.core_api
        )
        self.kubernetes = KubernetesHandler(
            self.client,
            self.queue,
            self.kubernetes_api,
            self.core_api,
            self.stickiness,
            self.reschedule_after,
        )

        for i in range(self.worker_count):
            self.register_task(
                self.kubernetes.handle_kubernetes_applications,
                name=f"kubernetes_worker_{i}",
            )

        for i in range(self.worker_count):
            self.register_task(
                self.openstack.handle_magnum_clusters, name=f"magnum_worker_{i}"
            )

        self.kubernetes_reflector = Reflector(
            listing=self.kubernetes_api.list_all_applications,
            watching=self.kubernetes_api.watch_all_applications,
            on_list=self.kubernetes.received_kubernetes_app,
            on_add=self.kubernetes.received_kubernetes_app,
            on_update=self.kubernetes.received_kubernetes_app,
            on_delete=self.kubernetes.received_kubernetes_app,
            resource_plural="Kubernetes Applications",
        )
        self.openstack_reflector = Reflector(
            listing=self.openstack_api.list_all_magnum_clusters,
            watching=self.openstack_api.watch_all_magnum_clusters,
            on_list=self.openstack.received_magnum_cluster,
            on_add=self.openstack.received_magnum_cluster,
            on_update=self.openstack.received_magnum_cluster,
            on_delete=self.openstack.received_magnum_cluster,
            resource_plural="Magnum Clusters",
        )
        self.register_task(self.kubernetes_reflector, name="Kubernetes reflector")
        self.register_task(self.openstack_reflector, name="OpenStack reflector")

    async def cleanup(self):
        self.kubernetes_reflector = None
        self.openstack_reflector = None
        self.openstack_api = None
        self.kubernetes_api = None
        self.core_api = None
        self.kubernetes = None
        self.openstack = None


class Handler(object):
    def __init__(self, client, queue, api, core_api):

        self.client = client
        self.queue = queue
        self.api = api
        self.core_api = core_api

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

    @staticmethod
    def metrics_reason_from_err(error):
        """Convert an error as exception into an instance of :class:`Reason`. Also
        generates an appropriate message if necessary.

        Args:
            error (Exception): error that occurred which has to be converted into a
                reason.

        Returns:
            Reason: reason generated from the provided error.
        """
        message = None
        if isinstance(error, MetricsProviderError):
            reason_code = ReasonCode.UNREACHABLE_METRICS_PROVIDER
        elif isinstance(error, MetricError):
            reason_code = ReasonCode.INVALID_METRIC
        elif isinstance(error, ClientError):
            resource_name = error.request_info.url.path.split("/")[-1]
            if "metricsprovider" in error.request_info.url.path:
                reason_code = ReasonCode.UNKNOWN_METRICS_PROVIDER
                message = (
                    f"The metrics provider {resource_name!r} was not found in the Krake"
                    f" database."
                )
            else:
                reason_code = ReasonCode.UNKNOWN_METRIC
                message = (
                    f"The metric {resource_name!r} was not found in the Krake database."
                )
        else:
            raise error

        final_message = message if message else str(error)
        return Reason(code=reason_code, message=final_message)

    async def update_resource_status(self, resource, metrics, reasons):
        """Update the status of the provided resource with the new list of reasons for
        metrics which failed.

        Args:
            resource (krake.data.serializable.ApiObject): the resource to updated.
            metrics (list[krake.data.core.MetricRef]): the list of metrics for which the
                scheduler attempted to fetch the current value.
            reasons (list[Reason]): the list of reasons for the metrics failing which
                were found. For each metric in the :attr:`metrics` argument, there
                should be one element in this argument: the reason for the metric
                failing, or None if it did not fail.

        Raises:
            AssertionError: if length of metrics and reasons don't match up
            ValueError: if the resource kind is not supported
        """
        assert len(metrics) == len(reasons)

        if resource.kind == "Cluster":
            resource.status.state = ClusterState.FAILING_METRICS
            update_status_client = self.api.update_cluster_status
        elif resource.kind == "Project":
            resource.status.state = ProjectState.FAILING_METRICS
            update_status_client = self.api.update_project_status
        else:
            raise ValueError(f"Unsupported kind: {resource.kind}.")

        # Add to resource only if a failure occurred.
        resource.status.metrics_reasons = {}
        for i, reason in enumerate(reasons):
            if reason:
                resource.status.metrics_reasons[metrics[i].name] = reason

        await update_status_client(
            namespace=resource.metadata.namespace,
            name=resource.metadata.name,
            body=resource,
        )

    async def fetch_metrics(self, resource, metrics):
        """Async generator for fetching metrics by the given list of metric
        references.

        If a :class:`MetricError` or `ClientError` occurs, the generator stops
        which means resources where an error during metric fetching occurs can
        be skipped by:

        .. code:: python

            scores = [
                self.calculate_foo_score()
                for foo in foos
                async for metrics in self.fetch_metrics(foo, foo.spec.metrics)
            ]

        Args:
            resource (krake.data.serializable.ApiObject): API resource to which
                the metrics belong.
            metrics (list[krake.data.core.MetricRef]): References to metrics
                that should be fetched.

        Raises:
            AssertionError: if metrics are not set or stopped is set

        Yields:
            list[krake.controller.scheduler.metrics.QueryResult]: List of fetched
                metrics with their value and weight.
        """
        assert metrics, "Got empty list of metric references"

        errors = []
        reasons = []
        fetching = []
        for metric_spec in metrics:
            try:
                if metric_spec.namespaced:
                    metric = await self.core_api.read_metric(
                        name=metric_spec.name, namespace=resource.metadata.namespace
                    )
                    metrics_provider = await self.core_api.read_metrics_provider(
                        name=metric.spec.provider.name,
                        namespace=resource.metadata.namespace
                    )
                else:
                    metric = await self.core_api.read_global_metric(
                        name=metric_spec.name
                    )
                    metrics_provider = await self.core_api.read_global_metrics_provider(
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
                reasons.append(None)  # Add an empty placeholder when no error occurred.
            except ClientError as err:
                reasons.append(self.metrics_reason_from_err(err))
                errors.append(err)

        fetched = await asyncio.gather(*fetching, return_exceptions=True)

        # Convert the errors which occurred when fetching the value of the remaining
        # metrics into Reason instances.
        # For this, the next occurrence of "None" inside the "reasons" list is used.
        # Each one of this occurrence corresponds to a task for fetching the metric. So
        # if for example the 3rd element in "fetched" is an error, the 3rd "None" in
        # "reasons" must be replaced.
        none_reason_iter = (i for i, reason in enumerate(reasons) if reason is None)
        for result in fetched:
            # Get the index of the next "None" inside "reasons".
            index_of_none = next(none_reason_iter)
            if isinstance(result, Exception):
                reasons[index_of_none] = self.metrics_reason_from_err(result)
                errors.append(result)

        stopped = False
        try:
            next(none_reason_iter)
        except StopIteration:
            stopped = True
        assert stopped

        if any(reasons):
            # If there is any issue with a metric, skip stop the generator.
            await self.update_resource_status(resource, metrics, reasons)
            for error in errors:
                if error:
                    logger.error(error)
            return

        for metric, weight, value in fetched:
            logger.debug(
                "Received metric %r with value %r for %r", metric, value, resource
            )

        yield fetched


class KubernetesHandler(Handler):
    def __init__(self, client, queue, api, core_api, stickiness, reschedule_after):

        super(KubernetesHandler, self).__init__(client, queue, api, core_api)

        self.stickiness = stickiness
        self.reschedule_after = reschedule_after

    async def received_kubernetes_app(self, app):
        """Handler for Kubernetes application reflector.

        Args:
            app (krake.data.kubernetes.Application): Application received from the API

        """
        if app.metadata.deleted:
            # TODO: If an application is deleted, the scheduling of other
            #   applications should potentially be revised.
            logger.debug("Cancel rescheduling of deleted %r", app)
            await self.queue.cancel(app.metadata.uid)

        # The application is already scheduled and no change has been made to the specs
        # since then. Nevertheless, we should perform a periodic rescheduling to handle
        # changes in the cluster metric values.
        elif (
            app.status.kube_controller_triggered
            and app.metadata.modified <= app.status.kube_controller_triggered
        ):
            await self.reschedule_kubernetes_application(app)

        elif app.status.state == ApplicationState.FAILED:
            logger.debug("Reject failed %r", app)
        else:
            logger.debug("Accept %r", app)
            await self.queue.put(app.metadata.uid, app)

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

                await self.api.update_application_status(
                    namespace=app.metadata.namespace, name=app.metadata.name, body=app
                )
            finally:
                await self.queue.done(key)
            if run_once:
                break  # TODO: should we keep this? Only useful for tests

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

        if app.status.scheduled_to and not app.spec.constraints.migration:
            logger.debug(
                "Not migrating %r, since migration of the application is disabled.", app
            )
            return

        clusters = await self.api.list_all_clusters()
        cluster = await self.select_kubernetes_cluster(app, clusters.items)

        scheduled_to = resource_ref(cluster)

        # Check if the scheduling decision changed
        if app.status.scheduled_to == scheduled_to:
            logger.debug("No change for %r", app)

            # The timestamp is updated anyway because the KubernetesController is
            # waiting for the Scheduler to take a decision before handling the update on
            # an Application. By updating this, the KubernetesController can start
            # working on the current Application.
            # However, if no update has been performed on the Application, then the
            # modified timestamp is lower. As we are in the case of no change in the
            # scheduling decision, there is no need to have the KubernetesController
            # processing the Application. Updating the timestamp would simply trigger
            # a processing of the Application by the KubernetesController, which would
            # not make the controller perform any action.
            if app.metadata.modified > app.status.kube_controller_triggered:
                app.status.kube_controller_triggered = utils.now()
                await self.api.update_application_status(
                    namespace=app.metadata.namespace, name=app.metadata.name, body=app
                )
            return

        if app.status.scheduled_to:
            logger.info(
                "Migrate %r from %s to %s", app, app.status.scheduled_to, scheduled_to
            )
        else:
            logger.info("Scheduled %r to %r", app, cluster)

        await self.api.update_application_binding(
            namespace=app.metadata.namespace,
            name=app.metadata.name,
            body=ClusterBinding(cluster=scheduled_to),
        )

    async def reschedule_kubernetes_application(self, app):
        """Ensure that the given Application will go through the scheduling process
        after a certain interval. This allows an Application to be rescheduled to a
        more suitable Cluster if a better one is found.

        Args:
            app (krake.data.kubernetes.Application): the Application to reschedule.

        """
        if not app.spec.constraints.migration:
            logger.debug(
                "Not rescheduling %r, since migration of the application is disabled.",
                app,
            )
            return

        # Put the application into the work queue with a certain delay. This
        # ensures the rescheduling of the application. Only put it if there is
        # not already another version of the resource in the queue. This check
        # is needed to ensure that we do not overwrite state changes with the
        # current one which might be outdated.
        if app.metadata.uid not in self.queue.dirty:
            logger.debug("Reschedule %r in %s secs", app, self.reschedule_after)
            await self.queue.put(app.metadata.uid, app, delay=self.reschedule_after)

    async def select_kubernetes_cluster(self, app, clusters):
        """Select suitable kubernetes cluster for application binding.

        Args:
            app (krake.data.kubernetes.Application): Application object for binding
            clusters (list[krake.data.kubernetes.Cluster]): Clusters between which
                the "best" one should be chosen.

        Returns:
            Cluster: Cluster suitable for application binding

        """
        # Reject clusters marked as deleted and clusters that are not online
        existing_clusters = \
            (cluster for cluster in clusters if cluster.metadata.deleted is None
                and cluster.status.state is ClusterState.ONLINE)

        possible_clusters = []

        fetched_metrics = dict()
        for cluster in clusters:
            possible_clusters.append(cluster)
            if cluster.spec.metrics:
                async for metrics in self.fetch_metrics(cluster, cluster.spec.metrics):
                    fetched_metrics[cluster.metadata.name] = metrics

        logger.info(possible_clusters)
        logger.info(fetched_metrics)

        matching = [
            cluster for cluster in existing_clusters
            if match_cluster_constraints(app, cluster, fetched_metrics)
        ]

        logger.info(matching)

        if not matching:
            logger.info("No matching Kubernetes cluster for %r found", app)
            raise NoClusterFound("No matching Kubernetes cluster found")

        # If the application already has been scheduled it might be that it
        # was very recently. In fact, since the controller reacts to all updates
        # of the application, it might very well be that the previous scheduling
        # took place very recently. For example, the kubernetes controller updates
        # the app in reaction to the scheduler's scheduling, in which case
        # the scheduler will try and select the best cluster yet again.
        # Therefore, we have to make sure the previous scheduling was not too recent.
        # If it was, we want to stay at the current cluster - if it is still matching.
        # The above reasoning is also true in the case when the user has performed an
        # update of the application's cluster label constraints. Also in this case, the
        # update should not cause a migration if 'app was `recently scheduled`'
        # and 'current cluster is still matching'. If the app was recently scheduled
        # but the update caused the current cluster to no longer be matching, we
        # will reschedule, since `current` will become None below.
        # If 'app was NOT `recently scheduled`' and 'current cluster is still matching',
        # we might reschedule, e.g., due to changing metrics.
        if app.status.scheduled_to:
            # get current cluster as first cluster in matching to which app is scheduled
            current = next(
                (c for c in matching if resource_ref(c) == app.status.scheduled_to),
                None,
            )
            # if current cluster is still matching
            if current:
                # We check how long ago the previous scheduling took place.
                # If it is less than reschedule_after seconds ago, we do not
                # reschedule. We use reschedule_after for this comparison,
                # since it indicates how often it is desired that an application
                # should be rescheduled when a more appropriate cluster exists.
                time_since_scheduled_to_current = utils.now() - app.status.scheduled
                app_recently_scheduled = time_since_scheduled_to_current < timedelta(
                    seconds=self.reschedule_after
                )
                if app_recently_scheduled:
                    return current

        # Partition list if matching clusters into a list if clusters with
        # metrics and without metrics. Clusters with metrics are preferred
        # over clusters without metrics.
        with_metrics = [cluster for cluster in matching if cluster.spec.metrics]

        # Only use clusters without metrics when there are no clusters with
        # metrics.
        scores = []
        if with_metrics:
            # Compute the score of all clusters based on their metric
            scores = await self.rank_kubernetes_clusters(app, with_metrics)

        if not scores:
            # If no score of cluster with metrics could be computed (e.g. due to
            # unreachable metrics providers), compute the score of the matching clusters
            # that do not have metrics.
            scores = [
                self.calculate_kubernetes_cluster_score((), cluster, app)
                for cluster in matching
            ]

        return self.select_maximum(scores).cluster

    async def rank_kubernetes_clusters(self, app, clusters):
        """Compute the score of the kubernetes clusters based on metrics values and
        weights.

        Args:
            app (krake.data.kubernetes.Application): Application object for binding
            clusters (list[Cluster]): List of clusters for which the score has to be
                computed.

        Returns:
            list[ClusterScore]: list of all cluster's score

        """
        return [
            self.calculate_kubernetes_cluster_score(metrics, cluster, app)
            for cluster in clusters
            async for metrics in self.fetch_metrics(cluster, cluster.spec.metrics)
        ]

    def calculate_kubernetes_cluster_score(self, metrics, cluster, app):
        """Calculate weighted sum of metrics values.

        Args:
            metrics (list[.metrics.QueryResult]): List of metric query results
            cluster (Cluster): cluster for which the score has to be computed.
            app (krake.data.kubernetes.Application): Application object that
                should be scheduled.

        Returns:
            ClusterScore: score of the passed cluster based on metrics and application.

        """
        sticky = self.calculate_kubernetes_cluster_stickiness(cluster, app)

        if not metrics:
            return ClusterScore(score=sticky.weight * sticky.value, cluster=cluster)

        norm = sum(metric.weight for metric in metrics) + sticky.weight
        score = (
            sum(metric.value * metric.weight for metric in metrics)
            + (sticky.value * sticky.weight)
        ) / norm

        return ClusterScore(score=score, cluster=cluster)

    def calculate_kubernetes_cluster_stickiness(self, cluster, app):
        """Return extra metric for clusters to make the application "stick" to
        it by increasing its score.

        If the application is already scheduled to the passed cluster, a
        stickiness of ``1.0`` with a configurable weight is returned.
        Otherwise, a stickiness of ``0`` is returned.

        Args:
            cluster (Cluster): cluster for which the score has to be computed.
            app (krake.data.kubernetes.Application): Application object that
                should be scheduled.

        Returns:
            Stickiness: Value and its weight that should be added to the
            cluster score.

        """
        if resource_ref(cluster) != app.status.scheduled_to:
            return Stickiness(weight=0, value=0)

        return Stickiness(weight=self.stickiness, value=1.0)


class OpenstackHandler(Handler):
    def __init__(self, client, queue, api, core_api):

        super(OpenstackHandler, self).__init__(client, queue, api, core_api)

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
            await self.queue.put(cluster.metadata.uid, cluster)
        else:
            logger.debug("Ignore bound %r", cluster)

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
            key, cluster = await self.queue.get()
            try:
                # TODO: API for supporting different application types
                logger.debug("Handling %r", cluster)
                await self.schedule_magnum_cluster(cluster)
            except ControllerError as error:
                cluster.status.reason = Reason(code=error.code, message=error.message)
                cluster.status.state = MagnumClusterState.FAILED

                await self.api.update_magnum_cluster_status(
                    namespace=cluster.metadata.namespace,
                    name=cluster.metadata.name,
                    body=cluster,
                )
            finally:
                await self.queue.done(key)

            if run_once:
                break

    async def schedule_magnum_cluster(self, cluster):
        """Choose a suitable OpenStack Project for the given MagnumCluster and bound
        them together.

        Args:
            cluster (krake.data.openstack.MagnumCluster): the MagnumCluster that needs
                to be scheduled to a Project.
        """
        assert cluster.status.project is None, "Magnum cluster is already bound"

        logger.info("Schedule %r", cluster)

        projects = await self.api.list_all_projects()
        project = await self.select_openstack_project(cluster, projects.items)

        if project is None:
            logger.info("No matching OpenStack project found for %r", cluster)
            raise NoProjectFound("No matching OpenStack project found")

        # TODO: Instead of copying labels and metrics, refactor the scheduler
        #   to support transitive labels and metrics.
        cluster.metadata.labels = {**project.metadata.labels, **cluster.metadata.labels}

        # If a metric with the same name is already specified in the Magnum
        # cluster spec, this takes precedence.
        metric_names = set(metric.name for metric in cluster.spec.metrics)
        for metric in project.spec.metrics:
            if metric.name not in metric_names:
                cluster.spec.metrics.append(metric)

        await self.api.update_magnum_cluster(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=cluster,
        )

        # TODO: How to support and compare different cluster templates?
        logger.info("Scheduled %r to %r", cluster, project)
        await self.api.update_magnum_cluster_binding(
            namespace=cluster.metadata.namespace,
            name=cluster.metadata.name,
            body=MagnumClusterBinding(
                project=resource_ref(project), template=project.spec.template
            ),
        )

    async def select_openstack_project(self, cluster, projects):
        """Select the "best" OpenStack project for the Magnum cluster.

        Args:
            cluster (krake.data.openstack.MagnumCluster): Cluster that should
                be bound to a project
            projects (list[krake.data.openstack.Project]): Projects between the
                "best" one is chosen.

        Returns:
            krake.data.openstack.Project, None: Best project matching the
            constraints of the Magnum cluster. None if no project can be found.

        """
        # Reject projects marked as deleted
        projects = (project for project in projects if project.metadata.deleted is None)
        matching = [
            project
            for project in projects
            if match_project_constraints(cluster, project)
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
            scores = [
                self.calculate_openstack_project_scores((), project)
                for project in matching
            ]
        else:
            # Compute the score of all projects based on their metric
            scores = await self.rank_openstack_projects(cluster, with_metrics)

        if not scores:
            logger.info("Unable to compute the score of any Kubernetes cluster")
            raise NoProjectFound("No OpenStack project available")

        return self.select_maximum(scores).project

    async def rank_openstack_projects(self, cluster, projects):
        """Compute the score of the OpenStack projects based on metric values and
        weights.

        Args:
            cluster (krake.data.openstack.MagnumCluster): Cluster that is scheduled
            projects (list[Project]): List of projects for which the score has to be
                computed.

        Returns:
            list[ProjectScore]: list of all cluster's score
        """
        return [
            self.calculate_openstack_project_scores(metrics, project)
            for project in projects
            async for metrics in self.fetch_metrics(project, project.spec.metrics)
        ]

    @staticmethod
    def metrics_reason_from_err(error):
        """Convert an error as exception into an instance of :class:`Reason`. Also
        generates an appropriate message if necessary.

        Args:
            error (Exception): error that occurred which has to be converted into a
                reason.

        Returns:
            Reason: reason generated from the provided error.

        """
        message = None
        if isinstance(error, MetricsProviderError):
            reason_code = ReasonCode.UNREACHABLE_METRICS_PROVIDER
        elif isinstance(error, MetricError):
            reason_code = ReasonCode.INVALID_METRIC
        elif isinstance(error, ClientError):
            resource_name = error.request_info.url.path.split("/")[-1]
            if "metricsprovider" in error.request_info.url.path:
                reason_code = ReasonCode.UNKNOWN_METRICS_PROVIDER
                message = (
                    f"The metrics provider {resource_name!r} was not found in the Krake"
                    f" database."
                )
            else:
                reason_code = ReasonCode.UNKNOWN_METRIC
                message = (
                    f"The metric {resource_name!r} was not found in the Krake database."
                )
        else:
            raise error

        final_message = message if message else str(error)
        return Reason(code=reason_code, message=final_message)

    async def update_resource_status(self, resource, metrics, reasons):
        """Update the status of the provided resource with the new list of reasons for
        metrics which failed.

        Args:
            resource (krake.data.serializable.ApiObject): the resource to updated.
            metrics (list[krake.data.core.MetricRef]): the list of metrics for which the
                scheduler attempted to fetch the current value.
            reasons (list[Reason]): the list of reasons for the metrics failing which
                were found. For each metric in the :args:`metrics` argument, there
                should be one element in this argument: the reason for the metric
                failing, or None if it did not fail.

        """
        assert len(metrics) == len(reasons)

        if resource.kind == "Cluster":
            resource.status.state = ClusterState.FAILING_METRICS
            update_status_client = self.api.update_cluster_status
        elif resource.kind == "Project":
            resource.status.state = ProjectState.FAILING_METRICS
            update_status_client = self.api.update_project_status
        else:
            raise ValueError(f"Unsupported kind: {resource.kind}.")

        # Add to resource only if a failure occurred.
        resource.status.metrics_reasons = {}
        for i, reason in enumerate(reasons):
            if reason:
                resource.status.metrics_reasons[metrics[i].name] = reason

        await update_status_client(
            namespace=resource.metadata.namespace,
            name=resource.metadata.name,
            body=resource,
        )

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
            metrics (list[krake.data.core.MetricRef]): References to metrics
                that should be fetched.

        Yields:
            list[krake.controller.scheduler.metrics.QueryResult]: List of fetched
                metrics with their value and weight.

        """
        assert metrics, "Got empty list of metric references"

        errors = []
        reasons = []
        fetching = []
        for metric_spec in metrics:
            try:
                if metric_spec.namespaced:
                    metric = await self.core_api.read_metric(
                        namespace=resource.metadata.namespace,
                        name=metric_spec.name,
                    )
                    metrics_provider = await self.core_api.read_metrics_provider(
                        namespace=resource.metadata.namespace,
                        name=metric.spec.provider.name,
                    )
                else:
                    metric = await self.core_api.read_global_metric(
                        name=metric_spec.name
                    )
                    metrics_provider = await self.core_api.read_global_metrics_provider(
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
                reasons.append(None)  # Add an empty placeholder when no error occurred.
            except ClientError as err:
                reasons.append(self.metrics_reason_from_err(err))
                errors.append(err)

        fetched = await asyncio.gather(*fetching, return_exceptions=True)

        # Convert the errors which occurred when fetching the value of the remaining
        # metrics into Reason instances.
        # For this, the next occurrence of "None" inside the "reasons" list is used.
        # Each one of this occurrence corresponds to a task for fetching the metric. So
        # if for example the 3rd element in "fetched" is an error, the 3rd "None" in
        # "reasons" must be replaced.
        none_reason_iter = (i for i, reason in enumerate(reasons) if reason is None)
        for result in fetched:
            # Get the index of the next "None" inside "reasons".
            index_of_none = next(none_reason_iter)
            if isinstance(result, Exception):
                reasons[index_of_none] = self.metrics_reason_from_err(result)
                errors.append(result)

        stopped = False
        try:
            next(none_reason_iter)
        except StopIteration:
            stopped = True
        assert stopped

        if any(reasons):
            # If there is any issue with a metric, skip stop the generator.
            await self.update_resource_status(resource, metrics, reasons)
            for error in errors:
                if error:
                    logger.error(error)
            return

        for metric, weight, value in fetched:
            logger.debug(
                "Received metric %r with value %r for %r", metric, value, resource
            )

        yield fetched

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

    def calculate_openstack_project_scores(self, metrics, project):
        """Calculate score of OpenStack project based on the given metrics.

        Args:
            metrics (list[krake.controller.scheduler.metrics.QueryResult]): List of
                metric query results.
            project (krake.data.openstack.Project): Project for which the score has to
                be computed.

        Returns:
            ProjectScore: Score of the passed project based on metrics and Magnum
                cluster.

        """
        # Score for a OpenStack project without any metrics
        if not metrics:
            return ProjectScore(score=0, project=project)

        norm = sum(metric.weight for metric in metrics)
        score = sum(metric.value * metric.weight for metric in metrics) / norm

        return ProjectScore(score=score, project=project)
