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

If TLS is enabled on the Krake API, the `complete` hook injects a Kubernetes configmap
and volume for the Krake CA certificate. The CA certificate is loaded from the configmap
into the volume as a file (default: ``/etc/krake_ca/ca.pem``) in a given application.

  .. tip::

      The Names of the environment variables and of the CA certificate filename are
      defined in the Kubernetes controller configuration file.

See also :ref:`user/configuration:Krake configuration`.

Applications signal the job completion by calling the `complete` hook URL.
The token is used for authentication and should be sent in a PUT request body.

Example using `cURL`:

.. code:: bash

    $ curl -X PUT -d "{\"token\":\"$KRAKE_TOKEN\"}" $KRAKE_COMPLETE_URL
    # If TLS is enabled on the Krake API
    $ curl -X PUT -d "{\"token\":\"$KRAKE_TOKEN\"}" $KRAKE_COMPLETE_URL --cacert /etc/krake_ca/ca.pem
