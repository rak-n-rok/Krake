import asyncio
import logging
from contextlib import suppress
from copy import deepcopy
from datetime import datetime
from functools import partial

from aiohttp import ClientResponseError
from krake.controller.kubernetes.client import KubernetesClient
from kubernetes_asyncio.client.rest import ApiException
from typing import NamedTuple, Tuple

from .hooks import listen, Hook
from krake.client.kubernetes import KubernetesApi
from krake.controller import Controller, Reflector, ControllerError
from krake.controller.kubernetes.hooks import register_observer, unregister_observer
from krake.data.core import ReasonCode, resource_ref, Reason
from krake.data.kubernetes import ApplicationState


logger = logging.getLogger(__name__)


class InvalidStateError(ControllerError):
    """Kubernetes application is in an invalid state"""

    code = ReasonCode.INTERNAL_ERROR


class ResourceID(NamedTuple):
    """Named tuple for identifying Kubernetes resource objects by their API
    version, kind, namespace and name.
    """

    api_version: str
    kind: str
    name: str
    namespace: str

    @classmethod
    def from_resource(cls, resource):
        """Create an identifier for the given Kubernetes resource object.

        Args:
            resource (dict): Kubernetes resource object

        Returns:
            ResourceID: Identifier for the given resource object

        """
        return cls(
            api_version=resource["apiVersion"],
            kind=resource["kind"],
            name=resource["metadata"]["name"],
            namespace=resource["metadata"].get("namespace"),
        )


class ResourceDelta(NamedTuple):
    """Description of the difference between the resource of two Kubernetes
    application.

    Resources are identified by :class:`ResourceID`. Resources with the same
    ID will be compared by their content.

    Attributes:
        new (Tuple[dict, ...]): Resources that are new in the specification
            and not in the status.
        deleted (Tuple[dict, ...]): Resources that are not in the
            specification but in the status.
        modified (Tuple[dict, ...]): Resources that are in the specification
            and the status but the resource content differs.

    """

    new: Tuple[dict, ...]
    deleted: Tuple[dict, ...]
    modified: Tuple[dict, ...]

    @classmethod
    def calculate(cls, app):
        """Calculate the difference between the resources in the specification
        and the status of the given application.

        Args:
            app (krake.data.kubernetes.Application): Kubernetes application

        Returns:
            ResourceDelta: Difference in resources between specification and
            status.

        """
        desired = {
            ResourceID.from_resource(resource): resource
            for resource in app.status.mangling
        }
        current = {
            ResourceID.from_resource(resource): resource
            for resource in (app.status.manifest or [])
        }

        deleted = [current[rid] for rid in set(current) - set(desired)]

        new = [desired[rid] for rid in set(desired) - set(current)]

        modified = [
            desired[rid]
            for rid in set(desired) & set(current)
            if desired[rid]["spec"] != current[rid]["spec"]
        ]

        return cls(new=tuple(new), deleted=tuple(deleted), modified=tuple(modified))

    def __bool__(self):
        return any([self.new, self.deleted, self.modified])


class KubernetesController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in "SCHEDULED" and "DELETING" state.

    Args:
        worker_count (int, optional): the amount of worker function that should be
            run as background tasks.
        time_step (float, optional): for the Observers: the number of seconds between
            two observations of the actual resource.

    """

    def __init__(
        self,
        api_endpoint,
        worker_count=10,
        loop=None,
        ssl_context=None,
        debounce=0,
        hooks=None,
        time_step=2,
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.kubernetes_api = None
        self.reflector = None

        self.worker_count = worker_count
        self.hooks = hooks

        self.observer_time_step = time_step
        self.observers = {}

    @staticmethod
    def scheduled_or_deleting(app):
        """Check if a resource should be accepted or not by the Controller to be
        handled.

        Args:
            app (krake.data.kubernetes.Application): the Application to check.

        Returns:
            bool: True if the Application should be handled, False otherwise.

        """
        # Always cleanup deleted applications even if they are in FAILED state.
        if app.metadata.deleted:
            if (
                app.metadata.finalizers
                and app.metadata.finalizers[-1] == "kubernetes_resources_deletion"
            ):
                logger.debug("Accept deleted %r", app)
                return True

            logger.debug("Reject deleted %r without finalizer", app)
            return False

        # Ignore all other failed application
        if app.status.state == ApplicationState.FAILED:
            logger.debug("Reject failed %r", app)
            return False

        # Accept only scheduled applications. Forces the Applications to be first
        # handled by the Scheduler, before the KubernetesController applies its
        # decision.
        if (
            app.status.kube_controller_triggered
            and app.status.kube_controller_triggered >= app.metadata.modified
        ):
            logger.debug("Accept scheduled %r", app)
            return True

        logger.debug("Reject %r", app)
        return False

    async def list_app(self, app):
        """Accept the Applications that need to be managed by the Controller on listing
        them at startup. Starts the observer for the Applications with actual resources.

        Args:
            app (krake.data.kubernetes.Application): the Application to accept or not.

        """
        if app.status.running_on:
            if app.metadata.uid in self.observers:
                # If an observer was started before, stop it
                await unregister_observer(self, app)
            # Start an observer only if an actual resource exists on a cluster
            await register_observer(self, app)

        await self.simple_on_receive(app, self.scheduled_or_deleting)

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.kubernetes_api = KubernetesApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        receive_app = partial(
            self.simple_on_receive, condition=self.scheduled_or_deleting
        )

        self.reflector = Reflector(
            listing=self.kubernetes_api.list_all_applications,
            watching=self.kubernetes_api.watch_all_applications,
            on_list=self.list_app,
            on_add=receive_app,
            on_update=receive_app,
            resource_plural="Kubernetes Applications",
        )
        self.register_task(self.reflector, name="Reflector")

    async def cleanup(self):
        self.reflector = None
        self.kubernetes_api = None

        # Stop the observers
        for _, task in self.observers.values():
            task.cancel()

        for _, task in self.observers.values():
            with suppress(asyncio.CancelledError):
                await task

        self.observers = {}

    async def on_status_update(self, app):
        """Called when an Observer noticed a difference of the status of an Application.
        Request an update of the status on the API.

        Args:
            app (krake.data.kubernetes.Application): the Application whose status has
                been updated.

        Returns:
            krake.data.kubernetes.Application: the updated Application sent by the API.

        """
        logger.error("resource %s is different", resource_ref(app))

        # The Application needs to be processed (thus accepted) by the Kubernetes
        # Controller
        app.status.kube_controller_triggered = datetime.now()
        assert app.metadata.modified is not None

        app = await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )
        return app

    async def handle_resource(self, run_once=False):
        """Infinite loop which fetches and hand over the resources to the right
        coroutine. The specific exceptions and error handling have to be added here.

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
                await self.resource_received(app)
            except ApiException as error:
                app.status.reason = Reason(
                    code=ReasonCode.KUBERNETES_ERROR, message=str(error)
                )
                app.status.state = ApplicationState.FAILED

                await self.kubernetes_api.update_application_status(
                    namespace=app.metadata.namespace, name=app.metadata.name, body=app
                )
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

    async def resource_received(self, app, start_observer=True):
        logger.debug("Handle %r", app)

        copy = deepcopy(app)

        if app.metadata.deleted:
            # Delete the Application
            await listen.hook(
                Hook.ApplicationPreDelete,
                controller=self,
                app=copy,
                start=start_observer,
            )
            await self._delete_application(copy)
            await listen.hook(
                Hook.ApplicationPostDelete,
                controller=self,
                app=copy,
                start=start_observer,
            )
        elif (
            copy.status.running_on
            and copy.status.running_on != copy.status.scheduled_to
        ):
            # Migrate the Application
            await listen.hook(
                Hook.ApplicationPreMigrate,
                controller=self,
                app=copy,
                start=start_observer,
            )
            await self._migrate_application(copy)
            await listen.hook(
                Hook.ApplicationPostMigrate,
                controller=self,
                app=copy,
                start=start_observer,
            )
        else:
            # Reconcile the Application
            await listen.hook(
                Hook.ApplicationPreReconcile,
                controller=self,
                app=copy,
                start=start_observer,
            )
            await self._reconcile_application(copy)
            await listen.hook(
                Hook.ApplicationPostReconcile,
                controller=self,
                app=copy,
                start=start_observer,
            )

    async def _delete_application(self, app):
        # FIXME: during its deletion, an Application is updated, and thus put into the
        #  queue again on the controller to be deleted. After deletion, the Application
        #  is released from the active resources of the queue, and the updated resource
        #  is handled again. However, there are no actual resource anymore, as they have
        #  been deleted. To prevent this, the worker verifies that the Application is
        #  not deleted yet before attempting to delete it.
        try:
            # Transition into "DELETING" state
            app.status.state = ApplicationState.DELETING
            await self.kubernetes_api.update_application_status(
                namespace=app.metadata.namespace, name=app.metadata.name, body=app
            )
        except ClientResponseError as err:
            if err.status == 404:
                return
            raise

        logger.info("Delete %r (%s)", app.metadata.name, app.metadata.namespace)

        await self._delete_manifest(app)

        # Remove finalizer
        finalizer = app.metadata.finalizers.pop(-1)
        assert finalizer == "kubernetes_resources_deletion"

        # Save status changes
        await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

        # Update owners and finalizers
        await self.kubernetes_api.update_application(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

    async def _delete_manifest(self, app):
        # Delete Kubernetes resources if the application was bound to a
        # cluster and there were Kubernetes resources created.
        if app.status.running_on and app.status.manifest:
            cluster = await self.kubernetes_api.read_cluster(
                namespace=app.status.running_on.namespace,
                name=app.status.running_on.name,
            )
            async with KubernetesClient(
                cluster.spec.kubeconfig, cluster.spec.custom_resources
            ) as kube:
                for resource in app.status.manifest:
                    await listen.hook(
                        Hook.ResourcePreDelete,
                        app=app,
                        cluster=cluster,
                        resource=resource,
                        controller=self,
                    )
                    resp = await kube.delete(resource)
                    await listen.hook(
                        Hook.ResourcePostDelete,
                        app=app,
                        cluster=cluster,
                        resource=resource,
                        response=resp,
                    )

        if app.status.running_on:
            app.metadata.owners.remove(app.status.running_on)

        # Clear manifest in status
        app.status.manifest = None
        app.status.mangling = None
        app.status.running_on = None

    async def _reconcile_application(self, app):
        if not app.status.scheduled_to:
            raise InvalidStateError(
                "Application is scheduled but no cluster is assigned"
            )

        # Mangle desired spec resource by Mangling hook
        app.status.mangling = deepcopy(app.spec.manifest)
        await listen.hook(
            Hook.ApplicationMangling,
            app=app,
            api_endpoint=self.api_endpoint,
            ssl_context=self.ssl_context,
            config=self.hooks,
        )

        delta = ResourceDelta.calculate(app)

        if not delta:
            logger.info(
                "%r (%s) is up-to-date", app.metadata.name, app.metadata.namespace
            )
            return

        logger.info("Reconcile %r", app)

        # Ensure finalizer exists before changing Kubernetes objects
        await self._ensure_finalizer(app)

        if not app.status.running_on:
            # Transition into "CREATING" state if the application is currently
            # not running on any cluster.
            app.status.state = ApplicationState.CREATING
        else:
            # Transition into "RECONCILING" state if application is already
            # running.
            app.status.state = ApplicationState.RECONCILING

        await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

        await self._apply_manifest(app, delta)

        # Transition into "RUNNING" state
        app.status.state = ApplicationState.RUNNING
        await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

        logger.info(
            "Reconciliation finished %r (%s)", app.metadata.name, app.metadata.namespace
        )

    async def _apply_manifest(self, app, delta):
        # Append "kubernetes_resources_deletion" finalizer if not already present.
        # This will prevent the API from deleting the resource without removing the
        # Kubernetes resources.
        if "kubernetes_resources_deletion" not in app.metadata.finalizers:
            app.metadata.finalizers.append("kubernetes_resources_deletion")
            await self.kubernetes_api.update_application(
                namespace=app.metadata.namespace, name=app.metadata.name, body=app
            )

        cluster = await self.kubernetes_api.read_cluster(
            namespace=app.status.scheduled_to.namespace,
            name=app.status.scheduled_to.name,
        )
        async with KubernetesClient(
            cluster.spec.kubeconfig, cluster.spec.custom_resources
        ) as kube:
            # Delete all resources that are no longer in the spec
            for deleted in delta.deleted:
                await listen.hook(
                    Hook.ResourcePreDelete,
                    app=app,
                    cluster=cluster,
                    resource=deleted,
                    controller=self,
                )
                resp = await kube.delete(deleted)
                await listen.hook(
                    Hook.ResourcePostDelete,
                    app=app,
                    cluster=cluster,
                    resource=deleted,
                    response=resp,
                )

            # Create new resource
            for new in delta.new:
                await listen.hook(
                    Hook.ResourcePreCreate,
                    app=app,
                    cluster=cluster,
                    resource=new,
                    controller=self,
                )
                resp = await kube.apply(new)
                await listen.hook(
                    Hook.ResourcePostCreate,
                    app=app,
                    cluster=cluster,
                    resource=new,
                    response=resp,
                )

            # Update modified resource
            for modified in delta.modified:
                await listen.hook(
                    Hook.ResourcePreUpdate,
                    app=app,
                    cluster=cluster,
                    resource=modified,
                    controller=self,
                )
                resp = await kube.apply(modified)
                await listen.hook(
                    Hook.ResourcePostUpdate,
                    app=app,
                    cluster=cluster,
                    resource=modified,
                    response=resp,
                )

        # Update resource in application status
        app.status.manifest = deepcopy(app.status.mangling)

        # Application is now running on the scheduled cluster
        app.status.running_on = app.status.scheduled_to

    async def _migrate_application(self, app):
        logger.info(
            "Migrate %r from %r to %r",
            app,
            app.status.running_on,
            app.status.scheduled_to,
        )

        # Ensure finalizer exists before changing Kubernetes objects
        await self._ensure_finalizer(app)

        # Transition into "MIGRATING" state
        app.status.state = ApplicationState.MIGRATING

        await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

        # Delete all resources currently running on the old cluster
        await self._delete_manifest(app)

        # Mangle desired spec resource by Mangling hook
        app.status.mangling = deepcopy(app.spec.manifest)
        await listen.hook(
            Hook.ApplicationMangling,
            app=app,
            api_endpoint=self.api_endpoint,
            ssl_context=self.ssl_context,
            config=self.hooks,
        )
        # Create complete manifest on the new cluster
        delta = ResourceDelta(new=tuple(app.status.mangling), modified=(), deleted=())
        await self._apply_manifest(app, delta)

        # Update resource in application status
        app.status.manifest = deepcopy(app.status.mangling)

        # Transition into "RUNNING" state
        app.status.state = ApplicationState.RUNNING
        await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )
        # Update owners
        await self.kubernetes_api.update_application(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

        logger.info("Migration of %r finished", app)

    async def _ensure_finalizer(self, app):
        # Append "kubernetes_resources_deletion" finalizer if not already present.
        # This will prevent the API from deleting the resource without removing the
        # Kubernetes resources.
        if "kubernetes_resources_deletion" not in app.metadata.finalizers:
            app.metadata.finalizers.append("kubernetes_resources_deletion")
            await self.kubernetes_api.update_application(
                namespace=app.metadata.namespace, name=app.metadata.name, body=app
            )
