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
``--hook`` argument in rok CLI.

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


TLS
---

If TLS is enabled on the Krake API, the `complete` hook needs to be authenticated with
some certificates signed directly or indirectly by the Krake CA. For that purpose, the
hook injects a Kubernetes ConfigMap for different files and mounts it in a volume:

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

Applications signal the job completion by calling the `complete` hook URL.
The token is used for authentication and should be sent in a PUT request body.


Examples
--------

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
