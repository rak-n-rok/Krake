"""This module defines the Hook Dispatcher and listeners for registering and
executing hooks. Hook Dispatcher emits hooks based on :class:`Hook` attributes which
define when the hook will be executed.

"""
import asyncio
import logging
import os
from collections import defaultdict
from contextlib import suppress
from copy import deepcopy
from functools import reduce
from operator import getitem
from enum import Enum, auto
from inspect import iscoroutinefunction
from typing import NamedTuple

import OpenSSL
import yarl
from krake.controller import Observer, ControllerError
from kubernetes_asyncio.client.rest import ApiException
from yarl import URL
from secrets import token_urlsafe

from kubernetes_asyncio.client import (
    Configuration,
    V1ConfigMap,
    V1EnvVar,
    V1VolumeMount,
    V1Volume,
)
from kubernetes_asyncio.config.kube_config import KubeConfigLoader

from krake.data.core import ReasonCode

from krake.data.kubernetes import ResourceVersion

logger = logging.getLogger(__name__)


class InvalidResourceError(ControllerError):
    """Raised in case of invalid kubernetes resource definition."""

    code = ReasonCode.INVALID_RESOURCE


class Hook(Enum):
    ResourcePreCreate = auto()
    ResourcePostCreate = auto()
    ResourcePreUpdate = auto()
    ResourcePostUpdate = auto()
    ResourcePreDelete = auto()
    ResourcePostDelete = auto()
    ApplicationMangling = auto()
    ApplicationPreMigrate = auto()
    ApplicationPostMigrate = auto()
    ApplicationPreReconcile = auto()
    ApplicationPostReconcile = auto()
    ApplicationPreDelete = auto()
    ApplicationPostDelete = auto()


class HookDispatcher(object):
    """Simple wrapper around a registry of handlers associated to :class:`Hook`
     attributes. Each :class:`Hook` attribute defines when the handler will be
     executed.

    Listeners for certain hooks can be registered via :meth:`on`. Registered
    listeners are executed via :meth:`hook`.

    Example:
        .. code:: python

        listen = HookDispatcher()

        @listen.on(Hook.PreApply)
        def to_perform_before_app_creation(app, cluster, resource, controller):
            # Do Stuff

        @listen.on(Hook.PostApply)
        def another_to_perform_after_app_creation(app, cluster, resource, resp):
            # Do Stuff

        @listen.on(Hook.PostDelete)
        def to_perform_after_app_deletion(app, cluster, resource, resp):
            # Do Stuff

    """

    def __init__(self):
        self.registry = defaultdict(list)

    def on(self, hook):
        """Decorator function to add a new handler to the registry.

        Args:
            hook (Hook): Hook attribute for which to register the handler.

        Returns:
            callable: Decorator for registering listeners for the specified
            hook.

        """

        def decorator(handler):
            self.registry[hook].append(handler)

            return handler

        return decorator

    async def hook(self, hook, **kwargs):
        """ Execute the list of handlers associated to the provided :class:`Hook`
        attribute.

        Args:
            hook (Hook): Hook attribute for which to execute handlers.

        """
        try:
            handlers = self.registry[hook]
        except KeyError:
            pass
        else:
            for handler in handlers:
                if iscoroutinefunction(handler):
                    await handler(**kwargs)
                else:
                    handler(**kwargs)


listen = HookDispatcher()


@listen.on(Hook.ResourcePostCreate)
@listen.on(Hook.ResourcePostUpdate)
async def register_service(app, cluster, resource, response):
    """Register endpoint of Kubernetes Service object on creation and update.

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        cluster (krake.data.kubernetes.Cluster): The cluster on which the
            application is running
        resource (dict): Kubernetes object description as specified in the
            specification of the application.
        response (kubernetes_asyncio.client.V1Service): Response of the
            Kubernetes API

    """
    if resource["kind"] != "Service":
        return

    service_name = resource["metadata"]["name"]
    node_port = None

    # Ensure that ports are specified
    if response.spec and response.spec.ports:
        node_port = response.spec.ports[0].node_port

    # If the service does not have a node port, remove a potential reference
    # and return.
    if node_port is None:
        try:
            del app.status.services[service_name]
        except KeyError:
            pass
        return

    # Determine URL of Kubernetes cluster API
    loader = KubeConfigLoader(cluster.spec.kubeconfig)
    config = Configuration()
    await loader.load_and_set(config)
    cluster_url = yarl.URL(config.host)

    app.status.services[service_name] = f"{cluster_url.host}:{node_port}"


@listen.on(Hook.ResourcePostDelete)
async def unregister_service(app, cluster, resource, response):
    """Unregister endpoint of Kubernetes Service object on deletion.

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        cluster (krake.data.kubernetes.Cluster): The cluster on which the
            application is running
        resource (dict): Kubernetes object description as specified in the
            specification of the application.
        response (kubernetes_asyncio.client.V1Status): Response of the
            Kubernetes API

    """
    if resource["kind"] != "Service":
        return

    service_name = resource["metadata"]["name"]
    try:
        del app.status.services[service_name]
    except KeyError:
        pass


@listen.on(Hook.ResourcePostCreate)
@listen.on(Hook.ResourcePostUpdate)
async def register_resource_version(app, response, **kwargs):
    """Register or update the resource version of a Kubernetes resource

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        response (object): Response of the Kubernetes API
    """

    for resource_version in app.status.resource_versions:
        if (
            resource_version.kind,
            resource_version.api_version,
            resource_version.name,
        ) == (response.kind, response.api_version, response.metadata.name):
            resource_version.last_applied_resource_version = int(
                response.metadata.resource_version
            )
            resource_version.observed_resource_version = int(
                response.metadata.resource_version
            )
            return

    app.status.resource_versions.append(
        ResourceVersion(
            kind=response.kind,
            api_version=response.api_version,
            name=response.metadata.name,
            last_applied_resource_version=int(response.metadata.resource_version),
            observed_resource_version=int(response.metadata.resource_version),
        )
    )


@listen.on(Hook.ResourcePostDelete)
async def unregister_resource_version(app, resource, **kwargs):
    """Unregister the resource version of a Kubernetes resource

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        resource (dict): Kubernetes object description as specified in the
            specification of the application.

    """

    for index, resource_version in enumerate(app.status.resource_versions):
        if (
            resource_version.kind,
            resource_version.api_version,
            resource_version.name,
        ) == (resource["kind"], resource["apiVersion"], resource["metadata"]["name"]):
            del app.status.resource_versions[index]
            return


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
            observed.
        on_res_update (coroutine): a coroutine called when a resource's actual status
            differs from the status sent by the database. Its signature is:
            ``(resource) -> updated_resource``. ``updated_resource`` is the instance of
            the resource that is up-to-date with the API. The Observer internal instance
            of the resource to observe will be updated. If the API cannot be contacted,
            ``None`` can be returned. In this case the internal instance of the Observer
            will not be updated.
        kubernetes_client (type):
        time_step (int, optional): how frequently the Observer should watch the actual
            status of the resources.

    """

    def __init__(
        self, cluster, resource, on_res_update, kubernetes_client, time_step=2
    ):
        super().__init__(resource, on_res_update, time_step)
        self.cluster = cluster
        self.kubernetes_client = kubernetes_client

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
            kube = self.kubernetes_client(self.cluster.spec.kubeconfig)
            async with kube:
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

            observed_resource = resp.to_dict()

            for resource_version in status.resource_versions:
                if (
                    resource_version.kind,
                    resource_version.api_version,
                    resource_version.name,
                ) == (
                    observed_resource["kind"],
                    observed_resource["api_version"],
                    observed_resource["metadata"]["name"],
                ):
                    resource_version.observed_resource_version = int(
                        observed_resource["metadata"]["resource_version"]
                    )

            # Update the status with the information taken from the resource on the
            # cluster
            actual_manifest = merge_status(resource, observed_resource)
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


@listen.on(Hook.ApplicationPostReconcile)
@listen.on(Hook.ApplicationPostMigrate)
async def register_observer(controller, app, kubernetes_client, start=True, **kwargs):
    """Create an observer for the given Application, and start it as background
    task if wanted.

    If an observer already existed for this Application, it is stopped and deleted.

    Args:
        controller (KubernetesController): the controller for which the observer will be
            added in the list of working observers.
        app (krake.data.kubernetes.Application): the Application to observe
        kubernetes_client (type):
        start (bool, optional): if False, does not start the observer as background
            task.

    """
    from krake.controller.kubernetes_application import KubernetesObserver

    cluster = await controller.kubernetes_api.read_cluster(
        namespace=app.status.running_on.namespace, name=app.status.running_on.name
    )
    observer = KubernetesObserver(
        cluster,
        app,
        controller.on_status_update,
        kubernetes_client,
        time_step=controller.observer_time_step,
    )

    logger.debug("Start observer for %r", app)
    task = None
    if start:
        task = controller.loop.create_task(observer.run())

    controller.observers[app.metadata.uid] = (observer, task)


@listen.on(Hook.ApplicationPreReconcile)
@listen.on(Hook.ApplicationPreMigrate)
@listen.on(Hook.ApplicationPreDelete)
async def unregister_observer(controller, app, **kwargs):
    """Stop and delete the observer for the given Application. If no observer is
    started, do nothing.

    Args:
        controller (KubernetesController): the controller for which the observer will be
            removed from the list of working observers.
        app (krake.data.kubernetes.Application): the Application whose observer will
            be stopped.

    """
    if app.metadata.uid not in controller.observers:
        return

    logger.debug("Stop observer for %r", app)
    _, task = controller.observers.pop(app.metadata.uid)
    task.cancel()

    with suppress(asyncio.CancelledError):
        await task


@listen.on(Hook.ApplicationMangling)
async def complete(app, api_endpoint, ssl_context, config):
    """Execute application complete hook defined by :class:`Complete`.
    Hook mangles given application and injects complete hooks variables.

    Application complete hook is disabled by default.
    User enables this hook by the --hook argument in rok cli.

    Args:
        app (krake.data.kubernetes.Application): Application object processed
            when the hook is called
        api_endpoint (str): the given API endpoint
        ssl_context (ssl.SSLContext): SSL context to communicate with the API endpoint
        config (krake.data.config.HooksConfiguration): Complete hook
            configuration.

    """
    if "complete" not in app.spec.hooks:
        return

    app.status.token = app.status.token if app.status.token else token_urlsafe()

    hook = Complete(
        api_endpoint,
        ssl_context,
        ca_dest=config.complete.ca_dest,
        env_token=config.complete.env_token,
        env_complete=config.complete.env_complete,
    )
    hook.mangle_app(
        app.metadata.name, app.metadata.namespace, app.status.token, app.status.mangling
    )


class SubResource(NamedTuple):
    group: str
    name: str
    body: dict
    path: tuple


class Complete(object):
    """Mangle given application and injects complete hooks variables into it.

    Hook injects environment variable which stores Krake authentication token
    and environment variable which stores the Krake complete hook URL for given
    application into application resource definition. Only resource for the Kubernetes
    Pod creation defined in :args:`complete_resources` can be modified.
    Names of environment variables are defined in the application controller
    configuration file.
    If TLS is enabled on Krake API, complete hook injects Kubernetes configmap
    and volume definition for the Krake CA certificate.
    CA certificate is loaded from configmap and stored as a file in injected
    application volume. Filename is defined in the application controller configuration
    file.

    Args:
        api_endpoint (str): the given API endpoint
        ssl_context (ssl.SSLContext): SSL context to communicate with the API endpoint
        ca_dest (str, optional): Path path of the CA in deployed Application.
            Defaults to /etc/krake_ca/ca.pem
        env_token (str, optional): Name of the environment variable, which stores Krake
            authentication token. Defaults to KRAKE_TOKEN
        env_complete (str, optional): Name of the environment variable,
            which stores Krake complete hook URL. Defaults to KRAKE_COMPLETE_URL

    """

    complete_resources = ("Pod", "Deployment", "ReplicationController")

    def __init__(
        self,
        api_endpoint,
        ssl_context,
        ca_dest="/etc/krake_ca/ca.pem",
        env_token="KRAKE_TOKEN",
        env_complete="KRAKE_COMPLETE_URL",
    ):
        self.api_endpoint = api_endpoint
        self.ssl_context = ssl_context
        self.ca_dest = ca_dest
        self.env_token = env_token
        self.env_complete = env_complete

    def mangle_app(self, name, namespace, token, mangling):
        """Mangle given application and injects complete hook resources and
        sub-resources into mangling object by :meth:`mangle`.

        Mangling object is created as a deep copy of desired application resources,
        defined by user. This object can be updated by custom hook resources
        or modified by custom hook sub-resources. It is used as a desired state for the
        Krake deployment process.

        Args:
            name (str): Application name
            namespace (str): Application namespace
            token (str): Complete hook authentication token
            mangling (list): Application resources

        """
        cfg_name = "-".join([name, "krake", "configmap"])
        volume_name = "-".join([name, "krake", "volume"])
        ca_certs = (
            self.ssl_context.get_ca_certs(binary_form=True)
            if self.ssl_context
            else None
        )

        hook_resources = [*self.configmap(cfg_name, ca_certs)]
        hook_sub_resources = [
            *self.env_vars(name, namespace, self.api_endpoint, token),
            *self.volumes(cfg_name, volume_name, ca_certs),
        ]

        self.mangle(hook_resources, mangling)
        self.mangle(hook_sub_resources, mangling, sub_resource=True)

    @staticmethod
    def attribute_map(obj):
        """Convert Kubernetes object to dict based on its attribute mapping

        Example:
            .. code:: python

            from kubernetes_asyncio.client import V1VolumeMount

            d = attribute_map(
                    V1VolumeMount(name="name", mount_path="path")
            )
            assert d == {'mountPath': 'path', 'name': 'name'}

        Args:
            obj (object): Kubernetes object

        Returns:
            dict: Converted Kubernetes object

        """
        return {
            obj.attribute_map[attr]: getattr(obj, attr)
            for attr, _ in obj.to_dict().items()
            if getattr(obj, attr) is not None
        }

    def mangle(self, items, mangling, sub_resource=False):
        """Mangle application desired state with custom hook resources or
        sub-resources

        Example:
            .. code:: python

            mangling = [
                {
                    'apiVersion': 'v1',
                    'kind': 'Pod',
                    'metadata': {'name': 'test'},
                    'spec': {'containers': [{'name': 'test'}]}
                }
            ]
            hook_resources = [
                {
                    'apiVersion': 'v1',
                    'kind': 'ConfigMap',
                    'metadata': {'name': 'cfg'}
                }
            ]
            hook_sub_resources = [
                SubResource(
                    group='env', name='env', body={'name': 'test', 'value': 'test'},
                    path=(('spec', 'containers'),)
                )
            ]

            mangle(hook_resources, mangling)
            mangle(hook_sub_resources, mangling, sub_resource=True)

            assert mangling == [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "test"},
                    "spec": {
                        "containers": [
                            {
                                "name": "test",
                                "env": [{"name": "test", "value": "test"}]
                            }
                        ]
                    },
                },
                {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "cfg"}},
            ]


        Args:
            items (list): Custom hook resources or sub-resources
            mangling (list): Application resources
            sub_resource (bool, optional): if False, the function only extend
                the mangling list of Kuberentes resources by new hook resources.
                Otherwise, continue to inject each new hook sub-resource into the
                mangling object sub-resources. Defaults to False

        """

        if not items:
            return

        if not sub_resource:
            mangling.extend(items)
            return

        def inject(sub_resource, sub_resources_to_mangle):
            """Inject hook defined sub-resources into mangle sub-resources

            Args:
                sub_resource (SubResource): Hook sub-resource that needs to be injected
                    into desired mangling state
                sub_resources_to_mangle (object): Sub-resource from the Mangling state
                    which needs to be processed

            """

            # Create sub-resource group if not present in the mangle sub-resources
            if sub_resource.group not in sub_resources_to_mangle:
                sub_resources_to_mangle.update({sub_resource.group: []})

            # Inject sub-resource
            # If sub-resource name is already there update it, if not, append it
            if sub_resource.name in [
                g["name"] for g in sub_resources_to_mangle[sub_resource.group]
            ]:
                for idx, item in enumerate(sub_resources_to_mangle[sub_resource.group]):

                    if item.name == item["name"]:
                        sub_resources_to_mangle[item.group][idx] = item.body
            else:
                sub_resources_to_mangle[sub_resource.group].append(sub_resource.body)

        for resource in mangling:
            # Complete hook is applied only on defined Kubernetes resources
            if resource["kind"] not in self.complete_resources:
                continue

            for sub_resource in items:
                sub_resources_to_mangle = None
                for keys in sub_resource.path:
                    try:
                        sub_resources_to_mangle = reduce(getitem, keys, resource)
                    except KeyError:
                        continue
                    break

                if isinstance(sub_resources_to_mangle, list):
                    for sub_resource_to_mangle in sub_resources_to_mangle:
                        inject(sub_resource, sub_resource_to_mangle)

                elif isinstance(sub_resources_to_mangle, dict):
                    inject(sub_resource, sub_resources_to_mangle)

                else:
                    raise InvalidResourceError

    def configmap(self, cfg_name, ca_certs=None):
        """Create complete hook configmap resource

        Complete hook configmap stores Krake CAs to communicate with the Krake API

        Args:
            cfg_name (str): Configmap name
            ca_certs (list): Krake CA list

        Returns:
            list: List of complete hook configmaps resources

        """
        if not ca_certs:
            return []

        ca_name = os.path.basename(self.ca_dest)

        ca_certs_pem = ""
        for ca_cert in ca_certs:
            x509 = OpenSSL.crypto.load_certificate(
                OpenSSL.crypto.FILETYPE_ASN1, ca_cert
            )
            ca_certs_pem += OpenSSL.crypto.dump_certificate(
                OpenSSL.crypto.FILETYPE_PEM, x509
            ).decode("utf-8")

        return [
            self.attribute_map(
                V1ConfigMap(
                    api_version="v1",
                    kind="ConfigMap",
                    data={ca_name: ca_certs_pem},
                    metadata={"name": cfg_name},
                )
            )
        ]

    def volumes(self, cfg_name, volume_name, ca_certs=None):
        """Create complete hook volume and volume mount sub-resources

        Complete hook volume gives access to configmap which stores Krake CAs
        Complete hook volume mount mounts volume into application

        Args:
            cfg_name (str): Configmap name
            volume_name (str): Volume name
            ca_certs (list): Krake CA list

        Returns:
            list: List of complete hook volume and volume mount sub-resources

        """
        if not ca_certs:
            return []

        ca_dir = os.path.dirname(self.ca_dest)

        volume = V1Volume(name=volume_name, config_map={"name": cfg_name})
        volume_mount = V1VolumeMount(name=volume_name, mount_path=ca_dir)
        return [
            SubResource(
                group="volumes",
                name=volume.name,
                body=self.attribute_map(volume),
                path=(("spec", "template", "spec"), ("spec",)),
            ),
            SubResource(
                group="volumeMounts",
                name=volume_mount.name,
                body=self.attribute_map(volume_mount),
                path=(
                    ("spec", "template", "spec", "containers"),
                    ("spec", "containers"),  # kind: Pod
                ),
            ),
        ]

    @staticmethod
    def create_complete_url(name, namespace, api_endpoint):
        """Create application complete URL.

        Args:
            name (str): Application name
            namespace (str): Application namespace
            api_endpoint (str): Krake API endpoint

        Returns:
            str: Application complete url

        """
        api_url = URL(api_endpoint)

        # FIXME: Krake host IP address is temporary loaded from environment
        #  variable "KRAKE_HOST", if present. This should be removed when
        #  DNS service takes place.
        api_host = os.environ.get("KRAKE_HOST")
        if api_host is not None:
            api_url = api_url.with_host(api_host)

        return str(
            api_url.with_path(
                f"/kubernetes/namespaces/{namespace}/applications/{name}/complete"
            )
        )

    def env_vars(self, name, namespace, api_endpoint, token):
        """Create complete hook environment variables sub-resources

        Create complete hook environment variables store Krake authentication token
        and complete hook URL for given application.

        Args:
            name (str): Application name
            namespace (str): Application namespace
            token (str): Complete hook authentication token
            api_endpoint (str): Krake API endpoint
            token (str): Complete hook authentication token

        Returns:
            list: List of complete hook environment variables sub-resources

        """
        sub_resources = []
        complete_url = self.create_complete_url(name, namespace, api_endpoint)

        env_token = V1EnvVar(name=self.env_token, value=token)
        env_url = V1EnvVar(name=self.env_complete, value=complete_url)

        for env in (env_token, env_url):
            sub_resources.append(
                SubResource(
                    group="env",
                    name=env.name,
                    body=self.attribute_map(env),
                    path=(
                        ("spec", "template", "spec", "containers"),
                        ("spec", "containers"),  # kind: Pod
                    ),
                )
            )
        return sub_resources
