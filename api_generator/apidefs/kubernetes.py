from krake.api.helpers import ListQuery
from krake.data.infrastructure import CloudBinding
from krake.data.kubernetes import (
    Application,
    ApplicationList,
    Cluster,
    ClusterList,
    ClusterBinding,
    ApplicationComplete,
    ApplicationShutdown,
)
from .definitions import ApiDef, Scope, operation, subresource


kubernetes = ApiDef("kubernetes")


@kubernetes.resource
class ApplicationResource:
    singular = "Application"
    plural = "Applications"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/kubernetes/namespaces/{namespace}/applications"
        body = Application
        response = Application

    @operation
    class Read:
        method = "GET"
        path = "/kubernetes/namespaces/{namespace}/applications/{name}"
        response = Application

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/kubernetes/namespaces/{namespace}/applications"
        response = ApplicationList

    @operation
    class ListAll(ListQuery):
        number = "plural"
        method = "GET"
        path = "/kubernetes/applications"
        response = ApplicationList

    @operation
    class Update:
        method = "PUT"
        path = "/kubernetes/namespaces/{namespace}/applications/{name}"
        body = Application
        response = Application

    @operation
    class Delete:
        method = "DELETE"
        path = "/kubernetes/namespaces/{namespace}/applications/{name}"
        response = Application

    @subresource
    class Status:
        @operation
        class Update:
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/applications/{name}/status"
            body = Application
            response = Application

    @subresource
    class Binding:
        @operation
        class Update:
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/applications/{name}/binding"
            body = ClusterBinding
            response = Application

    @subresource
    class Complete:
        @operation
        class Update:
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/applications/{name}/complete"
            body = ApplicationComplete
            response = Application

    @subresource
    class Shutdown:
        @operation
        class Update:
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/applications/{name}/shutdown"
            body = ApplicationShutdown
            response = Application


@kubernetes.resource
class ClusterResource:
    singular = "Cluster"
    plural = "Clusters"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/kubernetes/namespaces/{namespace}/clusters"
        body = Cluster
        response = Cluster

    @operation
    class Read:
        method = "GET"
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}"
        response = Cluster

    @operation
    class List(ListQuery):
        number = "plural"
        method = "GET"
        path = "/kubernetes/namespaces/{namespace}/clusters"
        response = ClusterList

    @operation
    class ListAll(ListQuery):
        number = "plural"
        method = "GET"
        path = "/kubernetes/clusters"
        response = ClusterList

    @operation
    class Update:
        method = "PUT"
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}"
        body = Cluster
        response = Cluster

    @operation
    class Delete:
        method = "DELETE"
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}"
        response = Cluster

    @subresource
    class Status:
        @operation
        class Update:
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/clusters/{name}/status"
            body = Cluster
            response = Cluster

    @subresource
    class Binding:
        @operation
        class Update:
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/clusters/{name}/binding"
            body = CloudBinding
            response = Cluster
