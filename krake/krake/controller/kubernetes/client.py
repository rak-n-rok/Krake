import logging

from kubernetes_asyncio.config.kube_config import KubeConfigLoader
from kubernetes_asyncio.client import (
    ApiClient,
    CoreV1Api,
    AppsV1Api,
    Configuration,
    ApiextensionsV1beta1Api,
    CustomObjectsApi,
)
from kubernetes_asyncio.client.rest import ApiException

from krake.controller import ControllerError
from krake.data.core import ReasonCode
from krake.utils import camel_to_snake_case, cached_property

logger = logging.getLogger(__name__)


class InvalidResourceError(ControllerError):
    """Raised in case of invalid kubernetes resource definition."""

    code = ReasonCode.INVALID_RESOURCE


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
                raise InvalidResourceError(str(err))

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

    def _get_immutables(self, resource):
        """From a resource manifest, look for the kind, name and namespace of the
        resource. If the latter is not present, the default namespace of the cluster is
        used instead.

        Args:
            resource (dict[str, Any]): the manifest file translated in dict of the
                resource from which the fields will be extracted.

        Returns:
            (str, str, str): the kind, name and namespace of the resource.

        Raises:
            InvalidResourceError: if the kind or the name is not present.

        """
        metadata = resource["metadata"]
        namespace = metadata.get("namespace", self.default_namespace)

        try:
            kind = resource["kind"]
        except KeyError:
            raise InvalidResourceError('Resource must define "kind"')

        try:
            name = metadata["name"]
        except KeyError:
            raise InvalidResourceError('Resource must define "metadata.name"')

        return kind, name, namespace

    async def apply(self, resource):
        """Apply the given resource on the cluster using its internal data as reference.

        Args:
            resource (dict): the resource to create, as a manifest file translated in
                dict.

        Returns:
            object: response from the cluster as given by the Kubernetes client.

        """
        kind, name, namespace = self._get_immutables(resource)

        resource_api = await self.get_resource_api(kind)

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

        """
        kind, name, namespace = self._get_immutables(resource)

        resource_api = await self.get_resource_api(kind)
        try:
            resp = await resource_api.delete(kind, name=name, namespace=namespace)
        except ApiException as err:
            if err.status == 404:
                logger.debug("%s already deleted", kind)
                return
            raise

        self.log_response(resp, kind, action="deleted")

        return resp

    @property
    def default_namespace(self):
        """From the kubeconfig file, get the default Kubernetes namespace where the
        resources will be created. If no namespace is specified, "default" will be used.

        Returns:
            str: the default namespace in the kubeconfig file.

        """
        return self.kubeconfig["contexts"][0]["context"].get("namespace", "default")
