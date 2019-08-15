from marshmallow import fields

from krake.data.kubernetes import (
    Application,
    ApplicationList,
    Cluster,
    ClusterList,
    ClusterBinding,
)
from .definitions import ApiDef, Resource, Subresource, Operation, Scope


kubernetes = ApiDef("kubernetes")


@kubernetes.resource
class ApplicationResource(Resource):
    singular = "Application"
    plural = "Applications"
    scope = Scope.NAMESPACED

    class Create(Operation):
        method = "POST"
        path = "/kubernetes/namespaces/{namespace}/applications"
        query = {"pretty": fields.Boolean(missing=False)}
        body = Application
        response = Application

    class Read(Operation):
        method = "GET"
        path = "/kubernetes/namespaces/{namespace}/applications/{name}"
        response = Application

    class List(Operation):
        method = "GET"
        query = {"watch": fields.Boolean(missing=False)}
        path = "/kubernetes/namespaces/{namespace}/applications"
        response = ApplicationList

    class ListAll(Operation):
        method = "GET"
        path = "/kubernetes/applications"
        response = ApplicationList

    class Update(Operation):
        method = "PUT"
        path = "/kubernetes/namespaces/{namespace}/applications/{name}"
        body = Application
        response = Application

    class Delete(Operation):
        method = "DELETE"
        path = "/kubernetes/namespaces/{namespace}/applications/{name}"
        response = Application

    class Status(Subresource):
        class Read(Operation):
            method = "GET"
            path = "/kubernetes/namespaces/{namespace}/applications/{name}/status"
            response = Application

        class Update(Operation):
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/applications/{name}/status"
            body = Application
            response = Application

    class Binding(Subresource):
        class Update(Operation):
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/applications/{name}/binding"
            body = ClusterBinding
            response = Application


@kubernetes.resource
class ClusterResource(Resource):
    singular = "Cluster"
    plural = "Clusters"
    scope = Scope.NAMESPACED

    class Create(Operation):
        method = "POST"
        path = "/kubernetes/namespaces/{namespace}/clusters"
        body = Cluster
        response = Cluster

    class List(Operation):
        method = "GET"
        path = "/kubernetes/namespaces/{namespace}/clusters"
        response = ClusterList

    class ListAll(Operation):
        method = "GET"
        path = "/kubernetes/clusters"
        response = ClusterList

    class Read(Operation):
        method = "GET"
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}"
        response = Cluster

    class Update(Operation):
        method = "PUT"
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}"
        body = Cluster
        response = Cluster

    class Delete(Operation):
        method = "DELETE"
        path = "/kubernetes/namespaces/{namespace}/clusters/{name}"
        response = Cluster

    class Status(Subresource):
        class Read(Operation):
            method = "GET"
            path = "/kubernetes/namespaces/{namespace}/clusters/{name}/status"
            response = Cluster

        class Update(Operation):
            method = "PUT"
            path = "/kubernetes/namespaces/{namespace}/clusters/{name}/status"
            body = Cluster
            response = Cluster
