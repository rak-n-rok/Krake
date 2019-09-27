=================
Rok documentation
=================

The Rok utility has a command line interface with a few specific commands, that can be added one after the other to refer to specific elements. The general syntax is

.. code:: bash

	rok <api> <resource> <operation> <parameters>


The separate elements are:

``api`` element:
	The name of the Krake API used. Different APIs are present to handle different kind of resources. Example: ``kube`` for the Kubernetes API of Krake.

``resource`` element:
	The name of the resource managed. Each API holds one or several resources it can handle. Example: ``cluster`` for the Krake **Clusters**, which correspond to Kubernetes clusters.

``operation`` element:
	The verb used for the operation to apply. For instance ``list`` can be used to get all instances of one kind of resource, while ``delete`` can be used to remove a resource.

``parameters`` element:
	The specific argument for the current operation. For instance, for some operations, the ``-f | --format`` argument change the format of the response.


A few examples:

.. code:: bash

	$ rok kube <...>  # handle the kubernetes API resources

	$ rok kube app <...>  # handle the Application resources of the Kubernetes API

	# Create a Cluster resource with the Kubernetes API using the minikube.yaml manifest
	$ rok kube cluster create ../minikube.yaml



The ``kube`` API
================

This API can be used to manage Kubernetes clusters and start, update and delete applications on them, through Krake.

Base command: ``rok kube <...>``



The Cluster resource: ``cluster``
---------------------------------

This resource manages Krake **Cluster** resources, which needs to be registered on Krake to be used. It corresponds to a cluster on Kubernetes.

Base command: ``rok kube cluster <...>``

create
	Add a new cluster to the Kubernetes clusters registered on Krake on a specified namespace.

	``kubeconfig``: the path to the kubeconfig file that refers to the cluster to add.

	``-n | --namespace`` (optional):
		The namespace to which the Cluster has to be added. If none is given, the user namespace is selected.

list
	List all Cluster of a namespace.

	``-f | --format <format>`` (optional):
		The format of the displayed response. Three are available: YAML: ``yaml``, JSON: ``json`` or table: ``table``.

	``-n | --namespace`` (optional):
		The namespace from which the Clusters have to be listed. If none is given, the user namespace is selected.

delete
	Request the deletion of a specific Cluster from a namespace.

	``-n | --namespace`` (optional):
		The namespace from which the Cluster have to be deleted. If none is given, the user namespace is selected.


The Application resource: ``app``
---------------------------------

This resource manages Krake **Applications** resources, which need to be registered on Krake to be managed. It corresponds to a Kubernetes resource.

Base command: ``rok kube app <...>``


create
	Add a new Application to the ones registered on Krake on a specified namespace. Example:

	.. code:: bash

		rok kube app create <application_name> -f <path_to_manifest>

	``name``:
		The name of the new Application, as stored by Krake (can be arbitrary). The same name cannot be used twice in the same namespace.

	``-f | --file``:
		The path to the manifest file that describes the new Application.

	``-n | --namespace`` (optional):
		The namespace to which the Application has to be added. If none is given, the user namespace is selected.

list
	List all Applications of a namespace.

	``-f | --format <format>`` (optional):
		The format of the displayed response. Three are available: YAML: ``yaml``, JSON: ``json`` or table: ``table``.

	``-n | --namespace`` (optional):
		The namespace from which the Applications have to be listed. If none is given, the user namespace is selected.

get
	Request information about a specific Application.

	``name``:
		The name of the Application to fetch.

	``-f | --format <format>`` (optional):
		The format of the displayed response. Three are available: YAML: ``yaml``, JSON: ``json`` or table: ``table``.

	``-n | --namespace`` (optional):
		The namespace from which the Applications have to be retrieved. If none is given, the user namespace is selected.

update
	Request a change of the current state of an existing Application.

	``name``:
		The name of the Application to update.

	``-f | --file``:
		The path to the manifest file that describes the Application with the updated fields.

	``-n | --namespace`` (optional):
		The namespace from which the Applications have to be taken. If none is given, the user namespace is selected.

delete
	Request the deletion of a specific Application from a namespace.

	``name``:
		The name of the Application to delete.

	``-n | --namespace`` (optional):
		The namespace from which the Application have to be deleted. If none is given, the user namespace is selected.
