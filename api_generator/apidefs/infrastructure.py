from krake.api.helpers import ListQuery
from krake.data.infrastructure import (
    GlobalInfrastructureProvider,
    GlobalInfrastructureProviderList,
    InfrastructureProvider,
    InfrastructureProviderList,
    GlobalCloud,
    GlobalCloudList,
    Cloud,
    CloudList,
)

from .definitions import Scope, ApiDef, operation, subresource


infrastructure = ApiDef("infrastructure")


@infrastructure.resource
class GlobalInfrastructureProviderResource:
    singular = "GlobalInfrastructureProvider"
    plural = "GlobalInfrastructureProviders"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/infrastructure/globalinfrastructureproviders"
        body = GlobalInfrastructureProvider
        response = GlobalInfrastructureProvider

    @operation
    class Read:
        method = "GET"
        path = "/infrastructure/globalinfrastructureproviders/{name}"
        response = GlobalInfrastructureProvider

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/infrastructure/globalinfrastructureproviders"
        response = GlobalInfrastructureProviderList

    @operation
    class Update:
        method = "PUT"
        path = "/infrastructure/globalinfrastructureproviders/{name}"
        body = GlobalInfrastructureProvider
        response = GlobalInfrastructureProvider

    @operation
    class Delete:
        method = "DELETE"
        path = "/infrastructure/globalinfrastructureproviders/{name}"
        response = GlobalInfrastructureProvider


@infrastructure.resource
class InfrastructureProviderResource:
    singular = "InfrastructureProvider"
    plural = "InfrastructureProviders"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders"
        body = InfrastructureProvider
        response = InfrastructureProvider

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders"
        response = InfrastructureProviderList

    @operation
    class ListAll(ListQuery):
        number = "plural"
        method = "GET"
        path = "/infrastructure/infrastructureproviders"
        response = InfrastructureProviderList

    @operation
    class Read:
        method = "GET"
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}"
        response = InfrastructureProvider

    @operation
    class Update:
        method = "PUT"
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}"
        body = InfrastructureProvider
        response = InfrastructureProvider

    @operation
    class Delete:
        method = "DELETE"
        path = "/infrastructure/namespaces/{namespace}/infrastructureproviders/{name}"
        response = InfrastructureProvider


@infrastructure.resource
class GlobalCloudResource:
    singular = "GlobalCloud"
    plural = "GlobalClouds"
    scope = Scope.NONE

    @operation
    class Create:
        method = "POST"
        path = "/infrastructure/globalclouds"
        body = GlobalCloud
        response = GlobalCloud

    @operation
    class Read:
        method = "GET"
        path = "/infrastructure/globalclouds/{name}"
        response = GlobalCloud

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/infrastructure/globalclouds"
        response = GlobalCloudList

    @operation
    class Update:
        method = "PUT"
        path = "/infrastructure/globalclouds/{name}"
        body = GlobalCloud
        response = GlobalCloud

    @operation
    class Delete:
        method = "DELETE"
        path = "/infrastructure/globalclouds/{name}"
        response = GlobalCloud

    @subresource
    class Status:
        @operation
        class Update:
            method = "PUT"
            path = "/infrastructure/globalclouds/{name}/status"
            body = GlobalCloud
            response = GlobalCloud


@infrastructure.resource
class CloudResource:
    singular = "Cloud"
    plural = "Clouds"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/infrastructure/namespaces/{namespace}/clouds"
        body = Cloud
        response = Cloud

    @operation
    class Read:
        method = "GET"
        path = "/infrastructure/namespaces/{namespace}/clouds/{name}"
        response = Cloud

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/infrastructure/namespaces/{namespace}/clouds"
        response = CloudList

    @operation
    class ListAll(ListQuery):
        number = "plural"
        method = "GET"
        path = "/infrastructure/clouds"
        response = CloudList

    @operation
    class Update:
        method = "PUT"
        path = "/infrastructure/namespaces/{namespace}/clouds/{name}"
        body = Cloud
        response = Cloud

    @operation
    class Delete:
        method = "DELETE"
        path = "/infrastructure/namespaces/{namespace}/clouds/{name}"
        response = Cloud

    @subresource
    class Status:
        @operation
        class Update:
            method = "PUT"
            path = "/infrastructure/namespaces/{namespace}/clouds/{name}/status"
            body = Cloud
            response = Cloud
