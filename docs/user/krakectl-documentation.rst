======================
krakectl documentation
======================

The krakectl utility has a command line interface with a few specific commands, that can be added one after the other to refer to specific elements. The general syntax is

.. code:: bash

    krakectl <api> <resource> <operation> <parameters>


The separate elements are:

``api`` element:
    The name of the Krake API used. Different APIs are present to handle different kind of resources. Example: ``kube`` for the Kubernetes API of Krake.

``resource`` element:
    The name of the resource managed. Each API holds one or several resources it can handle. Example: ``cluster`` for the Krake **Clusters**, which correspond to Kubernetes clusters.

``operation`` element:
    The verb used for the operation to apply. For instance ``list`` can be used to get all instances of one kind of resource, while ``delete`` can be used to remove a resource.

``parameters`` element:
    The specific argument for the current operation. For instance, the ``-o | --output`` argument change the format of the response.


A few examples:

.. code:: bash

    $ krakectl kube <...>  # handle the kubernetes API resources

    $ krakectl kube app <...>  # handle the Application resources of the Kubernetes API

    # Register a cluster with the Kubernetes API using the minikube.yaml kubeconfig
    $ krakectl kube cluster register --kubeconfig ../minikube.yaml

    # Create a cluster with the Kubernetes API using the tosca.yaml manifest
    $ krakectl kube cluster create --file ../tosca.yaml test-cluster


The ``kube`` API
================

This API can be used to manage Kubernetes clusters and start, update and delete applications on them, through Krake.

Base command: ``krakectl kube <...>``



The Cluster resource: ``cluster``
---------------------------------

This resource manages Krake **Cluster** resources, which needs to be registered or created on Krake to be used.
It corresponds to a cluster on Kubernetes.

Base command: ``krakectl kube cluster <...>``

register
    Add an existing cluster to the Kubernetes clusters registered in Krake on a specified namespace. Example:

    .. code:: bash

        krakectl kube cluster register -k <path_to_kubeconfig_file>


    ``-k | --kubeconfig``: the path to the kubeconfig file that refers to the cluster to register.

    ``-n | --namespace`` (optional):
        The namespace to which the Cluster has to be added. If none is given, the user namespace is selected.

    ``-c | --context`` (optional):
        The name of the context to use from the kubeconfig file. Only one context can be
        chosen at a time. If not context is specified, the current context of the
        kubeconfig file is chosen.

    ``--global-metric`` (optional):
        The name and weight of of a global cluster metric in the form: ``<name> <weight>``.
        Can be specified multiple times.

    ``-m | --metric`` (optional):
        The name and weight of a cluster metric in the form: ``<name> <weight>``.
        Can be specified multiple times.

    ``-l | --label`` (optional):
        The key and the value of a cluster label in the form: ``<key>=<value>``.
        Can be specified multiple times.

    ``-R | --custom-resource`` (optional):
        The name of custom resources definition in the form: ``<plural>.<group>`` which is supported by the cluster.
        Can be specified multiple times.

create
    Add a new cluster to the Kubernetes clusters registered in Krake on a specified namespace. Example:

    .. code:: bash

        krakectl kube cluster create <cluster_name> -f <path_to_tosca_template>

    ``name``:
        The name of the new Cluster, as stored by Krake (can be arbitrary). The same name cannot be used twice in the same namespace.

    ``-f | --file``:
        The path to the TOSCA template file that describes the desired Cluster.

    ``-n | --namespace`` (optional):
        The namespace to which the Cluster has to be added. If none is given, the user namespace is selected.

    ``--inherit-metrics`` (optional):
        Enables inheritance of all metrics from the cloud the cluster is scheduled to.

    ``--global-metric`` (optional):
        The name and weight of a global cluster metric in the form: ``<name> <weight>``. Can be specified multiple times.

    ``-m | --metric`` (optional):
        The name and weight of a cluster metric in the form: ``<name> <weight>``. Can be specified multiple times.

    ``--inherit-labels`` (optional):
        Enables inheritance of all labels from the cloud the cluster is scheduled to.

    ``-l | --label`` (optional):
        The key and the value of a cluster label in the form: ``<key>=<value>``. Can be specified multiple times.

    ``-R | --custom-resource`` (optional):
        The name of custom resources definition in the form: ``<plural>.<group>`` which is supported by the cluster. Can be specified multiple times.

    ``-L | --cloud-label-constraint`` (optional):
        The name and value of a constraint for labels of the cloud in the form: ``<label> expression <value>``. The cluster will be deployed only on the cloud that matches the given label constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`.

    ``-M | --cloud-metric-constraint`` (optional):
        The name and value of a constraint for metrics of the cloud in the form: ``<label> expression <value>``. The cluster will be deployed only on the cloud that matches the given metric constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`.


    ``--backoff`` (optional): multiplier applied to backoff_delay between attempts.
            default: 1 (no backoff)

    ``backoff_delay`` (optional): delay [s] between attempts. default: 1

    ``backoff_limit`` (optional):  a maximal number of attempts. If the attempt to handle the cluster failed, it will transfer to the Cluster State DEGRADED, instead of directly going into the State OFFLINE. Default: -1 (infinite) default: -1 (infinite)

list
    List all Cluster of a namespace.

    ``-n | --namespace`` (optional):
        The namespace from which the Clusters have to be listed. If none is given, the user namespace is selected.

get
    Request information about a specific Cluster.

    ``name``:
        The name of the Cluster to fetch.
    ``-n | --namespace`` (optional):
        The namespace from which the Clusters have to be retrieved. If none is given, the user namespace is selected.

update
    Request a change of the current state of an existing Cluster.

    ``name``:
        The name of the Cluster to update.

    ``-k | --kubeconfig`` (optional):
        The path to the kubeconfig file that describes the Cluster with the updated fields.

    ``-f | --file`` (optional):
        The path to the TOSCA template file that describes the desired Cluster with the updated fields.

    ``-n | --namespace`` (optional):
        The namespace from which the Clusters have to be taken. If none is given, the user namespace is selected.

    ``-c | --context`` (optional):
        The name of the context to use from the kubeconfig file. Only one context can be chosen at a time. If not context is specified, the current context of the kubeconfig file is chosen.

    ``--global-metric`` (optional):
        The name and weight of a global cluster metric in the form: ``<name> <weight>``. Can be specified multiple times.

    ``-m | --metric`` (optional):
        The name and weight of a cluster metric in the form: ``<name> <weight>``. Can be specified multiple times. Previous metrics will be kept by default.

    ``--remove-existing-metrics`` (optional):
        Remove all existing metrics on update. If new metrics are specified with the ``--metric`` argument, they will be used instead.

    ``-l | --label`` (optional):
        The key and the value of a cluster label in the form: ``<key>=<value>``. Can be specified multiple times. Previous labels will be kept by default.

    ``--remove-existing-labels`` (optional):
        Remove all existing labels on update. If new labels are specified with the ``--label`` argument, they will be used instead.

    ``-R | --custom-resource`` (optional):
        The name of custom resources definition in the form: ``<plural>.<group>`` which is supported by the cluster. Can be specified multiple times.

    ``-L | --cloud-label-constraint`` (optional):
        The name and value of a constraint for labels of the cloud in the form: ``<label> expression <value>``. The cluster will be deployed only on the cloud that matches the given label constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`. Previous constraints will be kept by default.

    ``--remove-existing-cloud-label-constraints`` (optional):
        Remove all existing cloud label constraints on update. If new labels are specified with the ``--label`` argument, they will be used instead.

    ``-M | --cloud-metric-constraint`` (optional):
        The name and value of a constraint for metrics of the cloud in the form: ``<label> expression <value>``. The cluster will be deployed only on the cloud that matches the given metric constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`. Previous constraints will be kept by default.

    ``--remove-existing-cloud-metric-constraints`` (optional):
        Remove all existing cloud metric constraints on update. If new metrics are specified with the ``--cloud-metric-constraint`` argument, they will be used instead.

    ``--backoff`` (optional): multiplier applied to backoff_delay between attempts.
            default: 1 (no backoff)

    ``--backoff_delay`` (optional): delay [s] between attempts. default: 1

    ``--backoff_limit`` (optional):  a maximal number of attempts, default: -1 (infinite)


delete
    Request the deletion of a specific Cluster from a namespace.

    ``-n | --namespace`` (optional):
        The namespace from which the Cluster have to be deleted. If none is given, the user namespace is selected.

    ``--force`` (optional):
        Force the deletion of resources directly from the Krake Database.




The Application resource: ``app``
---------------------------------

This resource manages Krake **Applications** resources, which need to be registered on Krake to be managed. It corresponds to a Kubernetes resource.

.. tip::

  Krake is able to manage applications that are described by Kubernetes manifests files as well as by TOSCA templates or CSAR archives, see :ref:`dev/tosca:TOSCA`.


Base command: ``krakectl kube app <...>``


create
    Add a new Application to the ones registered on Krake on a specified namespace. Example:

    .. code:: bash

        krakectl kube app create <application_name> -f <path_to_manifest_or_path_to_tosca_template>

    ``name``:
        The name of the new Application, as stored by Krake (can be arbitrary). The same name cannot be used twice in the same namespace.

    ``-f | --file``:
        The path to the manifest file or the TOSCA template file that describes the new Application.

    ``-u | --url``:
        The URL of the TOSCA template file or the CSAR archive that describes the new Application.

    ``-O | --observer_schema`` (optional):
        The path to the custom observer schema file, specifying the fields of the Kubernetes resources defined in the manifest file which should be observed. If none is given, all fields defined in the manifest file are observed. The custom observer schema could be used even when the application is described by the TOSCA template or CSAR archive.

    ``-n | --namespace`` (optional):
        The namespace to which the Application has to be added. If none is given, the user namespace is selected.

    ``--hook-complete`` (optional):
        The complete hook, which allows an Application to send a completion signal to the API.

    ``--hook-shutdown`` (optional):
        The shutdown hook, which allows the graceful shutdown of the Application. Can have additional values after the argument:

        timeout [s]

        failure_strategy ('give_up' | 'delete')

        failure_retry_count

    ``-l | --label`` (optional):
        The key and the value of a cluster label in the form: ``<key>=<value>``. Can be specified multiple times. Previous labels will be kept by default.

    ``--remove-existing-labels`` (optional):
        Remove all existing labels on update. If new labels are specified with the ``--label`` argument, they will be used instead.

    ``-R | --cluster-resource-constraint`` (optional):
        The name of custom resources definition constraint in form: ``<plural>.<group>``. The application will be deployed only on the clusters with given custom definition support. Can be specified multiple times. Previous resource constraints will be kept by default.

    ``--remove-existing-resource-constraints`` (optional):
        Remove all existing resource constraints on update. If new metrics are specified with ``--cluster-resource-constraint``, they will be used instead.

    ``-L | --cluster-label-constraint`` (optional):
        The name and value of a constraint for labels of the cluster in the form: ``<label> expression <value>``. The application will be deployed only on the cluster that matches the given label constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`. Previous label constraints will be kept by default.

    ``--remove-existing-label-constraints`` (optional):
        Remove all existing label constraints on update. If new label constraints are specified with
        ``--cluster-label-constraint``, they will be used instead.

    ``-M | --cluster-metric-constraint`` (optional):
        The name and value of a constraint for metrics of the cluster in the form: ``<label> expression <value>``. The application will be deployed only on the cluster that matches the given metric constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`. Previous metric constraints will be kept by default.

    ``--remove-existing-metric-constraints`` (optional):
        Remove all existing metric constraints on update. If new metric constraints are specified with ``--cluster-metric-constraint``, they will be used instead.

    ``--backoff`` (optional):
        multiplier applied to backoff_delay between attempts to handle the application.
            default: 1 (no backoff)

    ``--backoff_delay`` (optional):
        delay [s] between attempts to handle the application.
            default: 1

    ``--backoff_limit`` (optional):
        a maximal number of attempts to handle the application. If the attempt to handle the application failed, it will transfer to the Application State DEGRADED, instead of directly going into the State FAILED.
        default: -1 (infinite)

    ``--auto-cluster-create`` (optional):
        boolean value that determines, if clusters should be automatically created when a cloud resource has a better scheduling score than all the other clusters or clouds


list
    List all Applications of a namespace.

    ``-n | --namespace`` (optional):
        The namespace from which the Applications have to be listed. If none is given, the user namespace is selected.

get
    Request information about a specific Application.

    ``name``:
        The name of the Application to fetch.
    ``-n | --namespace`` (optional):
        The namespace from which the Applications have to be retrieved. If none is given, the user namespace is selected.

update
    Request a change of the current state of an existing Application.

    ``name``:
        The name of the Application to update.

    ``-f | --file``:
        The path to the manifest file or TOSCA template file that describes the Application with the updated fields.

    ``-u | --url``:
        The URL of the TOSCA template file or the CSAR archive that describes the Application with the updated fields.

    ``-O | --observer_schema`` (optional):
        The path to the custom observer schema file, specifying the fields of the
        Kubernetes resources defined in the manifest file which should be observed. If none is given, the observer schema is not udpated.
        The custom observer schema could be used even when the application is described by the TOSCA template or CSAR archive.

    ``-n | --namespace`` (optional):
        The namespace from which the Applications have to be taken. If none is given, the user namespace is selected.

    ``--hook-complete`` (optional):
        The complete hook, which allows an Application to send a completion signal to the API.

    ``--hook-shutdown`` (optional):
        The shutdown hook, which allows the graceful shutdown of the Application. Can have additional values after the argument:

        timeout [s]

        failure_strategy ('give_up' | 'delete')

        failure_retry_count
        
    ``-R | --cluster-resource-constraint`` (optional):
        The name of custom resources definition constraint in form: ``<plural>.<group>``. The application will be deployed only on the clusters with given custom definition support. Can be specified multiple times.

    ``-L | --cluster-label-constraint`` (optional):
        The name and value of a constraint for labels of the cluster in the form: ``<label> expression <value>``. The application will be deployed only on the cluster that matches the given label constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`.

    ``-M | --cluster-metric-constraint`` (optional):
        The name and value of a constraint for metrics of the cluster in the form: ``<label> expression <value>``. The application will be deployed only on the cluster that matches the given metric constraint. Can be specified multiple times, see :ref:`dev/scheduling:Constraints`.

    ``--backoff`` (optional): multiplier applied to backoff_delay between attempts.
            default: 1 (no backoff)

    ``backoff_delay`` (optional): delay [s] between attempts. default: 1

    ``backoff_limit`` (optional):  a maximal number of attempts, default: -1 (infinite)
delete
    Request the deletion of a specific Application from a namespace.

    ``name``:
        The name of the Application to delete.

    ``-n | --namespace`` (optional):
        The namespace from which the Application have to be deleted. If none is given, the user namespace is selected.

    ``--force`` (optional):
        Force the deletion an Application directly from the Krake Database.

The ``infra`` API
=================

This API can be used to manage the following infrastructure resources:

- GlobalInfrastructureProvider
- InfrastructureProvider
- GlobalCloud
- Cloud

Base command: ``krakectl infra <...>``


The GlobalInfrastructureProvider resource: ``globalinfrastructureprovider``
---------------------------------------------------------------------------

This resource manages Krake **GlobalInfrastructureProvider** non-namespaced resources,
which needs to be registered on Krake to be used. It corresponds to an infrastructure
provider software, that is able to deploy infrastructures (e.g. Virtual machines,
Kubernetes clusters, etc.) on IaaS Cloud deployments (e.g. OpenStack, AWS, etc.).

Krake currently supports the following GlobalInfrastructureProvider software (types):

- IM_ (Infrastructure Manager) tool developed by the GRyCAP research group

Base command: ``krakectl infra globalinfrastructureprovider  <...>``
Available aliases:
- ``krakectl infra gprovider  <...>``
- ``krakectl infra gip  <...>``

.. note::

  The global resource is a non-namespaced resource that could be used by any
  (even namespaced) Krake resource. For example, the global infrastructure
  provider resource could be used by any cloud which needs to be managed
  by the infrastructure provider.

register
    Add a new GlobalInfrastructureProvider to the ones registered on Krake. Example:

    .. code:: bash

        krakectl infra gprovider register <provider_name> \
          --type <provider_type> \
          --url <provider_api_url> \
          --username <provider_api_username> \
          --password <provider_api_password>

    ``name``:
        The name of the new GlobalInfrastructureProvider, as stored by Krake (can be arbitrary).
        The same name cannot be used twice.

    ``--type``:
        The GlobalInfrastructureProvider type. Type of the infrastructure provider that will be registered
        on Krake. Currently, only IM_ infrastructure provider is supported, and valid type is: `im`.

    ``--url``:
        The GlobalInfrastructureProvider API url. Valid together with --type im.

    ``--username`` (optional):
        The GlobalInfrastructureProvider API username. Valid together with --type im.

    ``--password`` (optional):
        The GlobalInfrastructureProvider API password. Valid together with --type im.

    ``--token`` (optional):
        The GlobalInfrastructureProvider API token. Valid together with --type im.

list
    List all GlobalInfrastructureProviders.

get
    Request information about a specific GlobalInfrastructureProvider.

    ``name``:
        The name of the GlobalInfrastructureProvider to fetch.

update
    Request a change of the current state of an existing GlobalInfrastructureProvider.

    ``name``:
        The name of the GlobalInfrastructureProvider to update.

    ``--url`` (optional):
        The GlobalInfrastructureProvider API url to update. Valid together with --type im.

    ``--username`` (optional):
        The GlobalInfrastructureProvider API username to update. Valid together with --type im.

    ``--password`` (optional):
        The GlobalInfrastructureProvider API password to update. Valid together with --type im.

    ``--token`` (optional):
        The GlobalInfrastructureProvider API token to update. Valid together with --type im.

delete
    Request the deletion of a specific GlobalInfrastructureProvider.

    ``name``:
        The name of the GlobalInfrastructureProvider to delete.


The InfrastructureProvider resource: ``infrastructureprovider``
---------------------------------------------------------------

This resource manages Krake **InfrastructureProvider** namespaced resources, which needs
to be registered on Krake to be used. It corresponds to an infrastructure provider software,
that is able to deploy infrastructures (e.g. Virtual machines, Kubernetes clusters)
on IaaS Cloud deployments.

Krake currently supports the following InfrastructureProvider software (types):

- IM_ (Infrastructure Manager) tool developed by the GRyCAP research group

Base command: ``krakectl infra infrastructureprovider  <...>``

Available aliases:

- ``krakectl infra provider  <...>``
- ``krakectl infra ip  <...>``

.. note::

  This resource is a namespaced resource that could be used by the
  Krake resources from the same namespace. For example, the infrastructure
  provider resource could be used by any cloud which lives in the same
  namespace as the infrastructure provider.

register
    Add a new InfrastructureProvider to the ones registered on Krake. Example:

    .. code:: bash

        krakectl infra provider register <provider_name> \
          --type <provider_type> \
          --url <provider_api_url> \
          --username <provider_api_username> \
          --password <provider_api_password>

    ``name``:
        The name of the new InfrastructureProvider, as stored by Krake (can be arbitrary).
        The same name cannot be used twice in the same namespace.

    ``-n | --namespace`` (optional):
        The namespace to which the InfrastructureProvider have to be added. If none is given, the
        user namespace is selected.

    ``--type``:
        The InfrastructureProvider type. Type of the infrastructure provider that will be registered
        on Krake. Currently, only IM_ infrastructure provider is supported, and valid type is: `im`.

    ``--url``:
        The InfrastructureProvider API url. Valid together with --type im.

    ``--username`` (optional):
        The InfrastructureProvider API username. Valid together with --type im.

    ``--password`` (optional):
        The InfrastructureProvider API password. Valid together with --type im.

    ``--token`` (optional):
        The InfrastructureProvider API token. Valid together with --type im.

list
    List all InfrastructureProviders of a namespace.

    ``-n | --namespace`` (optional):
        The namespace from which the InfrastructureProvider have to be listed. If none is given, the
        user namespace is selected.

get
    Request information about a specific InfrastructureProvider.

    ``name``:
        The name of the InfrastructureProvider to fetch.

    ``-n | --namespace`` (optional):
        The namespace from which the InfrastructureProvider have to be retrieved. If none is given, the
        user namespace is selected.

update
    Request a change of the current state of an existing InfrastructureProvider.

    ``name``:
        The name of the InfrastructureProvider to update.

    ``-n | --namespace`` (optional):
        The namespace from which the InfrastructureProvider have to be taken. If none is given, the
        user namespace is selected.

    ``--url`` (optional):
        The InfrastructureProvider API url to update. Valid together with --type im.

    ``--username`` (optional):
        The InfrastructureProvider API username to update. Valid together with --type im.

    ``--password`` (optional):
        The InfrastructureProvider API password to update. Valid together with --type im.

    ``--token`` (optional):
        The InfrastructureProvider API token to update. Valid together with --type im.

delete
    Request the deletion of a specific InfrastructureProvider from a namespace.

    ``name``:
        The name of the InfrastructureProvider to delete.

    ``-n | --namespace`` (optional):
        The namespace from which the InfrastructureProvider have to be deleted. If none is given, the user namespace is selected.


The GlobalCloud resource: ``globalcloud``
-----------------------------------------

This resource manages Krake **GlobalCloud** non-namespaced resources,
which needs to be registered on Krake to be used. It corresponds to
an IaaS Cloud deployments (e.g. OpenStack, AWS, etc.) that will be managed
by the infrastructure provider software. GlobalCloud resource could contain
also metrics and labels, that could be used in cluster scheduling.

Krake currently supports the following GlobalCloud cloud software (types):

- OpenStack_

Base command: ``krakectl infra globalcloud  <...>``

Available aliases:

- ``krakectl infra gcloud  <...>``
- ``krakectl infra gc  <...>``

.. note::

  The global resource is a non-namespaced resource that could be used by any
  (even namespaced) Krake resource. For example, the global cloud resource
  could be used by any cluster which needs to be scheduled to some cloud.

register
    Add a new GlobalCloud to the ones registered on Krake. Example:

    .. code:: bash

        krakectl infra gcloud register <cloud_name> \
          --type <cloud_type> \
          --url <cloud_identity_service_url> \
          --username <cloud_username> \
          --password <cloud_password> \
          --project <cloud_project_name> \
          --global-infra-provider <global_infra_provider_name>

    ``name``:
        The name of the new GlobalCloud, as stored by Krake (can be arbitrary).
        The same name cannot be used twice.

    ``--type``:
        The GlobalCloud type. Type of the cloud that will be registered
        on Krake. Currently, only OpenStack_ cloud software is supported, and valid type is: `openstack`.

    ``--url``:
        URL to OpenStack identity service (Keystone). Valid together with --type openstack.

    ``--username``:
        Username or UUID of OpenStack user. Valid together with --type openstack.

    ``--password``:
        Password of OpenStack user. Valid together with --type openstack.

    ``--project``:
        Name or UUID of the OpenStack project. Valid together with --type openstack.

    ``--global-infra-provider``:
        Global infrastructure provider name for cloud management. Valid together with --type openstack.

    ``--domain-name`` (optional):
        Domain name of the OpenStack user. Valid together with --type openstack.

    ``--domain-id`` (optional):
        Domain ID of the OpenStack project. Valid together with --type openstack.

    ``--global-metric`` (optional):
        The name and weight of a global cloud metric in form: ``<name> <weight>``. Can be
        specified multiple times.

    ``-l | --label`` (optional):
        The key and the value of cloud label in form: ``<key>=<value>``. Can be
        specified multiple times.

list
    List all GlobalClouds.

get
    Request information about a specific GlobalCloud.

    ``name``:
        The name of the GlobalCloud to fetch.

update
    Request a change of the current state of an existing GlobalCloud.

    ``name``:
        The name of the GlobalCloud to update.

    ``--url`` (optional):
        URL to OpenStack identity service (Keystone) to update. Valid together with --type openstack.

    ``--username`` (optional):
        Username or UUID of OpenStack user to update. Valid together with --type openstack.

    ``--password`` (optional):
        Password of OpenStack user to update. Valid together with --type openstack.

    ``--project`` (optional):
        Name or UUID of the OpenStack project to update. Valid together with --type openstack.

    ``--global-infra-provider`` (optional):
        Global infrastructure provider name for cloud management to update. Valid together with --type openstack.

    ``--domain-name`` (optional):
        Domain name of the OpenStack user to update. Valid together with --type openstack.

    ``--domain-id`` (optional):
        Domain ID of the OpenStack project to update. Valid together with --type openstack.

    ``--global-metric`` (optional):
        The name and weight of cloud global metric in form: ``<name> <weight>``. Can be
        specified multiple times.

    ``-l | --label`` (optional):
        The key and the value of cloud label in form: ``<key>=<value>``. Can be
        specified multiple times.

delete
    Request the deletion of a specific GlobalCloud.

    ``name``:
        The name of the GlobalCloud to delete.


The Cloud resource: ``cloud``
-----------------------------

This resource manages Krake **Cloud** namespaced resources,
which needs to be registered on Krake to be used. It corresponds to
an IaaS Cloud deployments (e.g. OpenStack, AWS, etc.) that will be managed
by the infrastructure provider software. Cloud resource could contain
also metrics and labels, that could be used in cluster scheduling.

Krake currently supports the following GlobalCloud cloud software (types):

- OpenStack_

Base command: ``krakectl infra cloud  <...>``

.. note::

  This resource is a namespaced resource that could be used by the
  Krake resources from the same namespace. For example, the cloud resource
  could be used by any cluster which lives in the same namespace as the
  cloud.

register
    Add a new Cloud to the ones registered on Krake. Example:

    .. code:: bash

        krakectl infra cloud register <cloud_name> \
          --type <cloud_type> \
          --url <cloud_identity_service_url> \
          --username <cloud_username> \
          --password <cloud_password> \
          --project <cloud_project_name> \
          --infra-provider <infra_provider_name>

    ``name``:
        The name of the new Cloud, as stored by Krake (can be arbitrary).
        The same name cannot be used twice in the same namespace.

    ``-n | --namespace`` (optional):
        The namespace to which the Cloud have to be added. If none is given, the
        user namespace is selected.

    ``--type``:
        The Cloud type. Type of the cloud that will be registered
        on Krake. Currently, only OpenStack_ cloud software is supported, and valid type is: `openstack`.

    ``--url``:
        URL to OpenStack identity service (Keystone). Valid together with --type openstack.

    ``--username``:
        Username or UUID of OpenStack user. Valid together with --type openstack.

    ``--password``:
        Password of OpenStack user. Valid together with --type openstack.

    ``--project``:
        Name or UUID of the OpenStack project. Valid together with --type openstack.

    ``--infra-provider`` (optional):
        Infrastructure provider name for cloud management. Valid together with --type openstack.

    ``--global-infra-provider`` (optional):
        Global infrastructure provider name for cloud management to update. Valid together with --type openstack.

    ``--domain-name`` (optional):
        Domain name of the OpenStack user. Valid together with --type openstack.

    ``--domain-id`` (optional):
        Domain ID of the OpenStack project. Valid together with --type openstack.

    ``--global-metric`` (optional):
        The name and weight of cloud global metric in form: ``<name> <weight>``. Can be
        specified multiple times.

    ``-m | --metric`` (optional):
        The name and weight of cloud metric in form: ``<name> <weight>``. Can be
        specified multiple times.

    ``-l | --label`` (optional):
        The key and the value of cloud label in form: ``<key>=<value>``. Can be
        specified multiple times.

list
    List all Clouds of a namespace.

    ``-n | --namespace`` (optional):
        The namespace from which the Cloud have to be listed. If none is given, the
        user namespace is selected.

get
    Request information about a specific Cloud.

    ``name``:
        The name of the Cloud to fetch.

    ``-n | --namespace`` (optional):
        The namespace from which the Cloud have to be retrieved. If none is given, the
        user namespace is selected.

update
    Request a change of the current state of an existing Cloud.

    ``name``:
        The name of the Cloud to update.

    ``-n | --namespace`` (optional):
        The namespace from which the Cloud have to be taken. If none is given, the
        user namespace is selected.

    ``--url`` (optional):
        URL to OpenStack identity service (Keystone) to update. Valid together with --type openstack.

    ``--username`` (optional):
        Username or UUID of OpenStack user to update. Valid together with --type openstack.

    ``--password`` (optional):
        Password of OpenStack user to update. Valid together with --type openstack.

    ``--project`` (optional):
        Name or UUID of the OpenStack project to update. Valid together with --type openstack.

    ``--infra-provider`` (optional):
        Infrastructure provider name for cloud management to update. Valid together with --type openstack.

    ``--global-infra-provider`` (optional):
        Global infrastructure provider name for cloud management to update. Valid together with --type openstack.

    ``--domain-name`` (optional):
        Domain name of the OpenStack user to update. Valid together with --type openstack.

    ``--domain-id`` (optional):
        Domain ID of the OpenStack project to update. Valid together with --type openstack.

    ``--global-metric`` (optional):
        The name and weight of cloud global metric in form: ``<name> <weight>``. Can be
        specified multiple times.

    ``-m | --metric`` (optional):
        The name and weight of cloud metric in form: ``<name> <weight>``. Can be
        specified multiple times.

    ``-l | --label`` (optional):
        The key and the value of cloud label in form: ``<key>=<value>``. Can be
        specified multiple times.

delete
    Request the deletion of a specific Cloud from a namespace.

    ``name``:
        The name of the Cloud to delete.

    ``-n | --namespace`` (optional):
        The namespace from which the Cloud have to be deleted. If none is given, the user namespace is selected.


Common options
==============

These options are common to all commands:

``-o | --output <format>`` (optional):
    The format of the displayed response. Three are available: YAML: ``yaml``, JSON: ``json`` or table: ``table``.


Warnings
========

Warning messages are issued in situations where it is useful to alert the user of some
condition in a Krake, which may exhibit errors or unexpected behavior.
Warnings_ standard library is used, hence the warning messages could be filtered
by ``PYTHONWARNINGS`` environment variable.

An example to disable all warnings:

.. code:: bash

    $ PYTHONWARNINGS=ignore krakectl kube app create <...>


.. _Warnings: https://docs.python.org/3/library/warnings.html
.. _IM: https://github.com/grycap/im
.. _OpenStack: https://www.openstack.org/
