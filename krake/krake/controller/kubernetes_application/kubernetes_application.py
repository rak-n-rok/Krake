import asyncio
import logging
import re
from contextlib import suppress
from copy import deepcopy
from datetime import datetime
from functools import partial

from aiohttp import ClientResponseError
from cached_property import cached_property

from krake.controller import Observer, Controller, Reflector
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.client import (
    ApiClient,
    CoreV1Api,
    AppsV1Api,
    Configuration,
    ApiextensionsV1beta1Api,
    CustomObjectsApi,
    V1DeleteOptions,
)
from kubernetes_asyncio.client.rest import ApiException
from typing import NamedTuple, Tuple

from ..exceptions import ControllerError, application_error_mapping
from .hooks import listen, Hook
from krake.data.core import ReasonCode, resource_ref
from krake.data.kubernetes import ApplicationState
from krake.client.kubernetes import KubernetesApi


logger = logging.getLogger(__name__)


class InvalidResourceError(ControllerError):
    """Raised in case of invalid kubernetes resource definition."""

    code = ReasonCode.INVALID_RESOURCE


class InvalidStateError(ControllerError):
    """Kubernetes application is in an invalid state"""


class ResourceID(NamedTuple):
    """Named tuple for identifying Kubernetes resource objects by their API
    version, kind and name.
    """

    api_version: str
    kind: str
    name: str

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


class KubernetesObserver(Observer):
    """Observer specific for Kubernetes Applications. One observer is created for each
    Application managed by the Controller, but not one per Kubernetes resource
    (Deployment, Service...). If several resources are defined by an Application, they
    are all monitored by the same observer.

    The observer gets the actual status of the resources on the cluster using the
    Kubernetes API, and compare it to the status stored in the API.

    The observer is:
     * started at initial Krake resource creation;

     * deleted when a resource needs to be updated, then started again when it is done;

     * simply deleted on resource deletion.

    Args:
        cluster (krake.data.kubernetes.Cluster): the cluster on which the observed
            Application is created.
        resource (krake.data.kubernetes.Application): the application that will be
            observed
        on_res_update (coroutine): a coroutine called when a resource's actual status
            differs from the status sent by the database. Its signature is:
            ``(resource) -> updated_resource``. ``updated_resource`` is the instance of
            the resource that is up-to-date with the API. The Observer internal instance
            of the resource to observe will be updated. If the API cannot be contacted,
            ``None`` can be returned. In this case the internal instance of the Observer
            will not be updated.
        time_step (int, optional): how frequently the Observer should watch the actual
            status of the resources.

    """

    def __init__(self, cluster, resource, on_res_update, time_step=2):
        super().__init__(resource, on_res_update, time_step)
        self.cluster = cluster

    async def poll_resource(self):
        """Fetch the current status of the Application monitored by the Observer.

        Returns:
            krake.data.core.Status: the status object created using information from the
                real world Applications resource.

        """
        app = self.resource

        status = deepcopy(app.status)
        status.manifest = []

        # For each kubernetes resource of the Application,
        # get its current status on the cluster.
        for resource in app.status.manifest:
            async with KubernetesClient(self.cluster.spec.kubeconfig) as kube:
                try:
                    resource_api = await kube.get_resource_api(resource["kind"])
                    resp = await resource_api.read(
                        resource["kind"], resource["metadata"]["name"], "default"
                    )
                except ApiException as err:
                    if err.status == 404:
                        # Resource does not exist
                        continue
                    # Otherwise, log the unexpected errors
                    logger.error(err)

            # Update the status with the information taken from the resource on the
            # cluster
            actual_manifest = merge_status(resource, resp.to_dict())
            status.manifest.append(actual_manifest)

        return status


def merge_status(orig, new):
    """Update recursively all elements not present in an original dictionary from a
    newer one. It does not modify the two given dictionaries, but creates a new one.

    If the new dictionary has keys not present in the original, they will not be copied.

    List elements are replaced by the newer if the length differ. Otherwise, all element
    of the list will be compared recursively.

    Args:
        orig (dict): the dictionary that will be updated.
        new (dict): the dictionary that contains the new values, used to update
            :attr:`orig`.

    Returns:
        dict: newly created dictionary that is the merge of the new dictionary in the
            original.

    """
    # If the value to merge is a simple variable (str, int...),
    # just return the updated value.
    if type(orig) is not dict:
        return new

    result = {}
    for key, value in orig.items():
        # Go through dictionaries recursively
        if type(value) is dict:
            new_value = new.get(key, {})
            assert type(new_value) is dict
            result[key] = merge_status(value, new_value)

        elif type(value) is list:
            new_value = new.get(key, [])
            # Replace the list with the newest if the length is different
            if len(value) != len(new_value):
                result[key] = new_value
            else:
                # Otherwise, update elements of the list with the new values
                new_list = []
                for orig_elt, new_elt in zip(value, new_value):
                    merged_elt = merge_status(orig_elt, new_elt)
                    new_list.append(merged_elt)

                result[key] = new_list

        else:
            # Update with value from new dictionary, or use original as default
            result[key] = new.get(key, value)

    return result


class ApplicationController(Controller):
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

        # Accept scheduled applications
        if app.status.scheduled and app.status.scheduled >= app.metadata.modified:
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
                await self.unregister_observer(app)
            # Start an observer only if an actual resource exists on a cluster
            await self.register_observer(app)

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
        app.status.scheduled = datetime.now()
        assert app.metadata.modified is not None

        app = await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )
        return app

    async def register_observer(self, app, start=True):
        """Create an observer for the given Application, and start it as background
        task if wanted.

        If an observer already existed for this Application, it is stopped and deleted.

        Args:
            app (krake.data.kubernetes.Application): the Application to observe
            start (bool, optional): if False, does not start the observer as background
                task.

        """
        cluster = await self.kubernetes_api.read_cluster(
            namespace=app.status.running_on.namespace, name=app.status.running_on.name
        )
        observer = KubernetesObserver(
            cluster, app, self.on_status_update, time_step=self.observer_time_step
        )

        logger.debug("Start observer for %r", app)
        task = None
        if start:
            task = self.loop.create_task(observer.run())

        self.observers[app.metadata.uid] = (observer, task)

    async def unregister_observer(self, app):
        """Stop and delete the observer for the given Application. If no observer is
        started, do nothing.

        Args:
            app (krake.data.kubernetes.Application): the Application whose observer will
                be stopped.

        """
        if app.metadata.uid not in self.observers:
            return

        logger.debug("Stop observer for %r", app)
        _, task = self.observers.pop(app.metadata.uid)
        task.cancel()

        with suppress(asyncio.CancelledError):
            await task

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
                logger.debug("Handling application %r", app)
                await self.resource_received(app)
            except ControllerError as err:
                await self.error_handler(app, error=err)
            finally:
                await self.queue.done(key)
            if run_once:
                break  # TODO: should we keep this? Only useful for tests

    async def resource_received(self, app, start_observer=True):
        logger.debug("Handle %r", app)

        await self.unregister_observer(app)
        need_to_register = True
        copy = deepcopy(app)

        if app.metadata.deleted:
            await self._delete_application(copy)
            need_to_register = False
        elif (
            copy.status.running_on
            and copy.status.running_on != copy.status.scheduled_to
        ):
            await self._migrate_application(copy)
        else:
            await self._reconcile_application(copy)

        if need_to_register:
            await self.register_observer(copy, start=start_observer)

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
                        Hook.PreDelete,
                        app=app,
                        cluster=cluster,
                        resource=resource,
                        controller=self,
                    )
                    resp = await kube.delete(resource)
                    await listen.hook(
                        Hook.PostDelete,
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
            Hook.Mangling,
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
                    Hook.PreDelete,
                    app=app,
                    cluster=cluster,
                    resource=deleted,
                    controller=self,
                )
                resp = await kube.delete(deleted)
                await listen.hook(
                    Hook.PostDelete,
                    app=app,
                    cluster=cluster,
                    resource=deleted,
                    response=resp,
                )

            # Create new resource
            for new in delta.new:
                await listen.hook(
                    Hook.PreCreate,
                    app=app,
                    cluster=cluster,
                    resource=new,
                    controller=self,
                )
                resp = await kube.apply(new)
                await listen.hook(
                    Hook.PostCreate,
                    app=app,
                    cluster=cluster,
                    resource=new,
                    response=resp,
                )

            # Update modified resource
            for modified in delta.modified:
                await listen.hook(
                    Hook.PreUpdate,
                    app=app,
                    cluster=cluster,
                    resource=modified,
                    controller=self,
                )
                resp = await kube.apply(modified)
                await listen.hook(
                    Hook.PostUpdate,
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
            Hook.Mangling,
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

    async def error_handler(self, app, error=None):
        """Asynchronous callback executed whenever an error occurs during
        :meth:`resource_received`.

        Callback updates kubernetes application status to the failed state and
        describes the reason of the failure.

        Args:
            app (krake.data.kubernetes.Application): Application object processed
                when the error occurred
            error (Exception, optional): The exception whose reason will be propagated
                to the end-user. Defaults to None.
        """
        reason = application_error_mapping(app.status.state, app.status.reason, error)
        app.status.reason = reason

        # If an important error occurred, simply delete the Application
        if reason.code.value >= 100:
            app.status.state = ApplicationState.DELETING
        else:
            app.status.state = ApplicationState.FAILED

        await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )


class ApiAdapter(object):
    """An adapter that provides functionality for calling
    CRUD on multiple Kubernetes resources.

    An appropriate method from Kubernetes api client is selected
    based on resource kind definition.

    Args:
        api (object): Kubernetes api client

    """

    def __init__(self, api):
        self.api = api

    async def read(self, kind, name=None, namespace=None):
        fn = getattr(self.api, f"read_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, namespace=namespace)

    async def create(self, kind, body=None, namespace=None):
        fn = getattr(self.api, f"create_namespaced_{camel_to_snake_case(kind)}")
        return await fn(body=body, namespace=namespace)

    async def patch(self, kind, name=None, body=None, namespace=None):
        fn = getattr(self.api, f"patch_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, body=body, namespace=namespace)

    async def delete(self, kind, name=None, namespace=None):
        fn = getattr(self.api, f"delete_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, namespace=namespace)


class ApiAdapterCustom(object):
    """An adapter that provides functionality for calling
    CRUD on multiple Kubernetes custom resources.

    An appropriate method from Kubernetes custom resources
    api client is selected based on custom resource kind
    and resource scope which is determined from custom resource
    definition.

    Args:
        api (CustomObjectsApi): Kubernetes custom resources api client
        scope (str): Scope indicates whether the custom resource
            is cluster or namespace scoped
        group (str): Group the custom resource belongs in
        version (str): Api version the custom resource belongs in
        plural (str):  Plural name of the custom resource

    """

    def __init__(self, api, scope, group, version, plural):
        self.api = api
        self.scope = scope
        self.group = group
        self.version = version
        self.plural = plural

    async def read(self, kind, name=None, namespace=None):
        if self.scope == "Namespaced":
            return await self.api.get_namespaced_custom_object(
                self.group, self.version, namespace, self.plural, name
            )
        return await self.api.get_cluster_custom_object(
            self.group, self.version, self.plural, name
        )

    async def create(self, kind, body=None, namespace=None):
        if self.scope == "Namespaced":
            return await self.api.create_namespaced_custom_object(
                self.group, self.version, namespace, self.plural, body
            )
        return await self.api.create_cluster_custom_object(
            self.group, self.version, self.plural, body
        )

    async def patch(self, kind, name=None, body=None, namespace=None):
        if self.scope == "Namespaced":
            return await self.api.patch_namespaced_custom_object(
                self.group, self.version, namespace, self.plural, name, body
            )
        return await self.api.patch_cluster_custom_object(
            self.group, self.version, self.plural, name, body
        )

    async def delete(self, kind, name=None, namespace=None):
        body = V1DeleteOptions()

        if self.scope == "Namespaced":
            return await self.api.delete_namespaced_custom_object(
                self.group, self.version, namespace, self.plural, name, body
            )
        return await self.api.delete_cluster_custom_object(
            self.group, self.version, self.plural, name, body
        )


class KubernetesClient(object):
    def __init__(self, kubeconfig, custom_resources=None):
        self.kubeconfig = kubeconfig
        self.custom_resources = custom_resources
        self.resource_apis = None
        self.api_client = None

    @staticmethod
    def log_resp(resp, kind, action=None):
        resp_log = (
            f"status={resp.status!r}"
            if hasattr(resp, "status")
            else f"resource={resp!r}"
        )
        logger.debug(f"%s {action}. %r", kind, resp_log)

    async def __aenter__(self):
        # Load Kubernetes configuration
        loader = KubeConfigLoader(self.kubeconfig)
        config = Configuration()
        await loader.load_and_set(config)

        self.api_client = ApiClient(config)
        core_v1_api = ApiAdapter(CoreV1Api(self.api_client))
        apps_v1_api = ApiAdapter(AppsV1Api(self.api_client))

        self.resource_apis = {
            "ConfigMap": core_v1_api,
            "Deployment": apps_v1_api,
            "Endpoints": core_v1_api,
            "Event": core_v1_api,
            "LimitRange": core_v1_api,
            "PersistentVolumeClaim": core_v1_api,
            "PersistentVolumeClaimStatus": core_v1_api,
            "Pod": core_v1_api,
            "PodLog": core_v1_api,
            "PodStatus": core_v1_api,
            "PodTemplate": core_v1_api,
            "ReplicationController": core_v1_api,
            "ReplicationControllerScale": core_v1_api,
            "ReplicationControllerStatus": core_v1_api,
            "ResourceQuota": core_v1_api,
            "ResourceQuotaStatus": core_v1_api,
            "Secret": core_v1_api,
            "Service": core_v1_api,
            "ServiceAccount": core_v1_api,
            "ServiceStatus": core_v1_api,
        }

        return self

    async def __aexit__(self, *exec):
        self.resource_apis = None
        self.api_client = None

    @cached_property
    async def custom_resource_apis(self):
        """Determine custom resource apis for given cluster.

        If given cluster supports custom resources, Krake determines
        apis from custom resource definitions.

        The custom resources apis are requested only once and then
        are cached by cached property decorator. This is an advantage in
        case of multiple Kubernetes custom resources.

        Raises:
            InvalidResourceError: If the request for the custom resource
            definition failed.

        Returns:
            dict: Custom resource apis

        """
        custom_resource_apis = {}

        if not self.custom_resources:
            return custom_resource_apis

        extensions_v1_api = ApiextensionsV1beta1Api(self.api_client)
        for custom_resource in self.custom_resources:

            try:
                # Determine scope, version, group and plural of custom resource
                # definition
                resp = await extensions_v1_api.read_custom_resource_definition(
                    custom_resource
                )
            except ApiException as err:
                raise InvalidResourceError(err_resp=err)

            # Custom resource api version should be always first item in versions
            # field
            version = resp.spec.versions[0].name
            kind = resp.spec.names.kind

            custom_resource_apis[kind] = ApiAdapterCustom(
                CustomObjectsApi(self.api_client),
                resp.spec.scope,
                resp.spec.group,
                version,
                resp.spec.names.plural,
            )
        return custom_resource_apis

    async def get_resource_api(self, kind):
        """Get the Kubernetes API corresponding to the given kind from the supported
        Kubernetes resources. If not found, look for it into the supported custom
        resources for the cluster.

        Args:
            kind (str): name of the Kubernetes resource, for which the Kubernetes API
                should be retrieved.

        Returns:
            ApiAdapter: the API adapter to use for this resource.

        Raises:
            InvalidResourceError: if the kind given is not supported by the Controller,
                and is not a supported custom resource.

        """
        try:
            resource_api = self.resource_apis[kind]
        except KeyError:
            try:
                custom_resource_apis = await self.custom_resource_apis
                resource_api = custom_resource_apis[kind]
            except KeyError:
                raise InvalidResourceError(f"{kind} resources are not supported")

        return resource_api

    async def apply(self, resource, namespace="default"):
        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidResourceError('Resource must define "kind"')

        resource_api = await self.get_resource_api(kind)

        try:
            name = resource["metadata"]["name"]
        except KeyError:
            raise InvalidResourceError('Resource must define "metadata.name"')

        try:
            resp = await resource_api.read(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status == 404:
                resp = None
            else:
                raise InvalidResourceError(err_resp=err)

        if resp is None:
            resp = await resource_api.create(kind, body=resource, namespace=namespace)
            self.log_resp(resp, kind, action="created")
        else:
            resp = await resource_api.patch(
                kind, name=name, body=resource, namespace=namespace
            )
            self.log_resp(resp, kind, action="patched")

        return resp

    async def delete(self, resource, namespace="default"):
        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidResourceError('Resource must define "kind"')

        resource_api = await self.get_resource_api(kind)

        try:
            name = resource["metadata"]["name"]
        except KeyError:
            raise InvalidResourceError('Resource must define "metadata.name"')

        try:
            resp = await resource_api.delete(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status == 404:
                logger.debug("%s already deleted", kind)
                return
            raise InvalidResourceError(err_resp=err)

        self.log_resp(resp, kind, action="deleted")

        return resp


def camel_to_snake_case(name):
    """Converts camelCase to the snake_case

    Args:
        name (str): Camel case name

    Returns:
        str: Name in snake case

    """
    cunder = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", cunder).lower()
