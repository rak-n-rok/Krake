=================
Application hooks
=================

This section describes Application hooks which are registered and called by
Hook Dispatcher in kubernetes application controller module.


Complete
========


Application ``complete`` hook gives ability to signals job completion.

Krake application controller calls application ``complete``
hook before the deployment of the application on Kubernetes
cluster. Hook is disabled by default. User enables this hook by the
--hook argument in rok CLI.

See also :ref:`user/rok-documentation:Rok documentation`.

Complete hook injects `KRAKE_TOKEN` environment variable which stores Krake
authentication token and `KRAKE_COMPLETE_URL` environment variable which stores the
Krake ``complete`` hook URL for given application.
If TLS is enabled on Krake API, ``complete`` hook injects Kubernetes configmap and
volume for the Krake CA certificate. CA certificate is loaded from configmap into
volume as a file (default: `/etc/krake_ca/ca.pem`) in given application.

  .. tip::

      Names of environment variables and CA certificate filename are defined
      in the application controller configuration file.

See also :ref:`user/configuration:Krake configuration`.

Application signals job completion by calling ``complete`` hook URL.
Token is used for authentication and should be sent in the PUT request body.

Example using `curl`:

.. code:: bash

    $ curl -X PUT -d "{\"token\":\"$KRAKE_TOKEN\"}" $KRAKE_COMPLETE_URL
    # If TLS is enabled on Krake API
    $ curl -X PUT -d "{\"token\":\"$KRAKE_TOKEN\"}" $KRAKE_COMPLETE_URL --cacert /etc/krake_ca/ca.pem
