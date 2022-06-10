import logging

import requests
from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client import (
    ApiClient,
    Configuration,
    ApiextensionsV1Api,
    CustomObjectsApi,
)
from kubernetes_asyncio.client.rest import ApiException

from krake.controller import ControllerError
from krake.data.core import ReasonCode
from krake.utils import camel_to_snake_case, cached_property

logger = logging.getLogger(__name__)


class InvalidManifestError(ControllerError):
    """Raised when the manifest of a resource has an invalid structure."""

    code = ReasonCode.INVALID_RESOURCE


class InvalidCustomResourceDefinitionError(ControllerError):
    """Raised when reading a custom resource definition from a cluster where it should
    exist, and the request fails. It mostly occurs when the provided custom resource
    definition has an invalid structure or does not exist on the actual cluster.
    """

    code = ReasonCode.INVALID_CUSTOM_RESOURCE


class UnsupportedResourceError(ControllerError):
    """Raised when the Kubernetes resource is not supported by
    the Kubernetes controller.
    """

    code = ReasonCode.UNSUPPORTED_RESOURCE


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
        if hasattr(self.api, f"read_namespaced_{camel_to_snake_case(kind)}"):
            return await getattr(
                self.api, f"read_namespaced_{camel_to_snake_case(kind)}"
            )(name=name, namespace=namespace)

        if hasattr(self.api, f"read_{camel_to_snake_case(kind)}"):
            return await getattr(self.api, f"read_{camel_to_snake_case(kind)}")(
                name=name
            )

        raise UnsupportedResourceError(f"{kind} resources are not supported.")

    async def create(self, kind, body=None, namespace=None):
        if hasattr(self.api, f"create_namespaced_{camel_to_snake_case(kind)}"):
            return await getattr(
                self.api, f"create_namespaced_{camel_to_snake_case(kind)}"
            )(body=body, namespace=namespace)

        if hasattr(self.api, f"create_{camel_to_snake_case(kind)}"):
            return await getattr(self.api, f"create_{camel_to_snake_case(kind)}")(
                body=body
            )

        raise UnsupportedResourceError(f"{kind} resources are not supported.")

    async def patch(self, kind, name=None, body=None, namespace=None):
        if hasattr(self.api, f"patch_namespaced_{camel_to_snake_case(kind)}"):
            return await getattr(
                self.api, f"patch_namespaced_{camel_to_snake_case(kind)}"
            )(name=name, body=body, namespace=namespace)

        if hasattr(self.api, f"patch_{camel_to_snake_case(kind)}"):
            return await getattr(self.api, f"patch_{camel_to_snake_case(kind)}")(
                name=name, body=body
            )

        raise UnsupportedResourceError(f"{kind} resources are not supported.")

    async def delete(self, kind, name=None, namespace=None):
        if hasattr(self.api, f"delete_namespaced_{camel_to_snake_case(kind)}"):
            return await getattr(
                self.api, f"delete_namespaced_{camel_to_snake_case(kind)}"
            )(name=name, namespace=namespace)

        if hasattr(self.api, f"delete_{camel_to_snake_case(kind)}"):
            return await getattr(self.api, f"delete_{camel_to_snake_case(kind)}")(
                name=name
            )

        raise UnsupportedResourceError(f"{kind} resources are not supported.")


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
        metadata (dict): Custom resource metadata

    """

    def __init__(self, api, scope, group, version, plural, metadata):
        self.api = api
        self.scope = scope
        self.group = group
        self.version = version
        self.plural = plural
        self.metadata = metadata

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
        if self.scope == "Namespaced":
            return await self.api.delete_namespaced_custom_object(
                self.group, self.version, namespace, self.plural, name
            )
        return await self.api.delete_cluster_custom_object(
            self.group, self.version, self.plural, name
        )


class KubernetesClient(object):
    """Client for connecting to a Kubernetes cluster. This client:

    * prepares the connection based on the information stored in the cluster's
      kubeconfig file;
    * prepares the connection to a custom resource's API, if a Kubernetes resource to be
      managed relies on a Kubernetes custom resource;
    * offers two methods:
      - :meth:`apply`: apply a manifest to create or update a resource
      - :meth:`delete`: delete a resource.

    The client can be used as a context manager, with the Kubernetes client being
    deleted when leaving the context.

    Attributes:
        kubeconfig (dict): provided kubeconfig file, to connect to the cluster.
        custom_resources (list[str]): name of all custom resources that are available on
            the current cluster.
        resource_apis (dict): mapping of a Kubernetes's resource name to the API object
            of the Kubernetes client which manages it (e.g. a Pod belongs to the
            "CoreV1" API of Kubernetes, so the mapping would be "Pod" ->
            <client.CoreV1Api_instance>), wrapped in an :class:`ApiAdapter` instance.
        api_client (ApiClient): base API object created by the Kubernetes API library.

    """

    def __init__(self, kubeconfig, custom_resources=None):
        """Instantiate the client with the information from a Krake Cluster resource.

        Args:
            kubeconfig (dict): kubeconfig file of the cluster associated to the Krake
                Cluster.
            custom_resources (list[str]): ame of all custom resources that are available
                on the cluster.

        """
        self.kubeconfig = kubeconfig
        self.custom_resources = custom_resources
        self.resource_apis = None
        self.api_client = None

    @staticmethod
    def log_response(response, kind, action=None):
        """Utility function to parse a response from the Kubernetes cluster and log its
        content.

        Args:
            response (object): the response, as handed over by the Kubernetes client
                library.
            kind (str): kind of the original resource that was managed (may be different
                from the kind of the response).
            action (str): the type of action performed to get this response.

        """
        resp_log = (
            f"status={response.status!r}"
            if hasattr(response, "status")
            else f"resource={response!r}"
        )
        logger.debug(f"%s {action}. %r", kind, resp_log)

    async def __aenter__(self):
        # Load Kubernetes configuration
        loader = KubeConfigLoader(self.kubeconfig)
        config = Configuration()
        await loader.load_and_set(config)

        self.api_client = ApiClient(config)
        return self

    async def __aexit__(self, *exec):
        self.resource_apis = None
        await self.api_client.close()

    @cached_property
    async def custom_resource_apis(self):
        """Determine custom resource apis for given cluster.

        If given cluster supports custom resources, Krake determines
        apis from custom resource definitions.

        The custom resources apis are requested only once and then
        are cached by cached property decorator. This is an advantage in
        case of the application contains multiple Kubernetes custom resources
        with the same kind, but with the different content, see example.

        Example:

        .. code:: yaml

            ---
            apiVersion: stable.example.com/v1
            kind: CRD
            metadata:
                name: cdr_1
            spec:
                crdSpec: spec_1
            ---
            apiVersion: stable.example.com/v1
            kind: CRD
            metadata:
                name: cdr_2
            spec:
                crdSpec: spec_2

        Returns:
            dict: Custom resource apis

        Raises:
            InvalidCustomResourceDefinitionError: If the request for the custom resource
                definition failed.

        """
        custom_resource_apis = {}

        if not self.custom_resources:
            return custom_resource_apis

        extensions_v1_api = ApiextensionsV1Api(self.api_client)
        for custom_resource in self.custom_resources:

            try:
                # Determine scope, version, group and plural of custom resource
                # definition
                resp = await extensions_v1_api.read_custom_resource_definition(
                    custom_resource
                )
            except ApiException as err:
                raise InvalidCustomResourceDefinitionError(err)

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
                resp.metadata,
            )
        return custom_resource_apis

    async def get_resource_api(self, group, version, kind):
        """Get the Kubernetes API corresponding to the given group and version.
         If not found, look for it into the supported custom resources for the cluster.

        Args:
            group (str): group of the Kubernetes resource,
                for which the Kubernetes API should be retrieved.
            version (str): version of the Kubernetes resource,
                for which the Kubernetes API should be retrieved.
            kind (str): name of the Kubernetes resource,
                for which the Kubernetes API should be retrieved.

        Returns:
            ApiAdapter: the API adapter to use for this resource.

        Raises:
            UnsupportedResourceError: if the group and version given are not
                supported by the Controller, and given kind is not a
                supported custom resource.

        """
        # Convert group name from DNS subdomain format to
        # python class name convention.
        group = "".join(word.capitalize() for word in group.split("."))

        try:
            fcn_to_call = getattr(k8s_client, f"{group}{version.capitalize()}Api")
            return ApiAdapter(fcn_to_call(self.api_client))
        except AttributeError:
            try:
                custom_resource_apis = await self.custom_resource_apis
                return custom_resource_apis[kind]
            except KeyError:
                raise UnsupportedResourceError(
                    f"{kind} resources are not supported. "
                    f"{group}{version.capitalize()}Api not found."
                )

    @staticmethod
    def _parse_api_version(api_version):
        """Parse resource manifest api version.

        Args:
            api_version (str): Resource api version.

        Returns:
            (str, str): the group and version of the resource.

        """
        group, _, version = api_version.partition("/")
        if not version:
            version = group
            group = "core"

        # Take care for the case e.g "apiextensions.k8s.io"
        # Only replace the last instance.
        group = "".join(group.rsplit(".k8s.io", 1))

        return group, version

    def get_immutables(self, resource):
        """From a resource manifest, look for the group, version, kind, name and
        namespace of the resource.

        If the latter is not present, the default namespace of the cluster is
        used instead.

        Args:
            resource (dict[str, Any]): the manifest file translated in dict of the
                resource from which the fields will be extracted.

        Returns:
            (str, str, str, str, str): the group, version, kind, name and
                namespace of the resource.

        Raises:
            InvalidResourceError: if the apiVersion, kind or the name is not present.

        Raises:
            InvalidManifestError: if the apiVersion, kind or name is not
                present in the resource.
            ApiException: by the Kubernetes API in case of malformed content or
                error on the cluster's side.

        """
        metadata = resource["metadata"]
        namespace = metadata.get("namespace", self.default_namespace)

        try:
            group, version = self._parse_api_version(resource["apiVersion"])
        except KeyError:
            raise InvalidManifestError('Resource must define "apiVersion"')

        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidManifestError('Resource must define "kind"')

        try:
            name = metadata["name"]
        except KeyError:
            raise InvalidManifestError('Resource must define "metadata.name"')

        return group, version, kind, name, namespace

    async def apply(self, resource):
        """Apply the given resource on the cluster using its internal data as reference.

        Args:
            resource (dict): the resource to create, as a manifest file translated in
                dict.

        Returns:
            object: response from the cluster as given by the Kubernetes client.

        """
        group, version, kind, name, namespace = self.get_immutables(resource)

        resource_api = await self.get_resource_api(group, version, kind)

        try:
            resp = await resource_api.read(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status != 404:
                raise
            resp = None

        if resp is None:
            resp = await resource_api.create(kind, body=resource, namespace=namespace)
            self.log_response(resp, kind, action="created")
        else:
            resp = await resource_api.patch(
                kind, name=name, body=resource, namespace=namespace
            )
            self.log_response(resp, kind, action="patched")

        return resp

    async def delete(self, resource):
        """Delete the given resource on the cluster using its internal data as
        reference.

        Args:
            resource (dict): the resource to delete, as a manifest file translated in
                dict.

        Returns:
            kubernetes_asyncio.client.models.v1_status.V1Status: response from the
                cluster as given by the Kubernetes client.

        Raises:
            InvalidManifestError: if the kind or name is not present in the resource.
            ApiException: by the Kubernetes API in case of malformed content or
                error on the cluster's side.

        """
        group, version, kind, name, namespace = self.get_immutables(resource)

        resource_api = await self.get_resource_api(group, version, kind)
        try:
            resp = await resource_api.delete(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status == 404:
                logger.debug("%s already deleted", kind)
                return
            raise

        self.log_response(resp, kind, action="deleted")

        return resp

    async def shutdown(self, app):
        """Gracefully shutdown the given application on the cluster by calling the apps
        exposed shutdown address.

        Args:
            app (): the app to gracefully shutdown.

        Returns:
            kubernetes_asyncio.client.models.v1_status.V1Status: response from the
                cluster as given by the Kubernetes client.

        Raises:
            InvalidManifestError: if the kind or name is not present in the resource.
            ApiException: by the Kubernetes API in case of malformed content or
                error on the cluster's side.

        """

        try:
            resp = requests.put(
                "http://" + app.status.services["shutdown"] + "/shutdown"
            )
        except requests.exceptions.RequestException as err:
            if err.response is None:
                logger.debug("There was no response")
                raise
            if err.response.statuscode == 404:
                logger.debug("Resource already deleted")
                return
            raise

        return resp

    @property
    def default_namespace(self):
        """From the kubeconfig file, get the default Kubernetes namespace where the
        resources will be created. If no namespace is specified, "default" will be used.

        Returns:
            str: the default namespace in the kubeconfig file.

        """
        return self.kubeconfig["contexts"][0]["context"].get("namespace", "default")
