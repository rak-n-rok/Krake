=================
Application hooks
=================

This section describes Application hooks which are registered and called by the
Hook Dispatcher in kubernetes application controller module.


Complete
========


The application `complete` hook gives the ability to signals job completion.

The Krake Kubernetes controller calls the application `complete`
hook before the deployment of the application on a Kubernetes
cluster. The hook is disabled by default. The user can enable this hook with the
``--hook-complete`` argument in rok CLI.

See also :ref:`user/rok-documentation:Rok documentation`.

The complete hook injects the ``KRAKE_TOKEN`` environment variable, which stores the
Krake authentication token, and the ``KRAKE_COMPLETE_URL`` environment variable, which
stores the Krake `complete` hook URL for a given application.

By default, this URL is the Krake API endpoint as specified in the Kubernetes Controller
configuration. This endpoint may be only internal and thus not accessible by an
application that runs on a cluster. Thus, the ``external_endpoint`` parameter can be
leveraged. It specifies an endpoint of the Krake API, which can be accessed by the
application. The endpoint is only overridden if the ``external_endpoint``
parameter is set.

Applications signal the job completion by calling the `complete` hook URL.
The token is used for authentication and should be sent in a PUT request body.

Shutdown
========


The application `shutdown` hook gives the ability to gracefully stop an application
before a migration or deletion happens. This in turn allows to save data or bring other
important processes to a safe conclusion.

The Krake Kubernetes controller calls the application `shutdown`
hook before the deployment of the application on a Kubernetes
cluster. The hook is disabled by default. The user can enable this hook with the
``--hook-shutdown`` argument in rok CLI.

See also :ref:`user/rok-documentation:Rok documentation`.

The shutdown hook injects the ``KRAKE_TOKEN`` and the ``KRAKE_SHUTDOWN_URL``
environment variables, which respectively store the Krake authentication token and the
Krake `shutdown` hook URL for a given application.

By default, this URL is the Krake API endpoint as specified in the Kubernetes Controller
configuration. This endpoint may be only internal and thus not accessible by an
application that runs on a cluster. Thus, the ``external_endpoint`` parameter can be
leveraged. It specifies an endpoint of the Krake API, which can be accessed by the
application. The endpoint is only overridden if the ``external_endpoint``
parameter is set.

If the application should be migrated or deleted, Krake calls the ``shutdown`` services
URL, which is set via the manifest file of the application.
The integrated service gracefully shuts down the application, preferably via SIGTERM
call, but the exact implementation is up to the individual developer.
After the shutdown process is complete, the service sends a completion signal
to the `shutdown` hook endpoint of the specific application on the Krake API.
The previously set token is used for authentication and should be sent in a PUT
request body. This requirement prevents the malicious or unintentional deletion of an
application. The workflow of this process can be seen in the following figure:

.. figure:: /img/shutdown_hook.png

    Shutdown hook workflow in Krake

The shutdown hook was developed especially to enable stateful applications. Since these
services generate data or are in specific states, it was difficult to migrate or even
delete these applications without disrupting their workflow. The shutdown hook enables
these normal Krake features for these applications by allowing saving of the current
state. But be aware, that Krake doesn't implement a specific graceful shutdown for these
applications and merely gives them a possibility to be informed about the intentions of
Krake.

TLS
===

If TLS is enabled on the Krake API, both hooks need to be authenticated with
some certificates signed directly or indirectly by the Krake CA. For that purpose, the
hooks inject a Kubernetes ConfigMap for different files and mounts it in a volume:

    ``ca-bundle.pem``
        It contains the CA certificate of Krake, and the hook certificate that was used
        to sign the certificate specific to the Application.
    ``cert.pem``
        The certificate signed by the hook. It is generated automatically for each
        Application. Its CN is set to the hooks user defined in the hook configuration,
        see :ref:`user/configuration:Krake configuration`.
    ``key.pem``
        The key of the certificate signed by the hook. It is generated automatically
        for each Application.

The certificate added are signed by a specific certificate, defined by the
``intermediate_src`` field in the configuration
:ref:`user/configuration:Kubernetes application controller`. This certificate needs the
following:

 * able to sign other certificates;
 * hold the right alternative names to accept the Krake endpoint.

The ConfigMap is mounted by default at: ``/etc/krake_ca/cert.pem`` in the Kubernetes
Deployment resources of the Applications.

The name of the environment variables and the directory where the ConfigMap is
mounted are defined in the Kubernetes controller configuration file, see
:ref:`user/configuration:Krake configuration`.


Examples
========

cURL
~~~~

Example using `cURL`:

.. code:: bash

    $ curl -X PUT -d "{\"token\":\"$KRAKE_TOKEN\"}" $KRAKE_COMPLETE_URL

    # If TLS is enabled on the Krake API
    $ curl -X PUT -d "{\"token\":\"$KRAKE_TOKEN\"}" $KRAKE_COMPLETE_URL \
        --cacert /etc/krake_cert/ca-bundle.pem \
        --cert /etc/krake_cert/cert.pem \
        --key /etc/krake_cert/key.pem


By running this command, the Krake API will compare the given token to the one in its
database, and if they match, will set the Application to be deleted.

The cURL above may not work with older versions of cURL. You should use versions >=
7.51, otherwise you would get:

.. code:: bash

    curl: (35) gnutls_handshake() failed: The TLS connection was non-properly terminated.


Python requests
~~~~~~~~~~~~~~~

Example using Python's `requests` module:

If TLS is not enabled:

.. code:: python

    import requests
    import os

    endpoint = os.getenv("KRAKE_COMPLETE_URL")
    token = os.getenv("KRAKE_TOKEN")

    requests.put(endpoint, json={"token": token})

If TLS is enabled, using the default configuration for the certificate directory:

.. code:: python

    import requests
    import os

    ca_bundle = "/etc/krake_cert/ca-bundle.pem"
    cert_path = "/etc/krake_cert/cert.pem"
    key_path = "/etc/krake_cert/key.pem"
    cert_and_key = (cert_path, key_path)
    endpoint = os.getenv("KRAKE_COMPLETE_URL")
    token = os.getenv("KRAKE_TOKEN")

    requests.put(endpoint, verify=ca_bundle, json={"token": token}, cert=cert_and_key)
