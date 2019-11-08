"""This module defines the Hook Dispatcher and listeners for registering and
executing hooks. Hook Dispatcher emits hooks based on :class:`Hook` attributes which
define when the hook will be executed.

"""
import logging
import os
from functools import reduce
from operator import getitem
from enum import Enum, auto
from functools import wraps
from inspect import iscoroutinefunction
from typing import NamedTuple

import OpenSSL
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

from ..exceptions import ControllerError


logger = logging.getLogger(__name__)


class InvalidResourceError(ControllerError):
    """Raised in case of invalid kubernetes resource definition."""

    code = ReasonCode.INVALID_RESOURCE


class Hook(Enum):
    PreApply = auto()
    PostApply = auto()
    PreDelete = auto()
    PostDelete = auto()
    Mangling = auto()


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
        self.registry = {}

    def on(self, hook):
        """Decorator function to add a new handler to the registry.

        Args:
            hook (Hook): Hook attribute for which to register the handler.

        Returns:
            callable: Decorator for registering listeners for the specified
            hook.

        """

        def decorator(handler):
            if hook not in self.registry:
                self.registry[hook] = [handler]
            else:
                self.registry[hook].append(handler)

            @wraps(handler)
            def wrapper(*args, **kwargs):
                handler(*args, **kwargs)

            return wrapper

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


@listen.on(Hook.PostApply)
async def register_service(app, cluster, resource, resp):
    if resource["kind"] != "Service":
        return

    service_name = resp.metadata.name

    node_port = resp.spec.ports[0].node_port

    if node_port is None:
        return

    # Load Kubernetes configuration and get host
    loader = KubeConfigLoader(cluster.spec.kubeconfig)
    config = Configuration()
    await loader.load_and_set(config)
    url = URL(config.host)

    app.status.services[service_name] = url.host + ":" + str(node_port)


@listen.on(Hook.Mangling)
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
        config (dict): Complete hook configuration

    """
    if "complete" not in app.spec.hooks:
        return

    complete_config = config.get("complete")
    if complete_config is None:
        return

    app.spec.token = app.spec.token if app.spec.token else token_urlsafe()

    hook = Complete(
        api_endpoint,
        ssl_context,
        ca_dest=complete_config["ca_dest"],
        env_token=complete_config["env_token"],
        env_complete=complete_config["env_complete"],
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
        """Mangle given application and injects complete hook variables into mangling
        object.

        Mangling object is created as a deep copy of desired application resources,
        defined by user. This object can be updated by custom Krake resources
        or modified by custom Krake sub-resources. It is used as a desired state for the
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

        resources = [*self.configmap(cfg_name, ca_certs)]
        sub_resources = [
            *self.env_vars(name, namespace, self.api_endpoint, token),
            *self.volumes(cfg_name, volume_name, ca_certs),
        ]

        self.mangle(resources, mangling)
        self.mangle(sub_resources, mangling, sub_resource=True)

    @staticmethod
    def attribute_map(obj):
        return {
            obj.attribute_map[attr]: getattr(obj, attr)
            for attr, _ in obj.to_dict().items()
            if getattr(obj, attr) is not None
        }

    def mangle(self, elements, mangling, sub_resource=False):
        """Mangle application desired state with custom Krake elements

        Args:
            elements (dict): Custom Krake elements
            mangling (list): Application resources
            sub_resource (bool, optional): if False, the function only append
                given element to the mangling list as a Kuberentes resource.
                Otherwise, continue to inject each new sub-resource into the mangling
                object. Defaults to False

        """

        if not elements:
            return

        if not sub_resource:
            mangling.extend(elements)
            return

        def update_or_append(element, section):
            if element.group not in section:
                section.update({element.group: []})

            if element.name in [g["name"] for g in section[element.group]]:
                for idx, item in enumerate(section[element.group]):
                    if element.name == item["name"]:
                        section[element.group][idx] = element.body

            else:
                section[element.group].append(element.body)

        for resource in mangling:
            if resource["kind"] not in self.complete_resources:
                continue

            for element in elements:
                section = None
                for keys in element.path:
                    try:
                        section = reduce(getitem, keys, resource)
                    except KeyError:
                        continue
                    break

                if isinstance(section, list):
                    for item in section:
                        update_or_append(element, item)

                elif isinstance(section, dict):
                    update_or_append(element, section)

                else:
                    raise InvalidResourceError

    def configmap(self, cfg_name, ca_certs=None):
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
            api_endpoint (str): the given API endpoint.

        Returns:
            str: Application complete url

        """
        api_url = URL(api_endpoint)

        # FIXME: Krake hostname is temporary loaded from environment
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
