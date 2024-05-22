=============
Configuration
=============

This sections describes the configuration of Krake components and Rok. The
different parameters, their value and role will be described here

.. note::
    If an example value is specified for a parameter, it means this parameter
    has no default value in Krake.


Configuration file or command-line options
==========================================

There are two different ways to configure Krake components:

*  using the configuration files (also for Rok);
*  using command-line options (only for Krake components).


Configuration files
-------------------

There are 7 different configuration files:

*  ``api.yaml`` for the Krake API;
*  ``scheduler.yaml`` for the Scheduler as controller;
*  ``kubernetes_application.yaml`` for the Kubernetes Application controller;
*  ``kubernetes_cluster.yaml`` for the Kubernetes Cluster controller;
*  ``garbage_collection.yaml`` for the Garbage Collector as controller;
*  ``infrastructure.yaml`` for the Infrastructure controller;
*  ``krakectl.yaml`` for the krakectl utility.

For each one of them except ``rok.yaml``, a template is present in the
``config`` directory. They end with the ``.template`` extension. For Rok, the
template configuration file is in the main directory of Krake.

By default, the configurations for Krake modules are searched in the following directories:

* current working directory
* location `/etc/krake/`

`rok` searches these locations:
* current working directory
* the current home directory defined by `XDG_CONFIG_HOME`
* location `/etc/rok/`

If the necessary configuration file is not found in these locations, an error is thrown and the module doesn't start. In order to use a different location, the `--config` option in the module start command can be used.


Generate configuration
~~~~~~~~~~~~~~~~~~~~~~
From the templates, actual configuration files can be generated using the
``krake/scripts/krake_generate_config`` script. The templates have parameters
that can be overwritten by the script. It allows setting some parameters using
command-line options. The arguments and available options are:

``<src_files> <src_files> ...<src_files>`` (list of file paths)
    Positional arguments: the list of template files that will be used for
    generation.

``--dst`` (path to a directory)
    Optional argument: the directory in which the generated files will be
    created. Default: ``.`` (current directory).

``--tls-enabled``
    If used, set the TLS support to enabled between all Krake components. By
    default, TLS is disabled.

``--cert-dir <cert_dir>`` (path to a directory)
    Set the directory in which the certificates for the TLS communication
    should be stored. Default: ``"tmp/pki"``.

``--allow-anonymous``
    If enabled, anonymous requests are accepted by the API. See
    :ref:`admin/security:Authentication`. Disabled by default for the generation.

``--keystone-authentication-enabled``
    Enable the Keystone authentication as one of the authentication mechanisms. See
    :ref:`admin/security:Authentication`. Disabled by default for the generation.

``--keystone-authentication-endpoint``
    Endpoint to connect to the keystone service. See
    :ref:`admin/security:Authentication`. Default: ``"http://localhost:5000/v3"``.

``--keycloak-authentication-enabled``
    Enable the Keycloak authentication as one of the authentication mechanisms. See
    :ref:`admin/security:Authentication`. Disabled by default for the generation.

``--keycloak-authentication-endpoint``
    Endpoint to connect to the Keycloak service. See
    :ref:`admin/security:Authentication`. Default: ``"http://localhost:9080"``.

``--keycloak-authentication-realm``
    Keycloak realm to use on the provided endpoint. See
    :ref:`admin/security:Authentication`. Default: ``krake``.

``--static-authentication-enabled``
    Enable the static authentication as one of the authentication mechanisms. See
    :ref:`admin/security:Authentication`. Disabled by default.

``--static-authentication-username``
    Name of the user that will authenticate through static authentication. See
    :ref:`admin/security:Authentication`. Default: ``"system:admin"``.

``--cors-origin``
    URL or wildcard for the 'Access-Control-Allow-Origin' of the CORS system on the API.
    Default: ``*``.

``--authorization-mode``
    Authorization mode to use for the requests sent to the API.
    Only 'RBAC' should be used in production. See :ref:`admin/security:Authorization`.
    Default: ``always-allow``.

``--api-host <api_host>`` (Address)
    Host that will be used to create the endpoint of the API for the
    controllers. Default: ``"localhost"``.

``--api-port <api_port>`` (integer)
    Port that will be used to create the endpoint of the API for the
    controllers.. Default: ``8080``.

``--etcd-version <etcd_version>`` (string)
    The etcd database version. Default: ``v3.5.12``.

``--etcd-host <etcd_host>`` (Address)
    Host for the API to use to connect to the etcd database. Default:
    ``127.0.0.1``.

``--etcd-port <etcd_port>`` (integer)
    Port for the API to use to connect to the etcd database. Default: ``2379``.

``--etcd-port <etcd_port>`` (integer)
    Peer port for the etcd endpoint. Default: ``2380``.

``--docs-problem-base-url <docs_problem_base_url>`` (string)
    URL of the problem documentation. Default: ``https://rak-n-rok.readthedocs.io/projects/krake/en/latest/user/problem``.

``--docker-daemon-mtu <docker_daemon_mtu>`` (integer)
    The Docker daemon MTU. Default: ``1450``.

``--worker-count <worker_count>`` (integer)
    Number of worker to start on the controller. Workers are the units that
    handle resources. Default: ``5``.

``--debounce <debounce>`` (float)
    For the controllers: the worker queue has a mechanism to delay a received
    state of a resource with a timer. A newer state received will then restart
    the timer. If a resource is updated a few times in one second, this
    mechanism prevents having to handle it each time by another component, and
    wait for the latest value. Default: ``1.0``.

``--reschedule-after``
    Time in seconds after which a resource will be rescheduled. See
    :ref:`dev/scheduling:Scheduling`. Default: ``60``.

``--stickiness``
    "Stickiness" weight to express migration overhead in the normalized ranking
    computation. See :ref:`dev/scheduling:Scheduling`. Default: ``0.1``.

``--poll-interval``
    Time in seconds for the Infrastructure Controller
    to ask the infrastructure provider client again after a modification of
    a cluster. Default: ``30``.

``--complete-hook-user``
    For the complete hook, set the name of the user that will be defined as CN of the
    generated certificates. See :ref:`dev/hooks:Complete`.
    Default: ``"system:complete-hook"``.

``--complete-hook-cert-dest``
    For the complete hook, set the path to the mounted directory, in which the
    certificates to communicate with the API will be stored. See
    :ref:`dev/hooks:Complete`. Default: ``"/etc/krake_cert"``.

``--complete-hook-env-token``
    For the complete hook, set the name of the environment variable that contain the
    value of the token, which will be given to the Application. See
    :ref:`dev/hooks:Complete`. Default: ``"KRAKE_COMPLETE_TOKEN"``.

``--complete-hook-env-url``
    For the complete hook, set the name of the environment variable that contain the
    URL of the Krake API, which will be given to the Application. See
    :ref:`dev/hooks:Complete`. Default: ``"KRAKE_COMPLETE_URL"``.

``--external-endpoint`` (str)
    If set, replaces the value of the URL host and port of the endpoint given to the
    Applications which have the 'complete' hook enabled. See :ref:`dev/hooks:Complete`.

``--logging-level`` (str)
    To set the logging level of a controller.
    Default: ``INFO``.

``--logging-handler`` (str)
    To set the handler to use for logging. This lets one choose whether the
    logging messages should be printed to stdout or saved to a file.
    Options are 'console' and 'file'.
    Default: ``console``.

``-h, --help``
    Display the help message and exit the script.



Examples
~~~~~~~~

To create default configuration files for Krake, the following command can be
used in the main directory:

.. code:: bash

    krake/scripts/krake_generate_config templates/config/*template

This will create all Krake configuration files in the main directory of Krake.

To create default configuration files for Rok, the following command can be
used in the main directory:

.. code:: bash

    krake/scripts/krake_generate_config templates/config/rok.yaml.template

This will create the Rok configuration file in the main directory of Krake.

The two previous commands can be combined together to generate both Rok and
Krake configuration files at the same time:

.. code:: bash

    krake/scripts/krake_generate_config templates/config/*template templates/config/rok.yaml.template

This will create Krake and Rok configuration files in the main directory of
Krake.

To create a new configuration for the API on the ``tmp`` directory with a
different etcd database endpoint, the following can be used:

.. code:: bash

    krake/scripts/krake_generate_config --dst /tmp templates/config/api.yaml.template --etcd-host newhost.org --etcd-port 1234


Command-line options
--------------------

Apart from the configuration files, specific command-line options are
available for the Krake components. They are created automatically from the
configuration parameters. Nested options are generated by concatenating the
names of section with dashes characters (``"-"``). For example, the
``authentication.allow_anonymous`` YAML element becomes the
``--authentication-allow-anonymous`` option.

There is one option for each parameter of the configuration, except the
elements that are lists for the moment. Booleans are converted into optional
flags.


Krake configuration
===================

All configuration options for the Krake API are described here.

port (integer)
    This parameter defines the port to which the Krake API will listen to for incoming
    requests.

etcd
    This section defines the parameters to let the API communicate with the ETCD database.

    host (string)
        Address of the database. Example: ``127.0.0.1``
    port (integer), default: ``2379``
        Port to communicate with the database.
    retry_transactions (int):
        Number of times a database transaction will be attempted again if it failed the
        first time due to concurrent write on the same resource.

tls
    This section defines the parameters needed for TLS support. If TLS is enabled, all other components and clients need TLS support to communicate with the API.

    enabled (boolean)
        Activate or deactivate the TLS support. Example: ``false``
    cert (path)
        Set the path to the client certificate authority. Example: ``tmp/pki/system:api-server.pem``
    key (path)
        Set the path to the client certificate. Example: ``tmp/pki/system:api-server-key.pem``
    client_ca (path)
        Set the path to the client key. Example: ``tmp/pki/ca.pem``


Authentication and authorization
--------------------------------

authentication
    This section defines the method for authenticating users that connect to the API.
    Three methods are available: keystone_, keycloak_ and static_. A user not recognized
    can still send request if anonymous_ are allowed.

    allow_anonymous (boolean), default: ``false``
        .. _anonymous:

        Enable the "anonymous" user. Any request executed without a user being authenticated will be processed as user ``system:anonymous``.

    strategy
        This section describes the parameters for the methods of authentication.

        keystone
            .. _keystone:

            The Keystone service of OpenStack can be used as authentication method.

            enabled (boolean)
                Set Keystone as authentication method. Example: ``false``
            endpoint (URL)
                Endpoint of the Keystone service. Example: ``http://localhost:5000/v3``

        keycloak
            .. _keycloak:

            The Keycloak service can be used as authentication method.

            enabled (boolean)
                Set Keycloak as authentication method. Example: ``false``
            endpoint (URL)
                Endpoint of the Keycloak service. Example: ``http://localhost:9080``
            realm (str)
                Keycloak realm to use at the provided endpoint. Example: ``krake``

        static
            .. _static:

            The user is set here, and the API will authenticate all requests as being sent by this user.

            enabled (boolean)
                Set the static method as authentication method. Example: ``true``
            name (string)
                This is the name of the user that will be set as sending all requests. Example: ``system``

    cors-origin (string), default ``*``
        For the CORS mechanism of Krake. Set the default allowed URL, which corresponds
        to the ``Access-Control-Allow-Origin`` response header.

authorization (enumeration)
    This parameter defines the mode for allowing users to perform specific actions (e.g. "create" or "delete" a resource). Three modes are available: ``RBAC``, ``always-allow``, ``always-deny``.


Controllers configuration
=========================

The general configuration is the same for each controller. Additional parameters can be added for specific controllers, depending on the implementation. Here are the common parameters:

api_endpoint (URL)
    .. _api_endpoint:

    Address of the API to be reached by the current controller. Example: ``http://localhost:8080``

debounce (float)
    For the worker queue of the controller: set the debounce time
    to delay the handling of a resource, and get any updated state
    in-between. Example ``1.5``

tls
    This section defines the parameters needed for TLS support. If TLS support is enabled on the API, it needs to be enabled on the controllers to let them communicate with the API.

    enabled (boolean)
        Activate or deactivate the TLS support. If the API uses only TLS, then this should be set to ``true``. This has priority over the scheme given by api_endpoint_. Example: ``false``
    client_ca (path)
        Set the path to the client certificate authority. Example: ``./tmp/pki/ca.pem``
    client_cert (path)
        Set the path to the client certificate. Example: ``./tmp/pki/jc.pem``
    client_key (path)
        Set the path to the client key. Example: ``./tmp/pki/jc-key.pem``

Kubernetes application controller
---------------------------------
Additional parameters, specific for the Kubernetes application controller:

hooks (string)
    All the parameters for the application hooks are described here. See also
    :ref:`dev/hooks:Complete`.

    complete (string)
        This section defines the parameters needed for the Application ``complete`` hook. If is not defined the Application ``complete`` hook is disabled.

        hook_user (string)
            Name of the user that will be set as CN in the certificates generated for
            the hook. If RBAC is enabled, should match a ``RoleBinding`` for the
            ``applications/complete`` subresource. Example ``system:complete-hook``
        intermediate_src (path)
            Path to the certificate which will be used to sign new generated
            certificates for the hook. Not needed if TLS is not enabled. Example:
            ``/etc/krake/certs/system:complete-signing.pem``
        intermediate_key_src (path)
            Path to the key of the certificate which will be used to sign new generated
            certificates for the hook. Not needed if TLS is not enabled. Example:
            ``/etc/krake/certs/system:complete-signing-key.pem``
        cert_dest (path)
            Set the path to the certificate authority on the deployed Application. Example: ``/etc/krake_cert``
        env_token (string)
            Name of the environment variable, which stores Krake authentication token. Example: ``KRAKE_COMPLETE_TOKEN``
        env_url (string)
            .. _complete_hook_env_url:

            Name of the environment variable, which stores Krake ``complete`` hook URL. Example: ``KRAKE_COMPLETE_URL``
        external_endpoint (URL, optional)
            If set, replaces the host and port in the value of environment variable in
            the Krake ``complete`` hook URL (the name of this variable is given by
            complete_hook_env_url_). By default, the value stored in the variable is the
            api_endpoint_. Example: ``https://krake.external.host:1234``.

    shutdown (string)
        This section defines the parameters needed for the Application ``shutdown`` hook. If is not defined the Application ``shutdown`` hook is disabled.

        hook_user (string)
            Name of the user that will be set as CN in the certificates generated for
            the hook. If RBAC is enabled, should match a ``RoleBinding`` for the
            ``applications/shutdown`` subresource. Example ``system:shutdown-hook``
        intermediate_src (path)
            Path to the certificate which will be used to sign new generated
            certificates for the hook. Not needed if TLS is not enabled. Example:
            ``/etc/krake/certs/system:shutdown-signing.pem``
        intermediate_key_src (path)
            Path to the key of the certificate which will be used to sign new generated
            certificates for the hook. Not needed if TLS is not enabled. Example:
            ``/etc/krake/certs/system:shutdown-signing-key.pem``
        cert_dest (path)
            Set the path to the certificate authority on the deployed Application. Example: ``/etc/krake_cert``
        env_token (string)
            Name of the environment variable, which stores Krake authentication token. Example: ``KRAKE_SHUTDOWN_TOKEN``
        env_url (string)
            .. _shutdown_hook_env_url:

            Name of the environment variable, which stores Krake ``shutdown`` hook URL. Example: ``KRAKE_SHUTDOWN_URL``
        external_endpoint (URL, optional)
            If set, replaces the host and port in the value of environment variable in
            the Krake ``shutdown`` hook URL (the name of this variable is given by
            shutdown_hook_env_url_). By default, the value stored in the variable is the
            api_endpoint_. Example: ``https://krake.external.host:1234``.

hooks (string)
    All the parameters for the migration of an application are described here.

    retry (string)
        This section defines the parameters needed for the retrying of migrations.

        max (string)
            Maximum number of retries for the transfer of a single file of an application.
        timeout (string)
            Timeout after a failure until the next rescheduling of the application takes place.
            This value will be multiplicated with the current number of tries.


Scheduler
---------
Additional parameters, specific for the Scheduler:

reschedule_after (float):
    Number of seconds between the last update or rescheduling of a resource and the
    next rescheduling. Example: ``60``
stickiness (float):
    Additional weight for the computation of the rank of the scheduler. It is added to
    the computation of the rank of the cluster on which a scheduled resource is
    actually running. It prevents migration from happening too frequently, and thus,
    represents the cost of migration. As the computation is done with normalized
    weights, the stickiness is advised to be between 0 and 1. Example: ``0.1``.

Infrastructure controller
-------------------------
Additional parameters, specific for the Infrastructure controller:

poll_interval (float):
    Time in seconds for the Infrastructure Controller to ask the infrastructure
    provider client again after a modification of a cluster. Example: ``30``.


Common configuration:
=====================

The following elements are common for all components of Krake except Rok.

Logging
-------

log:
    This section is dedicated to the logging of the application. The syntax follows the one described for the Python logging_ module (``logging.config``). The content of this section will be given to this module for configuration.


--------------------------------


Rok configuration
=================

api_url (URL)
    .. _api_url:

    Address of the Krake API to connect to. If the scheme given is incompatible with the tls.enabled_ parameter, it will be overwritten to match. Example: ``http://localhost:8080``
user (string)
    The name of the user that will access the resources. Example: ``john-doe``

tls
    This section defines the parameters needed for TLS support, which can be used to communicate with the API.

    enabled (boolean)
        .. _tls.enabled:

        Activate or deactivate the TLS support. If the API uses only TLS, then this should be set to ``true``. This has priority over the scheme given by api_url_. Example: ``false``
    client_ca (path)
        Set the path to the client certificate authority. Example: ``./tmp/pki/ca.pem``
    client_cert (path)
        Set the path to the client certificate. Example: ``./tmp/pki/jc.pem``
    client_key (path)
        Set the path to the client key. Example: ``./tmp/pki/jc-key.pem``


.. _logging: https://docs.python.org/2/library/logging.config.html
