"""This module defines the Hook Dispatcher and listeners for registering and
executing hooks. Hook Dispatcher emits hooks based on :class:`Hook` attributes which
define when the hook will be executed.

"""
import asyncio
import logging
import random
from base64 import b64encode
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
from aiohttp import ClientConnectorError

from krake.controller import Observer
from krake.controller.kubernetes.client import KubernetesClient, InvalidManifestError
from krake.controller.kubernetes.tosca import ToscaParser, ToscaParserException
from krake.utils import camel_to_snake_case, get_kubernetes_resource_idx
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio import client
from krake.data.kubernetes import (
    ClusterState,
    Application,
    Cluster,
    ClusterNodeCondition,
    ClusterNode,
    ClusterNodeStatus,
    ApplicationState,
)
from yarl import URL
from secrets import token_urlsafe

from kubernetes_asyncio.client import (
    Configuration,
    V1Secret,
    V1EnvVar,
    V1VolumeMount,
    V1Volume,
    V1SecretKeySelector,
    V1EnvVarSource,
)
from kubernetes_asyncio.config.kube_config import KubeConfigLoader


logger = logging.getLogger(__name__)


class HookType(Enum):
    ResourcePreCreate = auto()
    ResourcePostCreate = auto()
    ResourcePreUpdate = auto()
    ResourcePostUpdate = auto()
    ResourcePreDelete = auto()
    ResourcePostDelete = auto()
    ApplicationToscaTranslation = auto()
    ApplicationMangling = auto()
    ApplicationPreMigrate = auto()
    ApplicationPostMigrate = auto()
    ApplicationPreReconcile = auto()
    ApplicationPostReconcile = auto()
    ApplicationPreDelete = auto()
    ApplicationPostDelete = auto()
    ClusterCreation = auto()
    ClusterDeletion = auto()


class HookDispatcher(object):
    """Simple wrapper around a registry of handlers associated to :class:`Hook`
     attributes. Each :class:`Hook` attribute defines when the handler will be
     executed.

    Listeners for certain hooks can be registered via :meth:`on`. Registered
    listeners are executed via :meth:`hook`.

    Example:
        .. code:: python

        listen = HookDispatcher()

        @listen.on(HookType.PreApply)
        def to_perform_before_app_creation(app, cluster, resource, controller):
            # Do Stuff

        @listen.on(HookType.PostApply)
        def another_to_perform_after_app_creation(app, cluster, resource, resp):
            # Do Stuff

        @listen.on(HookType.PostDelete)
        def to_perform_after_app_deletion(app, cluster, resource, resp):
            # Do Stuff

    """

    def __init__(self):
        self.registry = defaultdict(list)

    def on(self, hook):
        """Decorator function to add a new handler to the registry.

        Args:
            hook (HookType): Hook attribute for which to register the handler.

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
            hook (HookType): The hook attribute for which to execute handlers.

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


@listen.on(HookType.ResourcePostCreate)
@listen.on(HookType.ResourcePostUpdate)
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

    if response.spec and response.spec.type == "LoadBalancer":
        # For a "LoadBalancer" type of Service, an external IP is given in the cluster
        # by a load balancer controller to the service. In this case, the "port"
        # specified in the spec is reachable from the outside.
        if (
            not response.status.load_balancer
            or not response.status.load_balancer.ingress
        ):
            # When a "LoadBalancer" type of service is created, the IP is given by an
            # additional controller (e.g. a controller that requests a floating IP to an
            # OpenStack infrastructure). This process can take some time, but the
            # Service itself already exist before the IP is assigned. In the case of an
            # error with the controller, the IP is also not given. This "<pending>" IP
            # just expresses that the Service exists, but the IP is not ready yet.
            external_ip = "<pending>"
        else:
            external_ip = response.status.load_balancer.ingress[0].ip

        if not response.spec.ports:
            external_port = "<pending>"
        else:
            external_port = response.spec.ports[0].port
        app.status.services[service_name] = f"{external_ip}:{external_port}"
        return

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


@listen.on(HookType.ResourcePostDelete)
async def unregister_service(app, resource, **kwargs):
    """Unregister endpoint of Kubernetes Service object on deletion.

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        resource (dict): Kubernetes object description as specified in the
            specification of the application.

    """
    if resource["kind"] != "Service":
        return

    service_name = resource["metadata"]["name"]
    try:
        del app.status.services[service_name]
    except KeyError:
        pass


@listen.on(HookType.ResourcePostDelete)
async def remove_resource_from_last_observed_manifest(app, resource, **kwargs):
    """Remove a given resource from the last_observed_manifest after its deletion

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        resource (dict): Kubernetes object description as specified in the
            specification of the application.

    """
    try:
        idx = get_kubernetes_resource_idx(app.status.last_observed_manifest, resource)
    except IndexError:
        return

    app.status.last_observed_manifest.pop(idx)


def update_last_applied_manifest_dict_from_resp(
    last_applied_manifest, observer_schema, response
):
    """Together with :func:``update_last_applied_manifest_list_from_resp``, this
    function is called recursively to update a partial ``last_applied_manifest``
    from a partial Kubernetes response

    Args:
        last_applied_manifest (dict): partial ``last_applied_manifest`` being
            updated
        observer_schema (dict): partial ``observer_schema``
        response (dict): partial response from the Kubernetes API.

    Raises:
        KeyError: If the observed field is not present in the Kubernetes response

    This function go through all observed fields, and initialized their value in
    last_applied_manifest if they are not yet present

    """
    for key, value in observer_schema.items():

        # Keys in the response are in camelCase
        camel_key = camel_to_snake_case(key)

        if camel_key not in response:
            # An observed key should always be present in the k8s response
            raise KeyError(
                f"Observed key {camel_key} is not present in response {response}"
            )

        if isinstance(value, dict):
            if key not in last_applied_manifest:
                # The dictionary is observed, but not present in
                # last_applied_manifest
                last_applied_manifest[key] = {}

            update_last_applied_manifest_dict_from_resp(
                last_applied_manifest[key], observer_schema[key], response[camel_key]
            )

        elif isinstance(value, list):
            if key not in last_applied_manifest:
                # The list is observed, but not present in last_applied_manifest
                last_applied_manifest[key] = []

            update_last_applied_manifest_list_from_resp(
                last_applied_manifest[key], observer_schema[key], response[camel_key]
            )

        elif key not in last_applied_manifest:
            # If key not present in last_applied_manifest, and value is neither a
            # dict nor a list, simply add it.
            last_applied_manifest[key] = response[camel_key]


def update_last_applied_manifest_list_from_resp(
    last_applied_manifest, observer_schema, response
):
    """Together with :func:``update_last_applied_manifest_dict_from_resp``, this
    function is called recursively to update a partial ``last_applied_manifest``
    from a partial Kubernetes response

    Args:
        last_applied_manifest (list): partial ``last_applied_manifest`` being
            updated
        observer_schema (list): partial ``observer_schema``
        response (list): partial response from the Kubernetes API.

    This function go through all observed fields, and initialized their value in
    last_applied_manifest if they are not yet present

    """
    # Looping over the observed resource, except the last element which is the
    # special control dictionary
    for idx, val in enumerate(observer_schema[:-1]):

        if idx >= len(response):
            # Element is observed but not present in k8s response, so following
            # elements will also not exist.
            #
            # This doesn't raise an Exception as observing the element of a list
            # doesn't ensure its presence. The list length is controlled by the
            # special control dictionary
            return

        if isinstance(val, dict):
            if idx >= len(last_applied_manifest):
                # The dict is observed, but not present in last_applied_manifest
                last_applied_manifest.append({})

            update_last_applied_manifest_dict_from_resp(
                last_applied_manifest[idx], observer_schema[idx], response[idx]
            )

        elif isinstance(response[idx], list):
            if idx >= len(last_applied_manifest):
                # The list is observed, but not present in last_applied_manifest
                last_applied_manifest.append([])

            update_last_applied_manifest_list_from_resp(
                last_applied_manifest[idx], observer_schema[idx], response[idx]
            )

        elif idx >= len(last_applied_manifest):
            # Element is not yet present in last_applied_manifest. Adding it.
            last_applied_manifest.append(response[idx])


@listen.on(HookType.ResourcePostCreate)
@listen.on(HookType.ResourcePostUpdate)
def update_last_applied_manifest_from_resp(app, response, **kwargs):
    """Hook run after the creation or update of an application in order to update the
    `status.last_applied_manifest` using the k8s response.

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        response (kubernetes_asyncio.client.V1Status): Response of the Kubernetes API

    After a Kubernetes resource has been created/updated, the
    `status.last_applied_manifest` has to be updated. All fields already initialized
    (either from the mangling of `spec.manifest`, or by a previous call to this
    function) should be left untouched. Only observed fields which are not present in
    `status.last_applied_manifest` should be initialized.

    """

    if isinstance(response, dict):
        # The Kubernetes API couldn't deserialize the k8s response into an object
        resp = response
    else:
        # The Kubernetes API deserialized the k8s response into an object
        resp = response.to_dict()

    idx_applied = get_kubernetes_resource_idx(app.status.last_applied_manifest, resp)

    idx_observed = get_kubernetes_resource_idx(app.status.mangled_observer_schema, resp)

    update_last_applied_manifest_dict_from_resp(
        app.status.last_applied_manifest[idx_applied],
        app.status.mangled_observer_schema[idx_observed],
        resp,
    )


@listen.on(HookType.ResourcePostCreate)
@listen.on(HookType.ResourcePostUpdate)
def update_last_observed_manifest_from_resp(app, response, **kwargs):
    """Handler to run after the creation or update of a Kubernetes resource to update
    the last_observed_manifest from the response of the Kubernetes API.

    Args:
        app (krake.data.kubernetes.Application): Application the service belongs to
        response (kubernetes_asyncio.client.V1Service): Response of the
            Kubernetes API

    The target last_observed_manifest holds the value of all observed fields plus the
    special control dictionaries for the list length

    """
    if isinstance(response, dict):
        # The Kubernetes API couldn't deserialize the k8s response into an object
        resp = response
    else:
        # The Kubernetes API deserialized the k8s response into an object
        resp = response.to_dict()

    try:
        idx_observed = get_kubernetes_resource_idx(
            app.status.mangled_observer_schema,
            resp,
        )
    except IndexError:
        # All created resources should be observed
        raise

    try:
        idx_last_observed = get_kubernetes_resource_idx(
            app.status.last_observed_manifest,
            resp,
        )
    except IndexError:
        # If the resource is not yes present in last_observed_manifest, append it.
        idx_last_observed = len(app.status.last_observed_manifest)
        app.status.last_observed_manifest.append({})

    # Overwrite the last_observed_manifest for this resource
    app.status.last_observed_manifest[
        idx_last_observed
    ] = update_last_observed_manifest_dict(
        app.status.mangled_observer_schema[idx_observed], resp
    )


def update_last_observed_manifest_dict(observed_resource, response):
    """Together with :func:``update_last_observed_manifest_list``, recursively
    crafts the ``last_observed_manifest`` from the Kubernetes :attr:``response``.

    Args:
        observed_resource (dict): The schema to observe for the partial given resource
        response (dict): The partial Kubernetes response for this resource.

    Raises:
        KeyError: If an observed key is not present in the Kubernetes response

    Returns:
        dict: The dictionary of observed keys and their value

    Get the value of all observed fields from the Kubernetes response
    """
    res = {}
    for key, value in observed_resource.items():

        camel_key = camel_to_snake_case(key)
        if camel_key not in response:
            raise KeyError(
                f"Observed key {camel_key} is not present in response {response}"
            )

        if isinstance(value, dict):
            res[key] = update_last_observed_manifest_dict(value, response[camel_key])

        elif isinstance(value, list):
            res[key] = update_last_observed_manifest_list(value, response[camel_key])

        else:
            res[key] = response[camel_key]

    return res


def update_last_observed_manifest_list(observed_resource, response):
    """Together with :func:``update_last_observed_manifest_dict``, recursively
    crafts the ``last_observed_manifest`` from the Kubernetes :attr:``response``.

    Args:
        observed_resource (list): the schema to observe for the partial given resource
        response (list): the partial Kubernetes response for this resource.

    Returns:
        list: The list of observed elements, plus the special list length control
            dictionary

    Get the value of all observed elements from the Kubernetes response
    """

    if not response:
        return [{"observer_schema_list_current_length": 0}]

    res = []
    # Looping over the observed resource, except the last element which is the special
    # control dictionary
    for idx, val in enumerate(observed_resource[:-1]):

        if idx >= len(response):
            # Element is not present in the Kubernetes response, nothing more to do
            break

        if type(response[idx]) == dict:
            res.append(update_last_observed_manifest_dict(val, response[idx]))

        elif type(response[idx]) == list:
            res.append(update_last_observed_manifest_list(val, response[idx]))

        else:
            res.append(response[idx])

    # Append the special control dictionary to the list
    res.append({"observer_schema_list_current_length": len(response)})

    return res


def update_last_applied_manifest_dict_from_spec(
    resource_status_new, resource_status_old, resource_observed
):
    """Together with :func:``update_last_applied_manifest_list_from_spec``, this
    function is called recursively to update a partial ``last_applied_manifest``

    Args:
        resource_status_new (dict): partial ``last_applied_manifest`` being updated
        resource_status_old (dict): partial of the current ``last_applied_manifest``
        resource_observed (dict): partial observer_schema for the manifest file
            being updated

    """
    for key, value in resource_observed.items():

        if key not in resource_status_old:
            continue

        if key in resource_status_new:

            if isinstance(value, dict):
                update_last_applied_manifest_dict_from_spec(
                    resource_status_new[key],
                    resource_status_old[key],
                    resource_observed[key],
                )

            elif isinstance(value, list):
                update_last_applied_manifest_list_from_spec(
                    resource_status_new[key],
                    resource_status_old[key],
                    resource_observed[key],
                )

        else:
            # If the key is not present the spec.manifest, we first need to
            # initialize it

            if isinstance(value, dict):
                resource_status_new[key] = {}
                update_last_applied_manifest_dict_from_spec(
                    resource_status_new[key],
                    resource_status_old[key],
                    resource_observed[key],
                )

            elif isinstance(value, list):
                resource_status_new[key] = []
                update_last_applied_manifest_list_from_spec(
                    resource_status_new[key],
                    resource_status_old[key],
                    resource_observed[key],
                )

            else:
                resource_status_new[key] = resource_status_old[key]


def update_last_applied_manifest_list_from_spec(
    resource_status_new, resource_status_old, resource_observed
):
    """Together with :func:``update_last_applied_manifest_dict_from_spec``, this
    function is called recursively to update a partial ``last_applied_manifest``

    Args:
        resource_status_new (list): partial ``last_applied_manifest`` being updated
        resource_status_old (list): partial of the current ``last_applied_manifest``
        resource_observed (list): partial observer_schema for the manifest file
            being updated

    """

    # Looping over the observed resource, except the last element which is the
    # special control dictionary
    for idx, val in enumerate(resource_observed[:-1]):

        if idx >= len(resource_status_old):
            # The element in not in the current last_applied_manifest, and neither
            # is the rest of the list
            break

        if idx < len(resource_status_new):
            # The element is present in spec.manifest and in the current
            # last_applied_manifest. Updating observed fields

            if isinstance(val, dict):
                update_last_applied_manifest_dict_from_spec(
                    resource_status_new[idx],
                    resource_status_old[idx],
                    resource_observed[idx],
                )

            elif isinstance(val, list):
                update_last_applied_manifest_list_from_spec(
                    resource_status_new[idx],
                    resource_status_old[idx],
                    resource_observed[idx],
                )

        else:
            # If the element is not present in the spec.manifest, we first have to
            # initialize it.

            if isinstance(val, dict):
                resource_status_new.append({})
                update_last_applied_manifest_dict_from_spec(
                    resource_status_new[idx],
                    resource_status_old[idx],
                    resource_observed[idx],
                )

            elif isinstance(val, list):
                resource_status_new.append([])
                update_last_applied_manifest_list_from_spec(
                    resource_status_new[idx],
                    resource_status_old[idx],
                    resource_observed[idx],
                )

            else:
                resource_status_new.append(resource_status_old[idx])


def update_last_applied_manifest_from_spec(app):
    """Update the status.last_applied_manifest of an application from spec.manifests

    Args:
        app (krake.data.kubernetes.Application): Application to update

    This function is called on application creation and updates. The
    last_applied_manifest of an application is initialized as a copy of spec.manifest,
    and is augmented by all known observed fields not yet initialized (i.e. all observed
    fields or resources which are present in the current last_applied_manifest but not
    in the spec.manifest)

    """

    # The new last_applied_manifest is initialized as a copy of the spec.manifest, and
    # augmented by all observed fields which are present in the current
    # last_applied_manifest but not in the original spec.manifest
    new_last_applied_manifest = deepcopy(app.spec.manifest)

    # Loop over observed resources and observed fields, and check if they should be
    # added to the new last_applied_manifest (i.e. present in the current
    # last_applied_manifest but not in spec.manifest)
    for resource_observed in app.status.mangled_observer_schema:

        # If the resource is not present in the current last_applied_manifest, there is
        # nothing to do. Whether the resource was initialized by spec.manifest doesn't
        # matter.
        try:
            idx_status_old = get_kubernetes_resource_idx(
                app.status.last_applied_manifest, resource_observed
            )
        except IndexError:
            continue

        # As the resource is present in the current last_applied_manifest, we need to go
        # through it to check if observed fields should be set to their current value
        # (i.e. fields are present in the current last_applied_manifest, but not in
        # spec.manifest)
        try:
            # Check if the observed resource is present in spec.manifest
            idx_status_new = get_kubernetes_resource_idx(
                new_last_applied_manifest, resource_observed
            )
        except IndexError:
            # The resource is observed but is not present in the spec.manifest.
            # Create an empty resource, which will be augmented in
            # update_last_applied_manifest_dict_from_spec with the observed and known
            # fields.
            new_last_applied_manifest.append({})
            idx_status_new = len(new_last_applied_manifest) - 1

        update_last_applied_manifest_dict_from_spec(
            new_last_applied_manifest[idx_status_new],
            app.status.last_applied_manifest[idx_status_old],
            resource_observed,
        )

    app.status.last_applied_manifest = new_last_applied_manifest


class KubernetesApplicationObserver(Observer):
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
        # For each observed kubernetes resource of the Application,
        # get its current status on the cluster.
        for desired_resource in app.status.last_applied_manifest:
            kube = KubernetesClient(self.cluster.spec.kubeconfig)
            idx_observed = get_kubernetes_resource_idx(
                app.status.mangled_observer_schema, desired_resource
            )
            observed_resource = app.status.mangled_observer_schema[idx_observed]
            async with kube:
                try:
                    group, version, kind, name, namespace = kube.get_immutables(
                        desired_resource
                    )
                    resource_api = await kube.get_resource_api(group, version, kind)
                    resp = await resource_api.read(kind, name, namespace)
                except (ClientConnectorError, ApiException) as err:
                    if hasattr(err, "status") and err.status == 404:
                        # Resource does not exist
                        continue
                    # Otherwise, log the unexpected error and return the
                    # last known application status
                    logger.debug(err)
                    return app.status

            observed_manifest = update_last_observed_manifest_dict(
                observed_resource, resp.to_dict()
            )
            status.last_observed_manifest.append(observed_manifest)

        return status


class KubernetesClusterObserver(Observer):
    """Observer specific for Kubernetes Clusters. One observer is created for each
    Cluster managed by the Controller.

    The observer gets the actual status of the cluster using the
    Kubernetes API, and compare it to the status stored in the API.

    The observer is:
     * started at initial Krake resource creation;

     * deleted when a resource needs to be updated, then started again when it is done;

     * simply deleted on resource deletion.

    Args:
        resource (krake.data.kubernetes.Cluster): the cluster which will be observed.
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

    def __init__(self, resource, on_res_update, time_step=2):
        super().__init__(resource, on_res_update, time_step)

    async def poll_resource(self):
        """Fetch the current status of the Cluster monitored by the Observer.

        Note regarding exceptions handling:
          The current cluster status is fetched by :func:`poll_resource` from its API.
          If the cluster API is shutting down the API server responds with a 503
          (service unavailable, apiserver is shutting down) HTTP response which
          leads to the kubernetes client ApiException. If the cluster's API has been
          successfully shut down and there is an attempt to fetch cluster status,
          the ClientConnectorError is raised instead.
          Therefore, both exceptions should be handled.

        Returns:
            krake.data.core.Status: the status object created using information from the
                real world Cluster.

        """
        cluster = self.resource
        status = deepcopy(cluster.status)
        status.nodes = []
        # For each observed kubernetes cluster registered in Krake,
        # get its current node status.
        loader = KubeConfigLoader(cluster.spec.kubeconfig)
        config = Configuration()
        await loader.load_and_set(config)
        kube = ApiClient(config)

        async with kube as api:
            v1 = client.CoreV1Api(api)
            try:
                response = await v1.list_node()
            except (ClientConnectorError, ApiException) as err:
                # Log the error and set cluster state to OFFLINE
                logger.debug(err)
                status.state = ClusterState.OFFLINE
                return status

            # Fetch nodes conditions
            nodes = []
            for node in response.items:
                conditions = []
                for condition in node.status.conditions:
                    conditions.append(
                        ClusterNodeCondition(
                            message=condition.message,
                            reason=condition.reason,
                            status=condition.status,
                            type=condition.type,
                        )
                    )

                nodes.append(
                    ClusterNode(status=ClusterNodeStatus(conditions=conditions))
                )
            status.nodes = nodes

            # The scheduler is unable to fetch cluster metrics, hence
            # the cluster state should wait for it and the cluster
            # status should not be changed by the observer.
            if status.state == ClusterState.FAILING_METRICS:
                return status

            # Set the cluster state to CONNECTING if the previous state
            # was OFFLINE. It is due to smooth transition from
            # the OFFLINE to ONLINE state.
            if status.state == ClusterState.OFFLINE:
                status.state = ClusterState.CONNECTING
                return status

            for node in status.nodes:
                for condition in node.status.conditions:
                    if (
                        condition.type.lower().endswith("pressure")
                        and condition.status == "True"
                    ):
                        status.state = ClusterState.UNHEALTHY
                        return status

                    if condition.type.lower() == "ready" and condition.status != "True":
                        status.state = ClusterState.NOTREADY
                        return status

            status.state = ClusterState.ONLINE
            return status


@listen.on(HookType.ApplicationPostReconcile)
@listen.on(HookType.ApplicationPostMigrate)
@listen.on(HookType.ClusterCreation)
async def register_observer(controller, resource, start=True, **kwargs):
    """Create an observer for the given Application or Cluster, and start it as a
    background task if wanted.

    If an observer already existed for this Application or Cluster, it is stopped
    and deleted.

    Args:
        controller (KubernetesController): the controller for which the observer will be
            added in the list of working observers.
        resource (krake.data.kubernetes.Application): the Application to observe or
        resource (krake.data.kubernetes.Cluster): the Cluster to observe.
        start (bool, optional): if False, does not start the observer as background
            task.

    """
    if resource.kind == Application.kind:
        cluster = await controller.kubernetes_api.read_cluster(
            namespace=resource.status.running_on.namespace,
            name=resource.status.running_on.name,
        )
        observer = KubernetesApplicationObserver(
            cluster,
            resource,
            controller.on_status_update,
            time_step=controller.observer_time_step,
        )

    elif resource.kind == Cluster.kind:
        observer = KubernetesClusterObserver(
            resource,
            controller.on_status_update,
            time_step=controller.observer_time_step,
        )
    else:
        logger.debug("Unknown resource kind. No observer was registered.", resource)
        return

    logger.debug(f"Start observer for {resource.kind} %r", resource.metadata.name)
    task = None
    if start:
        task = controller.loop.create_task(observer.run())

    controller.observers[resource.metadata.uid] = (observer, task)


@listen.on(HookType.ApplicationPreReconcile)
@listen.on(HookType.ApplicationPreMigrate)
@listen.on(HookType.ApplicationPreDelete)
@listen.on(HookType.ClusterDeletion)
async def unregister_observer(controller, resource, **kwargs):
    """Stop and delete the observer for the given Application or Cluster. If no observer
    is started, do nothing.

    Args:
        controller (KubernetesController): the controller for which the observer will be
            removed from the list of working observers.
        resource (krake.data.kubernetes.Application): the Application whose observer
        will be stopped or
        resource (krake.data.kubernetes.Cluster): the Cluster whose observer will be
        stopped.

    """
    if resource.metadata.uid not in controller.observers:
        return

    logger.debug(f"Stop observer for {resource.kind} %r", resource.metadata.name)
    _, task = controller.observers.pop(resource.metadata.uid)
    task.cancel()

    with suppress(asyncio.CancelledError):
        await task


@listen.on(HookType.ApplicationToscaTranslation)
async def translate_tosca(controller, app, **kwargs):
    """Translate a TOSCA template or CSAR archive into a Kubernetes manifest.

    Args:
        controller (KubernetesController): the controller that handles the application
            resource.
        app (krake.data.kubernetes.Application): the Application that could be defined
            by a TOSCA template or a CSAR archive.

    Raises:
        ToscaParserException: If the given application does not contain
         at least one from the following:
         - Kubernetes manifest
         - TOSCA template
         - CSAR archive

    """
    if app.spec.manifest:
        return

    if not app.spec.tosca and not app.spec.csar:
        raise ToscaParserException(
            "Application should be defined by a Kubernetes manifest,"
            " a TOSCA template or a CSAR archive: %r",
            app,
        )
    app.status.state = ApplicationState.TRANSLATING
    await controller.kubernetes_api.update_application_status(
        namespace=app.metadata.namespace, name=app.metadata.name, body=app
    )

    if app.spec.tosca and isinstance(app.spec.tosca, dict):

        manifest = ToscaParser.from_dict(app.spec.tosca).translate_to_manifests()
    else:
        manifest = ToscaParser.from_url(
            app.spec.tosca or app.spec.csar
        ).translate_to_manifests()

    app.spec.manifest = manifest
    await controller.kubernetes_api.update_application(
        namespace=app.metadata.namespace, name=app.metadata.name, body=app
    )


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

    client_cert.sign(intermediate_key_src, "sha256")

    cert_dump = crypto.dump_certificate(crypto.FILETYPE_PEM, client_cert).decode()
    key_dump = crypto.dump_privatekey(crypto.FILETYPE_PEM, client_key).decode()
    return CertificatePair(cert=cert_dump, key=key_dump)


def generate_default_observer_schema(app):
    """Generate the default observer schema for each Kubernetes resource present in
    ``spec.manifest`` for which a custom observer schema hasn't been specified.

    Args:
        app (krake.data.kubernetes.Application): The application for which to generate a
            default observer schema
    """

    app.status.mangled_observer_schema = deepcopy(app.spec.observer_schema)

    for resource_manifest in app.spec.manifest:
        try:
            get_kubernetes_resource_idx(
                app.status.mangled_observer_schema, resource_manifest
            )

        except IndexError:
            # Only create a default observer schema, if a custom observer schema hasn't
            # been set by the user.
            app.status.mangled_observer_schema.append(
                generate_default_observer_schema_dict(
                    resource_manifest,
                    first_level=True,
                )
            )


def generate_default_observer_schema_dict(manifest_dict, first_level=False):
    """Together with :func:``generate_default_observer_schema_list``, this function is
    called recursively to generate part of a default ``observer_schema`` from part of a
    Kubernetes resource, defined respectively by ``manifest_dict`` or ``manifest_list``.

    Args:
        manifest_dict (dict): Partial Kubernetes resources
        first_level (bool, optional): If True, indicates that the dictionary represents
            the whole observer schema of a Kubernetes resource

    Returns:
        dict: Generated partial observer_schema

    This function creates a new dictionary from ``manifest_dict`` and replaces all
    non-list and non-dict values by ``None``.

    In case of ``first_level`` dictionary (i.e. complete ``observer_schema`` for a
    resource), the values of the identifying fields are copied from the manifest file.

    """
    observer_schema_dict = {}

    for key, value in manifest_dict.items():

        if isinstance(value, dict):
            observer_schema_dict[key] = generate_default_observer_schema_dict(value)

        elif isinstance(value, list):
            observer_schema_dict[key] = generate_default_observer_schema_list(value)

        else:
            observer_schema_dict[key] = None

    if first_level:
        observer_schema_dict["apiVersion"] = manifest_dict["apiVersion"]
        observer_schema_dict["kind"] = manifest_dict["kind"]
        observer_schema_dict["metadata"]["name"] = manifest_dict["metadata"]["name"]

        if (
            "spec" in manifest_dict
            and "type" in manifest_dict["spec"]
            and manifest_dict["spec"]["type"] == "LoadBalancer"
        ):
            observer_schema_dict["status"] = {"load_balancer": {"ingress": None}}

    return observer_schema_dict


def generate_default_observer_schema_list(manifest_list):
    """Together with :func:``generate_default_observer_schema_dict``, this function is
    called recursively to generate part of a default ``observer_schema`` from part of a
    Kubernetes resource, defined respectively by ``manifest_list`` or ``manifest_dict``.

    Args:
        manifest_list (list): Partial Kubernetes resources

    Returns:
        list: Generated partial observer_schema

    This function creates a new list from ``manifest_list`` and replaces all non-list
    and non-dict elements by ``None``.

    Additionally, it generates the default list control dictionary, using the current
    length of the list as default minimum and maximum values.

    """
    observer_schema_list = []

    for value in manifest_list:

        if isinstance(value, dict):
            observer_schema_list.append(generate_default_observer_schema_dict(value))

        elif isinstance(value, list):
            observer_schema_list.append(generate_default_observer_schema_list(value))

        else:
            observer_schema_list.append(None)

    observer_schema_list.append(
        {
            "observer_schema_list_min_length": len(manifest_list),
            "observer_schema_list_max_length": len(manifest_list),
        }
    )

    return observer_schema_list


@listen.on(HookType.ApplicationMangling)
async def complete(app, api_endpoint, ssl_context, config):
    """Execute application complete hook defined by :class:`Complete`.
    Hook mangles given application and injects complete hooks variables.

    Application complete hook is disabled by default.
    User enables this hook by the --hook-complete argument in rok cli.

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

    app.status.complete_token = (
        app.status.complete_token if app.status.complete_token else token_urlsafe()
    )

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
        env_url=config.complete.env_url,
    )
    hook.mangle_app(
        app.metadata.name,
        app.metadata.namespace,
        app.status.complete_token,
        app.status.last_applied_manifest,
        config.complete.intermediate_src,
        generated_cert,
        app.status.mangled_observer_schema,
        "complete",
    )


@listen.on(HookType.ApplicationMangling)
async def shutdown(app, api_endpoint, ssl_context, config):
    """Executes an application shutdown hook defined by :class:`Shutdown`.
    The hook mangles the given application and injects shutdown hooks variables.

    Application shutdown hook is disabled by default.
    User enables this hook by the --hook-shutdown argument in rok cli.

    Args:
        app (krake.data.kubernetes.Application): Application object processed
            when the hook is called
        api_endpoint (str): the given API endpoint
        ssl_context (ssl.SSLContext): SSL context to communicate with the API endpoint
        config (krake.data.config.HooksConfiguration): Shutdown hook
            configuration.

    """
    if "shutdown" not in app.spec.hooks:
        return

    # Use the endpoint of the API only if the external endpoint has not been set.
    if config.shutdown.external_endpoint:
        api_endpoint = config.shutdown.external_endpoint

    app.status.shutdown_token = (
        app.status.shutdown_token if app.status.shutdown_token else token_urlsafe()
    )

    # Generate only once the certificate and key for a specific Application
    generated_cert = CertificatePair(
        cert=app.status.shutdown_cert, key=app.status.shutdown_key
    )
    if ssl_context and generated_cert == (None, None):
        generated_cert = generate_certificate(config.shutdown)
        app.status.shutdown_cert = generated_cert.cert
        app.status.shutdown_key = generated_cert.key

    hook = Shutdown(
        api_endpoint,
        ssl_context,
        hook_user=config.shutdown.hook_user,
        cert_dest=config.shutdown.cert_dest,
        env_token=config.shutdown.env_token,
        env_url=config.shutdown.env_url,
    )
    hook.mangle_app(
        app.metadata.name,
        app.metadata.namespace,
        app.status.shutdown_token,
        app.status.last_applied_manifest,
        config.shutdown.intermediate_src,
        generated_cert,
        app.status.mangled_observer_schema,
        "shutdown",
    )


@listen.on(HookType.ResourcePreDelete)
async def pre_shutdown(controller, app, **kwargs):
    """

    Args:
        app (krake.data.kubernetes.Application): Application object processed
            when the hook is called
    """
    if "shutdown" not in app.spec.hooks:
        return

    return


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


class Hook(object):

    hook_resources = ()

    ca_name = "ca-bundle.pem"
    cert_name = "cert.pem"
    key_name = "key.pem"

    def __init__(
        self, api_endpoint, ssl_context, hook_user, cert_dest, env_token, env_url
    ):
        self.api_endpoint = api_endpoint
        self.ssl_context = ssl_context
        self.hook_user = hook_user
        self.cert_dest = cert_dest
        self.env_token = env_token
        self.env_url = env_url

    def mangle_app(
        self,
        name,
        namespace,
        token,
        last_applied_manifest,
        intermediate_src,
        generated_cert,
        mangled_observer_schema,
        hook_type="",
    ):
        """Mangle a given application and inject complete hook resources and
        sub-resources into the :attr:`last_applied_manifest` object by :meth:`mangle`.
        Also mangle the observer_schema as new resources and sub-resources should
        be observed.

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
            mangled_observer_schema (list): Observed fields
            hook_type (str, optional): Name of the hook the app should be mangled for

        """

        secret_certs_name = "-".join([name, "krake", hook_type, "secret", "certs"])
        secret_token_name = "-".join([name, "krake", hook_type, "secret", "token"])
        volume_name = "-".join([name, "krake", hook_type, "volume"])
        ca_certs = (
            self.ssl_context.get_ca_certs(binary_form=True)
            if self.ssl_context
            else None
        )

        # Extract all different namespaces
        # FIXME: too many assumptions here: do we create one ConfigMap for each
        #  namespace?
        resource_namespaces = {
            resource["metadata"].get("namespace", "default")
            for resource in last_applied_manifest
        }

        hook_resources = []
        hook_sub_resources = []
        if ca_certs:
            hook_resources.extend(
                [
                    self.secret_certs(
                        secret_certs_name,
                        resource_namespace,
                        intermediate_src=intermediate_src,
                        generated_cert=generated_cert,
                        ca_certs=ca_certs,
                    )
                    for resource_namespace in resource_namespaces
                ]
            )
            hook_sub_resources.extend(
                [*self.volumes(secret_certs_name, volume_name, self.cert_dest)]
            )

        hook_resources.extend(
            [
                self.secret_token(
                    secret_token_name,
                    name,
                    namespace,
                    resource_namespace,
                    self.api_endpoint,
                    token,
                )
                for resource_namespace in resource_namespaces
            ]
        )
        hook_sub_resources.extend(
            [
                *self.env_vars(secret_token_name),
            ]
        )

        self.mangle(
            hook_resources,
            last_applied_manifest,
            mangled_observer_schema,
        )
        self.mangle(
            hook_sub_resources,
            last_applied_manifest,
            mangled_observer_schema,
            is_sub_resource=True,
        )

    def mangle(
        self,
        items,
        last_applied_manifest,
        mangled_observer_schema,
        is_sub_resource=False,
    ):
        """Mangle applications desired state with custom hook resources or
        sub-resources.

        Example:
            .. code:: python

            last_applied_manifest = [
                {
                    'apiVersion': 'v1',
                    'kind': 'Pod',
                    'metadata': {'name': 'test', 'namespace': 'default'},
                    'spec': {'containers': [{'name': 'test'}]}
                }
            ]
            mangled_observer_schema = [
                {
                    'apiVersion': 'v1',
                    'kind': 'Pod',
                    'metadata': {'name': 'test', 'namespace': 'default'},
                    'spec': {
                        'containers': [
                            {'name': None},
                            {
                                'observer_schema_list_max_length': 1,
                                'observer_schema_list_min_length': 1,
                            },
                        ]
                    },
                }
            ]
            hook_resources = [
                {
                    'apiVersion': 'v1',
                    'kind': 'Secret',
                    'metadata': {'name': 'sct', 'namespace': 'default'}
                }
            ]
            hook_sub_resources = [
                SubResource(
                    group='env', name='env', body={'name': 'test', 'value': 'test'},
                    path=(('spec', 'containers'),)
                )
            ]

            mangle(
                hook_resources,
                last_applied_manifest,
                mangled_observer_schema,
            )
            mangle(
                hook_sub_resources,
                last_applied_manifest,
                mangled_observer_schema,
                is_sub_resource=True
            )

            assert last_applied_manifest == [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "test", 'namespace': 'default'},
                    "spec": {
                        "containers": [
                            {
                                "name": "test",
                                "env": [{"name": "test", "value": "test"}]
                            }
                        ]
                    },
                },
                {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "sct"}},
            ]

            assert mangled_observer_schema == [
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "test", "namespace": None},
                    "spec": {
                        "containers": [
                            {
                                "name": None,
                                "env": [
                                    {"name": None, "value": None},
                                    {
                                        "observer_schema_list_max_length": 1,
                                        "observer_schema_list_min_length": 1,
                                    },
                                ],
                            },
                            {
                                "observer_schema_list_max_length": 1,
                                "observer_schema_list_min_length": 1,
                            },
                        ]
                    },
                },
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": "sct", "namespace": None},
                },
            ]

        Args:
            items (list[SubResource]): Custom hook resources or sub-resources
            last_applied_manifest (list): Application resources
            mangled_observer_schema (list): Observed resources
            is_sub_resource (bool, optional): if False, the function only extend the
                list of Kubernetes resources defined in :attr:`last_applied_manifest`
                with new hook resources. Otherwise, the function injects each new hook
                sub-resource into the :attr:`last_applied_manifest` object
                sub-resources. Defaults to False.

        """

        if not items:
            return

        if not is_sub_resource:
            last_applied_manifest.extend(items)
            for sub_resource in items:
                # Generate the default observer schema for each resource
                mangled_observer_schema.append(
                    generate_default_observer_schema_dict(
                        sub_resource,
                        first_level=True,
                    )
                )
            return

        def inject(sub_resource, sub_resource_to_mangle, observed_resource_to_mangle):
            """Inject a hooks defined sub-resource into a Kubernetes sub-resource.

            Args:
                sub_resource (SubResource): Hook sub-resource that needs to be injected
                    into :attr:`last_applied_manifest`
                sub_resource_to_mangle (object): Kubernetes sub-resources from
                    :attr:`last_applied_manifest` which need to be processed
                observed_resource_to_mangle (dict): partial mangled_observer_schema
                    corresponding to the Kubernetes sub-resource.

            Raises:
                InvalidManifestError: if the sub-resource which will be mangled is not a
                    list or a dict.

            """

            # Create sub-resource group if not present in the Kubernetes sub-resource
            if sub_resource.group not in sub_resource_to_mangle:
                # FIXME: This assumes the subresource group contains a list
                sub_resource_to_mangle.update({sub_resource.group: []})

            # Create sub-resource group if not present in the observed fields
            if sub_resource.group not in observed_resource_to_mangle:
                observed_resource_to_mangle.update(
                    {
                        sub_resource.group: [
                            {
                                "observer_schema_list_min_length": 0,
                                "observer_schema_list_max_length": 0,
                            }
                        ]
                    }
                )

            # Inject sub-resource
            # If sub-resource name is already there update it, if not, append it
            if sub_resource.name in [
                g["name"] for g in sub_resource_to_mangle[sub_resource.group]
            ]:
                # FIXME: Assuming we are dealing with a list
                for idx, item in enumerate(sub_resource_to_mangle[sub_resource.group]):
                    if item["name"]:
                        if hasattr(item, "body"):
                            sub_resource_to_mangle[item.group][idx] = item["body"]
            else:
                sub_resource_to_mangle[sub_resource.group].append(sub_resource.body)

            # Make sure the value is observed
            if sub_resource.name not in [
                g["name"] for g in observed_resource_to_mangle[sub_resource.group][:-1]
            ]:
                observed_resource_to_mangle[sub_resource.group].insert(
                    -1, generate_default_observer_schema_dict(sub_resource.body)
                )
                observed_resource_to_mangle[sub_resource.group][-1][
                    "observer_schema_list_min_length"
                ] += 1
                observed_resource_to_mangle[sub_resource.group][-1][
                    "observer_schema_list_max_length"
                ] += 1

        for resource in last_applied_manifest:
            # Complete hook is applied only on defined Kubernetes resources
            if resource["kind"] not in self.hook_resources:
                continue

            for sub_resource in items:
                sub_resources_to_mangle = None
                idx_observed = get_kubernetes_resource_idx(
                    mangled_observer_schema, resource
                )
                for keys in sub_resource.path:
                    try:
                        sub_resources_to_mangle = reduce(getitem, keys, resource)
                    except KeyError:
                        continue

                    break

                # Create the path to the observed sub-resource, if it doesn't yet exist
                try:
                    observed_sub_resources = reduce(
                        getitem, keys, mangled_observer_schema[idx_observed]
                    )
                except KeyError:
                    Complete.create_path(
                        mangled_observer_schema[idx_observed], list(keys)
                    )
                    observed_sub_resources = reduce(
                        getitem, keys, mangled_observer_schema[idx_observed]
                    )

                if isinstance(sub_resources_to_mangle, list):
                    for idx, sub_resource_to_mangle in enumerate(
                        sub_resources_to_mangle
                    ):

                        # Ensure that each element of the list is observed.
                        idx_observed = idx
                        if idx >= len(observed_sub_resources[:-1]):
                            idx_observed = len(observed_sub_resources[:-1])
                            # FIXME: Assuming each element of the list contains a
                            # dictionary, therefore initializing new elements with an
                            # empty dict
                            observed_sub_resources.insert(-1, {})
                        observed_sub_resource = observed_sub_resources[idx_observed]

                        # FIXME: This is assuming a list always contains dict
                        inject(
                            sub_resource, sub_resource_to_mangle, observed_sub_resource
                        )

                elif isinstance(sub_resources_to_mangle, dict):
                    inject(
                        sub_resource, sub_resources_to_mangle, observed_sub_resources
                    )

                else:
                    message = (
                        f"The sub-resource to mangle {sub_resources_to_mangle!r} has an"
                        "invalid type, should be in '[dict, list]'"
                    )
                    raise InvalidManifestError(message)

    @staticmethod
    def attribute_map(obj):
        """Convert a Kubernetes object to dict based on its attribute mapping

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

    @staticmethod
    def create_path(mangled_observer_schema, keys):
        """Create the path to the observed field in the observer schema.

        When a sub-resource is mangled, it should be observed. This function creates
        the path to the subresource to observe.

        Args:
            mangled_observer_schema (dict): Partial observer schema of a resource
            keys (list): list of keys forming the path to the sub-resource to
                observe

        FIXME: This assumes we are only adding keys to dict. We don't consider lists

        """

        # Unpack the first key first, as it contains the base directory
        key = keys.pop(0)

        # If the key is the last of the list, we reached the end of the path.
        if len(keys) == 0:
            mangled_observer_schema[key] = None
            return

        if key not in mangled_observer_schema:
            mangled_observer_schema[key] = {}
        Hook.create_path(mangled_observer_schema[key], keys)

    def secret_certs(
        self,
        secret_name,
        namespace,
        ca_certs=None,
        intermediate_src=None,
        generated_cert=None,
    ):
        """Create a complete hooks secret resource.

        Complete hook secret stores Krake CAs and client certificates to communicate
        with the Krake API.

        Args:
            secret_name (str): Secret name
            namespace (str): Kubernetes namespace where the Secret will be created.
            ca_certs (list): Krake CA list
            intermediate_src (str): content of the certificate that is used to sign new
                certificates for the complete hook.
            generated_cert (CertificatePair): tuple that contains the content of the
                new signed certificate for the Application, and the content of its
                corresponding key.

        Returns:
            dict: complete hook secret resource

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
            self.ca_name: self._encode_to_64(ca_certs_pem),
            self.cert_name: self._encode_to_64(generated_cert.cert),
            self.key_name: self._encode_to_64(generated_cert.key),
        }
        return self.secret(secret_name, data, namespace)

    def secret_token(
        self, secret_name, name, namespace, resource_namespace, api_endpoint, token
    ):
        """Create a hooks secret resource.

        The hook secret stores Krake authentication token
        and hook URL for given application.

        Args:
            secret_name (str): Secret name
            name (str): Application name
            namespace (str): Application namespace
            resource_namespace (str): Kubernetes namespace where the
                Secret will be created.
            api_endpoint (str): Krake API endpoint
            token (str): Complete hook authentication token

        Returns:
            dict: complete hook secret resource

        """
        pass

    def volumes(self, secret_name, volume_name, mount_path):
        """Create complete hooks volume and volume mount sub-resources

        Complete hook volume gives access to hook's secret, which stores
        Krake CAs and client certificates to communicate with the Krake API.
        Complete hook volume mount puts the volume into the application

        Args:
            secret_name (str): Secret name
            volume_name (str): Volume name
            mount_path (list): Volume mount path

        Returns:
            list: List of complete hook volume and volume mount sub-resources

        """
        volume = V1Volume(name=volume_name, secret={"secretName": secret_name})
        volume_mount = V1VolumeMount(name=volume_name, mount_path=mount_path)
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
    def _encode_to_64(string):
        """Compute the base 64 encoding of a string.

        Args:
            string (str): the string to encode.

        Returns:
            str: the result of the encoding.

        """
        return b64encode(string.encode()).decode()

    def secret(self, secret_name, secret_data, namespace, _type="Opaque"):
        """Create a secret resource.

        Args:
            secret_name (str): Secret name
            secret_data (dict): Secret data
            namespace (str): Kubernetes namespace where the Secret will be created.
            _type (str, optional): Secret type. Defaults to Opaque.

        Returns:
            dict: secret resource

        """
        return self.attribute_map(
            V1Secret(
                api_version="v1",
                kind="Secret",
                data=secret_data,
                metadata={"name": secret_name, "namespace": namespace},
                type=_type,
            )
        )

    @staticmethod
    def create_hook_url(name, namespace, api_endpoint):
        """Create an applications' hook URL.
        Function needs to be specified for each hook.

        Args:
            name (str): Application name
            namespace (str): Application namespace
            api_endpoint (str): Krake API endpoint

        Returns:
            str: Application shutdown url

        """
        pass

    def env_vars(self, secret_name):
        """Create the hooks' environment variables sub-resources.
        Function needs to be specified for each hook.

        Creates hook environment variables to store Krake authentication token
        and a hook URL for the given applications.

        Args:
            secret_name (str): Secret name

        Returns:
            list: List of shutdown hook environment variables sub-resources

        """
        pass


class Complete(Hook):
    """Mangle given application and inject complete hooks variables into it.

    Hook injects a Kubernetes secret, which stores Krake authentication token
    and the Krake complete hook URL for the given application. The variables
    from Kubernetes secret are imported as environment variables
    into the application resource definition. Only resources defined in
    :args:`hook_resources` can be modified.

    Names of environment variables are defined in the application controller
    configuration file.

    If TLS is enabled on the Krake API, the complete hook injects a Kubernetes secret,
    and it's corresponding volume and volume mount definitions for the Krake CA,
    the client certificate with the right CN, and its key. The directory where the
    secret is mounted is defined in the configuration.

    Args:
        api_endpoint (str): the given API endpoint
        ssl_context (ssl.SSLContext): SSL context to communicate with the API endpoint
        cert_dest (str, optional): Path of the directory where the CA, client
            certificate and key to the Krake API will be stored.
        env_token (str, optional): Name of the environment variable, which stores Krake
            authentication token.
        env_url (str, optional): Name of the environment variable,
            which stores Krake complete hook URL.

    """

    hook_resources = ("Pod", "Deployment", "ReplicationController")

    def __init__(
        self, api_endpoint, ssl_context, hook_user, cert_dest, env_token, env_url
    ):
        super().__init__(
            api_endpoint, ssl_context, hook_user, cert_dest, env_token, env_url
        )
        self.env_url = env_url

    def secret_token(
        self, secret_name, name, namespace, resource_namespace, api_endpoint, token
    ):
        """Create complete hooks secret resource.

        Complete hook secret stores Krake authentication token
        and complete hook URL for given application.

        Args:
            secret_name (str): Secret name
            name (str): Application name
            namespace (str): Application namespace
            resource_namespace (str): Kubernetes namespace where the
                Secret will be created.
            api_endpoint (str): Krake API endpoint
            token (str): Complete hook authentication token

        Returns:
            dict: complete hook secret resource

        """
        complete_url = self.create_hook_url(name, namespace, api_endpoint)
        data = {
            self.env_token.lower(): self._encode_to_64(token),
            self.env_url.lower(): self._encode_to_64(complete_url),
        }
        return self.secret(secret_name, data, resource_namespace)

    @staticmethod
    def create_hook_url(name, namespace, api_endpoint):
        """Create an applications' complete URL.

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

    def env_vars(self, secret_name):
        """Create complete hooks environment variables sub-resources

        Create complete hook environment variables store Krake authentication token
        and complete hook URL for given application.

        Args:
            secret_name (str): Secret name

        Returns:
            list: List of complete hook environment variables sub-resources

        """
        sub_resources = []

        env_token = V1EnvVar(
            name=self.env_token,
            value_from=self.attribute_map(
                V1EnvVarSource(
                    secret_key_ref=self.attribute_map(
                        V1SecretKeySelector(
                            name=secret_name, key=self.env_token.lower()
                        )
                    )
                )
            ),
        )
        env_url = V1EnvVar(
            name=self.env_url,
            value_from=self.attribute_map(
                V1EnvVarSource(
                    secret_key_ref=self.attribute_map(
                        V1SecretKeySelector(name=secret_name, key=self.env_url.lower())
                    )
                )
            ),
        )

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


class Shutdown(Hook):
    """Mangle given application and inject shutdown hooks variables into it.

    Hook injects a Kubernetes secret, which stores Krake authentication token
    and the Krake complete hook URL for the given application. The variables
    from the Kubernetes secret are imported as environment variables
    into the application resource definition. Only resources defined in
    :args:`hook_resources` can be modified.

    Names of environment variables are defined in the application controller
    configuration file.

    If TLS is enabled on the Krake API, the shutdown hook injects a Kubernetes secret,
    and it's corresponding volume and volume mount definitions for the Krake CA,
    the client certificate with the right CN, and its key. The directory where the
    secret is mounted is defined in the configuration.

    Args:
        api_endpoint (str): the given API endpoint
        ssl_context (ssl.SSLContext): SSL context to communicate with the API endpoint
        cert_dest (str, optional): Path of the directory where the CA, client
            certificate and key to the Krake API will be stored.
        env_token (str, optional): Name of the environment variable, which stores Krake
            authentication token.
        env_url (str, optional): Name of the environment variable,
            which stores Krake complete hook URL.

    """

    hook_resources = ("Pod", "Deployment", "ReplicationController")

    def __init__(
        self, api_endpoint, ssl_context, hook_user, cert_dest, env_token, env_url
    ):
        super().__init__(
            api_endpoint, ssl_context, hook_user, cert_dest, env_token, env_url
        )
        self.env_url = env_url

    def secret_token(
        self, secret_name, name, namespace, resource_namespace, api_endpoint, token
    ):
        """Create shutdown hooks secret resource.

        Shutdown hook secret stores Krake authentication token
        and shutdown hook URL for given application.

        Args:
            secret_name (str): Secret name
            name (str): Application name
            namespace (str): Application namespace
            resource_namespace (str): Kubernetes namespace where the
                Secret will be created.
            api_endpoint (str): Krake API endpoint
            token (str): Shutdown hook authentication token

        Returns:
            dict: shutdown hook secret resource

        """
        shutdown_url = self.create_hook_url(name, namespace, api_endpoint)
        data = {
            self.env_token.lower(): self._encode_to_64(token),
            self.env_url.lower(): self._encode_to_64(shutdown_url),
        }
        return self.secret(secret_name, data, resource_namespace)

    @staticmethod
    def create_hook_url(name, namespace, api_endpoint):
        """Create an applications' shutdown URL.

        Args:
            name (str): Application name
            namespace (str): Application namespace
            api_endpoint (str): Krake API endpoint

        Returns:
            str: Application shutdown url

        """
        api_url = URL(api_endpoint)
        return str(
            api_url.with_path(
                f"/kubernetes/namespaces/{namespace}/applications/{name}/shutdown"
            )
        )

    def env_vars(self, secret_name):
        """Create shutdown hooks environment variables sub-resources.

        Creates shutdown hook environment variables to store Krake authentication token
        and a shutdown hook URL for given applications.

        Args:
            secret_name (str): Secret name

        Returns:
            list: List of shutdown hook environment variables sub-resources

        """
        sub_resources = []

        env_resources = []

        env_token = V1EnvVar(
            name=self.env_token,
            value_from=self.attribute_map(
                V1EnvVarSource(
                    secret_key_ref=self.attribute_map(
                        V1SecretKeySelector(
                            name=secret_name, key=self.env_token.lower()
                        )
                    )
                )
            ),
        )
        env_resources.append(env_token)

        env_url = V1EnvVar(
            name=self.env_url,
            value_from=self.attribute_map(
                V1EnvVarSource(
                    secret_key_ref=self.attribute_map(
                        V1SecretKeySelector(name=secret_name, key=self.env_url.lower())
                    )
                )
            ),
        )
        env_resources.append(env_url)

        for env in env_resources:
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
