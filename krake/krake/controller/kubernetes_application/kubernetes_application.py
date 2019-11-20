import logging
import re
from copy import deepcopy
from functools import partial

from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.client import ApiClient, CoreV1Api, AppsV1Api, Configuration
from kubernetes_asyncio.client.rest import ApiException
from typing import NamedTuple, Tuple

from krake.data.core import ReasonCode
from krake.data.kubernetes import ApplicationState
from krake.client.kubernetes import KubernetesApi

from ..exceptions import ControllerError, application_error_mapping
from .. import Controller, Reflector
from .hooks import listen, Hook

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


class ApplicationController(Controller):
    """Controller responsible for :class:`krake.data.kubernetes.Application`
    resources in "SCHEDULED" and "DELETING" state.

    Args:
        worker_count (int, optional): the amount of worker function that should be
            run as background tasks.

    """

    def __init__(
        self,
        api_endpoint,
        worker_count=10,
        loop=None,
        ssl_context=None,
        debounce=0,
        hooks=None,
    ):
        super().__init__(
            api_endpoint, loop=loop, ssl_context=ssl_context, debounce=debounce
        )
        self.kubernetes_api = None
        self.reflector = None
        self.worker_count = worker_count
        self.hooks = hooks

    async def prepare(self, client):
        assert client is not None
        self.client = client
        self.kubernetes_api = KubernetesApi(self.client)

        for i in range(self.worker_count):
            self.register_task(self.handle_resource, name=f"worker_{i}")

        def scheduled_or_deleting(app):
            # Always cleanup deleted applications even if they are in FAILED
            # state.
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

        receive_app = partial(self.simple_on_receive, condition=scheduled_or_deleting)

        self.reflector = Reflector(
            listing=self.kubernetes_api.list_all_applications,
            watching=self.kubernetes_api.watch_all_applications,
            on_list=receive_app,
            on_add=receive_app,
            on_update=receive_app,
        )
        self.register_task(self.reflector, name="Reflector")

    async def cleanup(self):
        self.reflector = None
        self.kubernetes_api = None

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

    async def resource_received(self, app):
        logger.debug("Handle %r", app)

        copy = deepcopy(app)

        if app.metadata.deleted:
            await self._delete_application(copy)
        elif (
            copy.status.running_on
            and copy.status.running_on != copy.status.scheduled_to
        ):
            await self._migrate_application(copy)
        else:
            await self._reconcile_application(copy)

    async def _delete_application(self, app):
        logger.info("Delete %r (%s)", app.metadata.name, app.metadata.namespace)

        # Transition into "DELETING" state
        app.status.state = ApplicationState.DELETING
        await self.kubernetes_api.update_application_status(
            namespace=app.metadata.namespace, name=app.metadata.name, body=app
        )

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
        # cluster and there Kubernetes resources were created.
        if app.status.running_on and app.status.manifest:
            cluster = await self.kubernetes_api.read_cluster(
                namespace=app.status.running_on.namespace,
                name=app.status.running_on.name,
            )
            async with KubernetesClient(cluster.spec.kubeconfig) as kube:
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
        # This will prevent the API from deleting the resource without remove the
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
        async with KubernetesClient(cluster.spec.kubeconfig) as kube:
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


class KubernetesClient(object):
    def __init__(self, kubeconfig):
        self.kubeconfig = kubeconfig
        self.resource_apis = None

    async def __aenter__(self):
        # Load Kubernetes configuration
        loader = KubeConfigLoader(self.kubeconfig)
        config = Configuration()
        await loader.load_and_set(config)

        api_client = ApiClient(config)
        core_v1_api = CoreV1Api(api_client)
        apps_v1_api = AppsV1Api(api_client)

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

    @staticmethod
    def log_resp(resp, kind, action=None):
        resp_log = (
            f"status={resp.status!r}"
            if hasattr(resp, "status")
            else f"resource={resp!r}"
        )
        logger.debug(f"%s {action}. %r", kind, resp_log)

    async def _read(self, kind, name, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"read_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, namespace=namespace)

    async def _create(self, kind, body, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"create_namespaced_{camel_to_snake_case(kind)}")
        return await fn(body=body, namespace=namespace)

    async def _patch(self, kind, name, body, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"patch_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, body=body, namespace=namespace)

    async def _delete(self, kind, name, namespace):
        api = self.resource_apis[kind]
        fn = getattr(api, f"delete_namespaced_{camel_to_snake_case(kind)}")
        return await fn(name=name, namespace=namespace)

    async def apply(self, resource, namespace="default"):
        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidResourceError('Resource must define "kind"')

        if kind not in self.resource_apis:
            raise InvalidResourceError(f"{kind} resources are not supported")

        try:
            name = resource["metadata"]["name"]
        except KeyError:
            raise InvalidResourceError('Resource must define "metadata.name"')

        try:
            resp = await self._read(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status == 404:
                resp = None
            else:
                raise InvalidResourceError(err_resp=err)

        if resp is None:
            resp = await self._create(kind, body=resource, namespace=namespace)
            self.log_resp(resp, kind, action="created")
        else:
            resp = await self._patch(
                kind, name=name, body=resource, namespace=namespace
            )
            self.log_resp(resp, kind, action="patched")

        return resp

    async def delete(self, resource, namespace="default"):
        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidResourceError('Resource must define "kind"')

        if kind not in self.resource_apis:
            raise InvalidResourceError(f"{kind} resources are not supported")

        try:
            name = resource["metadata"]["name"]
        except KeyError:
            raise InvalidResourceError('Resource must define "metadata.name"')

        try:
            resp = await self._delete(kind, name=name, namespace=namespace)
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
