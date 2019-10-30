===================
Configuration files
===================

This sections describes the configuration files of Krake and Rok, respectively the **krake.yaml** and **rok.yaml** files.

Both files also have their respective templates that need to be copied before being modified: **krake.yaml.template** and **rok.yaml.template**.

.. note::
    If an example value is specified for a parameter, it means this parameter has no default value in Krake.


Krake configuration
===================

etcd
    This section defines the parameters to let the API communicate with the ETCD database.

    host (string)
        Address of the database. Example: ``127.0.0.1``
    port (integer), default: ``2379``
        Port to communicate with the database.

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


Authentication:
---------------


authentication
    This section defines the method for authenticating users that connect to the API. Two methods are available: keystone_ and static_. A user not recognized can still send request if anonymous_ are allowed.

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

        static
            .. _static:

            The user is set here, and the API will authenticate all requests as being sent by this user.

            enabled (boolean)
                Set the static method as authentication method. Example: ``true``
            name (string)
                This is the name of the user that will be set as sending all requests. Example: ``system``


Authorization
-------------

authorization (enumeration)
    This parameter defines the mode for allowing users to perform specific actions (e.g. "create" or "delete" a resource). Three modes are available: ``RBAC``, ``always-allow``, ``always-deny``.

default-roles (list)
    This section is a list of all the roles that have to be added to the database when starting the API.

    The syntax for each role is described in the following:

    metadata
        Here we define the metadata of the current role.

        name (string)
            .. _default-roles.metadata.name:

            The name of the role to add. Example: ``system:admin``

    rules (list)
        This section is a list of all rules that apply to the current role.

        api (string)
            The name of the API the current role is authorized to access. For all APIs to be accessible, the syntax: ``"all"`` must be used.
        namespaces (list of strings)
            The list of all namespaces the current role is authorized to access. For all namespaces to be accessible, the syntax: ``["all"]`` must be used.
        resources (list of strings)
            The list of all resources the current role is authorized to access. For all resources to be accessible, the syntax: ``["all"]`` must be used.
        verbs (list of strings)
            The list of verbs that corresponds to the operations this role is allowed to execute. Example: ``["create", "list", "get", "update", "delete"]``


default-role-bindings (list)
    This section is a list of all bindings between the defined users and roles. The syntax for each binding is described in the following:

    metadata
        Here we define the metadata of the current role binding.

        name (string)
            Name of the current binding. Example: ``system:admin``

    users (list of strings)
        List of users concerned by this binding. They will be given the roles listed in default-role-bindings.roles_. Example: ``["system:admin"]``
    roles (list of strings)
        .. _default-role-bindings.roles:

        List of roles concerned by this binding. The names listed have to correspond to the name of the roles, as defined in default-roles.metadata.name_. Example: ``["system:admin"]``.


Controllers
-----------

controllers:
    This section defines the parameters for each controller separately. The controllers have their own respective subsection, with the name of the controller as subsection name.

    Example:

    .. code:: yaml

        controllers:
          scheduler:
            <configuration_for_scheduler>

          kubernetes:
            <configuration_for_kubernetes_controller>


    The general configuration is the same for each controller. Additional parameters can be added for specific controllers, depending on the implementation. Here are the common parameters:

    controller_name (string)
        All the parameters for the current controller are described here. The ``controller_name`` needs to be replaced by the actual name of the current controller.

        api_endpoint (URL)
            .. _controllers.controller_name.api_endpoint:

            Address of the API to be reached by the current controller. Example: ``http://localhost:8080``

            worker_count (integer)
                Number of workers handling the resources on the controller.
                Example: ``5``

            debounce (float)
                For the worker queue of the controller: set the debounce time
                to delay the handling of a resource, and get any updated state
                in-between. Example ``1.5``

            tls
                This section defines the parameters needed for TLS support. If TLS support is enabled on the API, it needs to be enabled on the controllers to let them communicate with the API.

                enabled (boolean)
                    Activate or deactivate the TLS support. If the API uses only TLS, then this should be set to ``true``. This has priority over the scheme given by controllers.controller_name.api_endpoint_. Example: ``false``
                client_ca (path)
                    Set the path to the client certificate authority. Example: ``./tmp/pki/ca.pem``
                client_cert (path)
                    Set the path to the client certificate. Example: ``./tmp/pki/jc.pem``
                client_key (path)
                    Set the path to the client key. Example: ``./tmp/pki/jc-key.pem``


Logging
-----------

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
