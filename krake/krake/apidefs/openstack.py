from krake.data.openstack import Project, ProjectList, MagnumCluster, MagnumClusterList
from .definitions import ApiDef, subresource, operation, Scope, ListQuery


openstack = ApiDef("openstack")


@openstack.resource
class ProjectResource:
    singular = "Project"
    plural = "Projects"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/openstack/namespaces/{namespace}/projects"
        body = Project
        response = Project

    @operation
    class Read:
        method = "GET"
        path = "/openstack/namespaces/{namespace}/projects/{name}"
        response = Project

    @operation
    class List(ListQuery):
        method = "GET"
        path = "/openstack/namespaces/{namespace}/projects"
        response = ProjectList

    @operation
    class ListAll(ListQuery):
        method = "GET"
        path = "/openstack/projects"
        response = ProjectList

    @operation
    class Update:
        method = "PUT"
        path = "/openstack/namespaces/{namespace}/projects/{name}"
        body = Project
        response = Project

    @operation
    class Delete:
        method = "DELETE"
        path = "/openstack/namespaces/{namespace}/projects/{name}"
        response = Project

    @subresource
    class Status:
        @operation
        class Update:
            method = "PUT"
            path = "/openstack/namespaces/{namespace}/projects/{name}/status"
            body = Project
            response = Project


@openstack.resource
class MagnumClusterResource:
    singular = "MagnumCluster"
    plural = "MagnumClusters"
    scope = Scope.NAMESPACED

    @operation
    class Create:
        method = "POST"
        path = "/openstack/namespaces/{namespace}/magnumclusters"
        body = MagnumCluster
        response = MagnumCluster

    @operation
    class Read:
        method = "GET"
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}"
        response = MagnumCluster

    @operation
    class List(ListQuery):
        method = "GET"
        path = "/openstack/namespaces/{namespace}/magnumclusters"
        response = MagnumClusterList

    @operation
    class ListAll(ListQuery):
        method = "GET"
        path = "/openstack/magnumclusters"
        response = MagnumClusterList

    @operation
    class Update:
        method = "PUT"
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}"
        body = MagnumCluster
        response = MagnumCluster

    @operation
    class Delete:
        method = "DELETE"
        path = "/openstack/namespaces/{namespace}/magnumclusters/{name}"
        response = MagnumCluster

    @subresource
    class Status:
        @operation
        class Update:
            method = "PUT"
            path = "/openstack/namespaces/{namespace}/magnumclusters/{name}/status"
            body = MagnumCluster
            response = MagnumCluster
