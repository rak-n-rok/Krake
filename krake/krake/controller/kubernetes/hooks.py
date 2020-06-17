"""This module defines the Hook Dispatcher and listeners for registering and
executing hooks. Hook Dispatcher emits hooks based on :class:`Hook` attributes which
define when the hook will be executed.

"""
import asyncio
import logging
import random
from collections import defaultdict
from contextlib import suppress
from copy import deepcopy
from datetime import datetime
from functools import reduce
from operator import getitem
from enum import Enum, auto
from inspect import iscoroutinefunction
from OpenSSL import crypto
from typing import NamedTuple

import yarl
from krake.controller import Observer, ControllerError
from krake.controller.kubernetes.client import KubernetesClient
from krake.utils import camel_to_snake_case
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
        """Execute the list of handlers associated to the provided :class:`Hook`
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
        status.last_observed_manifest = []

        # For each kubernetes resource of the Application,
        # get its current status on the cluster.
        for resource in app.status.last_observed_manifest:
            kube = KubernetesClient(self.cluster.spec.kubeconfig)

            async with kube:
                try:
                    resource_api = await kube.get_resource_api(resource["kind"])

                    namespace = resource["metadata"].get(
                        "namespace", kube.default_namespace
                    )
                    resp = await resource_api.read(
                        resource["kind"], resource["metadata"]["name"], namespace
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
            status.last_observed_manifest.append(actual_manifest)

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
        # The keys taken from the new dictionary are in camel case, while the keys from
        # the old dictionary are in snake case.
        underscore_key = camel_to_snake_case(key)

        # Go through dictionaries recursively
        if type(value) is dict:
            new_value = new.get(underscore_key, {})
            assert type(new_value) is dict
            result[key] = merge_status(value, new_value)

        elif type(value) is list:
            new_value = new.get(underscore_key, [])
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
            result[key] = new.get(underscore_key, value)

    return result


@listen.on(Hook.ApplicationPostReconcile)
@listen.on(Hook.ApplicationPostMigrate)
async def register_observer(controller, app, start=True, **kwargs):
    """Create an observer for the given Application, and start it as background
    task if wanted.

    If an observer already existed for this Application, it is stopped and deleted.

    Args:
        controller (KubernetesController): the controller for which the observer will be
            added in the list of working observers.
        app (krake.data.kubernetes.Application): the Application to observe
        start (bool, optional): if False, does not start the observer as background
            task.

    """
    from krake.controller.kubernetes import KubernetesObserver

    cluster = await controller.kubernetes_api.read_cluster(
        namespace=app.status.running_on.namespace, name=app.status.running_on.name
    )
    observer = KubernetesObserver(
        cluster,
        app,
        controller.on_status_update,
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


def utc_difference():
    """Get the difference in seconds between the current time and the current UTC time.

    Returns:
        int: the time difference in seconds.

    """
    delta = datetime.now() - datetime.utcnow()
    return delta.seconds


def generate_certificate(config):
    """Create and sign a new certificate using the one defined in the complete hook
    configuration as intermediate certificate.

    Args:
        config (krake.data.config.CompleteHookConfiguration): the configuration of the
            complete hook.

    Returns:
        CertificatePair: the content of the certificate created and its corresponding
            key.

    """
    with open(config.intermediate_src, "rb") as f:
        intermediate_src = crypto.load_certificate(crypto.FILETYPE_PEM, f.read())
    with open(config.intermediate_key_src, "rb") as f:
        intermediate_key_src = crypto.load_privatekey(crypto.FILETYPE_PEM, f.read())

    client_cert = crypto.X509()

    # Set general information
    client_cert.set_version(3)
    client_cert.set_serial_number(random.randint(50000000000000, 100000000000000))
    # If not set before, TLS will not accept to use this certificate in UTC cases, as
    # the server time may be earlier.
    time_offset = utc_difference() * -1
    client_cert.gmtime_adj_notBefore(time_offset)
    client_cert.gmtime_adj_notAfter(1 * 365 * 24 * 60 * 60)

    # Set issuer and subject
    intermediate_subject = intermediate_src.get_subject()
    client_cert.set_issuer(intermediate_subject)
    client_subj = crypto.X509Name(intermediate_subject)
    client_subj.CN = config.hook_user
    client_cert.set_subject(client_subj)

    # Create and set the private key
    client_key = crypto.PKey()
    client_key.generate_key(crypto.TYPE_RSA, 2048)
    client_cert.set_pubkey(client_key)

    client_cert.sign(intermediate_key_src, "sha256")  # Should be done at the very end.

    cert_dump = crypto.dump_certificate(crypto.FILETYPE_PEM, client_cert).decode()
    key_dump = crypto.dump_privatekey(crypto.FILETYPE_PEM, client_key).decode()
    return CertificatePair(cert=cert_dump, key=key_dump)


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

    # Use the endpoint of the API only if the external endpoint has not been set.
    if config.complete.external_endpoint:
        api_endpoint = config.complete.external_endpoint

    app.status.token = app.status.token if app.status.token else token_urlsafe()

    # Generate only once the certificate and key for a specific Application
    generated_cert = CertificatePair(
        cert=app.status.complete_cert, key=app.status.complete_key
    )
    if ssl_context and generated_cert == (None, None):
        generated_cert = generate_certificate(config.complete)
        app.status.complete_cert = generated_cert.cert
        app.status.complete_key = generated_cert.key

    hook = Complete(
        api_endpoint,
        ssl_context,
        hook_user=config.complete.hook_user,
        cert_dest=config.complete.cert_dest,
        env_token=config.complete.env_token,
        env_complete=config.complete.env_complete,
    )
    hook.mangle_app(
        app.metadata.name,
        app.metadata.namespace,
        app.status.token,
        app.status.last_applied_manifest,
        config.complete.intermediate_src,
        generated_cert,
    )


class SubResource(NamedTuple):
    group: str
    name: str
    body: dict
    path: tuple


class CertificatePair(NamedTuple):
    """Tuple which contains a certificate and its corresponding key.

    Attributes:
        cert (str): content of a certificate.
        key (str): content of the key that corresponds to the certificate.

    """

    cert: str
    key: str


class Complete(object):
    """Mangle given application and injects complete hooks variables into it.

    Hook injects environment variable which stores Krake authentication token
    and environment variable which stores the Krake complete hook URL for given
    application into application resource definition. Only resource for the Kubernetes
    Pod creation defined in :args:`complete_resources` can be modified.
    Names of environment variables are defined in the application controller
    configuration file.
    If TLS is enabled on the Krake API, the complete hook injects a Kubernetes configmap
    and it corresponding volume and volume mount definitions for the Krake CA,
    the client certificate with the right CN, and its key. The directory where the
    configmap is mounted is defined in the configuration.

    Args:
        api_endpoint (str): the given API endpoint
        ssl_context (ssl.SSLContext): SSL context to communicate with the API endpoint
        cert_dest (str, optional): Path of the directory where the CA, client
            certificate and key to the Krake API will be stored.
        env_token (str, optional): Name of the environment variable, which stores Krake
            authentication token.
        env_complete (str, optional): Name of the environment variable,
            which stores Krake complete hook URL.

    """

    complete_resources = ("Pod", "Deployment", "ReplicationController")
    ca_name = "ca-bundle.pem"
    cert_name = "cert.pem"
    key_name = "key.pem"

    def __init__(
        self, api_endpoint, ssl_context, hook_user, cert_dest, env_token, env_complete
    ):
        self.api_endpoint = api_endpoint
        self.ssl_context = ssl_context
        self.hook_user = hook_user
        self.cert_dest = cert_dest
        self.env_token = env_token
        self.env_complete = env_complete

    def mangle_app(
        self, name, namespace, token, last_applied_manifest, intermediate_src, generated_cert
    ):
        """Mangle given application and injects complete hook resources and
        sub-resources into :attr:`last_applied_manifest` object by :meth:`mangle`.

        :attr:`last_applied_manifest` is created as a deep copy of the desired
        application resources, as defined by user. It can be updated by custom hook
        resources or modified by custom hook sub-resources. It is used as a desired
        state for the Krake deployment process.

        Args:
            name (str): Application name
            namespace (str): Application namespace
            token (str): Complete hook authentication token
            last_applied_manifest (list): Application resources
            intermediate_src (str): content of the certificate that is used to sign new
                certificates for the complete hook.
            generated_cert (CertificatePair): tuple that contains the content of the
                new signed certificate for the Application, and the content of its
                corresponding key.

        """
        cfg_name = "-".join([name, "krake", "configmap"])
        volume_name = "-".join([name, "krake", "volume"])
        ca_certs = (
            self.ssl_context.get_ca_certs(binary_form=True)
            if self.ssl_context
            else None
        )

        # Extract all different namespaces
        # FIXME: too many assumptions here: do we create one ConfigMap for each
        #  namespace?
        resource_namespaces = {
            resource["metadata"].get("namespace", "default") for resource in mangling
        }

        hook_resources = []
        if ca_certs:
            hook_resources = [
                self.configmap(
                    cfg_name,
                    namespace,
                    intermediate_src=intermediate_src,
                    generated_cert=generated_cert,
                    ca_certs=ca_certs,
                )
                for namespace in resource_namespaces
            ]

        hook_sub_resources = [
            *self.env_vars(name, namespace, self.api_endpoint, token),
            *self.volumes(cfg_name, volume_name, ca_certs),
        ]

        self.mangle(hook_resources, last_applied_manifest)
        self.mangle(hook_sub_resources, last_applied_manifest, is_sub_resource=True)

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

    def mangle(self, items, last_applied_manifest, is_sub_resource=False):
        """Mangle application desired state with custom hook resources or
        sub-resources

        Example:
            .. code:: python

            last_applied_manifest = [
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

            mangle(hook_resources, last_applied_manifest)
            mangle(hook_sub_resources, last_applied_manifest, is_sub_resource=True)

            assert last_applied_manifest == [
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
            last_applied_manifest (list): Application resources
            is_sub_resource (bool, optional): if False, the function only extend list of
                Kubernetes resources definied in :attr:`last_applied_manifest` with new
                hook resources. Otherwise, continue to inject each new hook
                sub-resource into the :attr:`last_applied_manifest` object
                sub-resources. Defaults to False

        """

        if not items:
            return

        if not is_sub_resource:
            last_applied_manifest.extend(items)
            return

        def inject(sub_resource, sub_resources_to_mangle):
            """Inject hook defined sub-resources into Kubernetes sub-resources

            Args:
                sub_resource (SubResource): Hook sub-resource that needs to be injected
                    into :attr:`last_applied_manifest`
                sub_resources_to_mangle (object): Kubernetes sub-resources from
                    :attr:`last_applied_manifest` which need to be processed

            """

            # Create sub-resource group if not present in the kubernetes sub-resources
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

        for resource in last_applied_manifest:
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

    def configmap(
        self,
        cfg_name,
        namespace,
        ca_certs=None,
        intermediate_src=None,
        generated_cert=None,
    ):
        """Create a complete hook configmap resource.

        Complete hook configmap stores Krake CAs and client certificates to communicate
        with the Krake API.

        Args:
            cfg_name (str): Configmap name
            namespace (str): Kubernetes namespace where the ConfigMap will be created.
            ca_certs (list): Krake CA list
            intermediate_src (str): content of the certificate that is used to sign new
                certificates for the complete hook.
            generated_cert (CertificatePair): tuple that contains the content of the
                new signed certificate for the Application, and the content of its
                corresponding key.

        Returns:
            dict: complete hook configmaps resources

        """
        ca_certs_pem = ""
        for ca_cert in ca_certs:
            x509 = crypto.load_certificate(crypto.FILETYPE_ASN1, ca_cert)
            ca_certs_pem += crypto.dump_certificate(crypto.FILETYPE_PEM, x509).decode()

        # Add the intermediate certificate into the chain
        with open(intermediate_src, "r") as f:
            intermediate_src_content = f.read()
        ca_certs_pem += intermediate_src_content

        data = {
            self.ca_name: ca_certs_pem,
            self.cert_name: generated_cert.cert,
            self.key_name: generated_cert.key,
        }
        return self.attribute_map(
            V1ConfigMap(
                api_version="v1",
                kind="ConfigMap",
                data=data,
                metadata={"name": cfg_name, "namespace": namespace},
            )
        )

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

        volume = V1Volume(name=volume_name, config_map={"name": cfg_name})
        volume_mount = V1VolumeMount(name=volume_name, mount_path=self.cert_dest)
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
