============================================
Demonstration of basic commands and workflow
============================================

Goal: Get familiar with basic ``rok`` commands, and with the associated internal Krake mechanisms.

Introduction to the ``rok`` CLI
===============================

- Following commands provide basic help on the ``rok`` CLI and its structure:

.. prompt:: bash $ auto

    $ rok --help
    $ rok kubernetes --help  # Similar to "rok kube --help"
    $ rok kube application --help  # Similar to "rok app --help"
    $ rok kube cluster --help
    $ rok openstack --help  # Similar to "rok os --help"

Register a cluster
==================

- Create a Kubernetes ``Cluster`` using its associated Kubernetes ``kubeconfig`` file.

.. prompt:: bash $ auto

    $ rok kube cluster list  # No Cluster resource is present
    $ rok kube cluster create clusters/config/minikube-cluster-demoenv-1
    $ rok kube cluster list  # One Cluster resource with name "minikube-cluster-demoenv-1"

Spawn the demo application
==========================

- Spawn a Kubernetes ``Application`` using its Kubernetes manifest file.

.. prompt:: bash $ auto

    $ rok kube app list  # No Application resource is present
    $ rok kube app create -f git/krake/rak/functionals/echo-demo.yaml echo-demo
    $ rok kube app list  # One Application resource with name "echo-demo"

- Check application information:

  - Application Status is ``RUNNING``.
  - Application is running on ``minikube-cluster-demoenv-1``.

.. prompt:: bash $ auto

    $ rok kube app get echo-demo
    $ rok kube app get echo-demo -f json  # Use JSON format, which is also more verbose

- Access the demo application endpoint:

.. prompt:: bash $ auto

    $ APP_URL=$(rok kube app get echo-demo -f json | jq '.status.services["echo-demo"]'); APP_URL="${APP_URL:1: -1}"  # Extract Application endpoint from JSON output and register it in the APP_URL variable
    $ curl $APP_URL

- Check the created resources on the Kubernetes cluster:

.. prompt:: bash $ auto

    $ kubectl --kubeconfig clusters/config/minikube-cluster-demoenv-1 get deployments
    NAME        READY   UP-TO-DATE   AVAILABLE   AGE
    echo-demo   1/1     1            1           3h34m
    $ kubectl --kubeconfig clusters/config/minikube-cluster-demoenv-1 get services
    NAME         TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)          AGE
    echo-demo    NodePort    10.98.78.74   <none>        8080:32235/TCP   3h34m
    kubernetes   ClusterIP   10.96.0.1     <none>        443/TCP          27h
    $ kubectl --kubeconfig clusters/config/minikube-cluster-demoenv-1 get po
    NAME                         READY   STATUS    RESTARTS   AGE
    echo-demo-6dc5d84869-4hcd8   1/1     Running   0          3h34m

Update resources
================

- Update the manifest file to create a second Pod for the ``echo-demo`` application.

.. prompt:: bash $ auto

    $ cat git/krake/rak/functionals/echo-demo-update.yaml
    ---
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: echo-demo
    spec:
      replicas: 2
      selector:
        matchLabels:
          app: echo
      template:
        metadata:
          labels:
            app: echo
        spec:
          containers:
          - name: echo
            image: k8s.gcr.io/echoserver:1.9
            ports:
            - containerPort: 8080
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: echo-demo
    spec:
      type: NodePort
      selector:
        app: echo
      ports:
      - port: 8080
        protocol: TCP
        targetPort: 8080

    $ rok kube app update -f git/krake/rak/functionals/echo-demo-update.yaml echo-demo

- Check the existing resources on the Kubernetes cluster: A second Pod has been spawned.

.. prompt:: bash $ auto

    $ kubectl --kubeconfig clusters/config/minikube-cluster-demoenv-1 get deployments
    NAME        READY   UP-TO-DATE   AVAILABLE   AGE
    echo-demo   2/2     2            2           42m
    $ kubectl --kubeconfig clusters/config/minikube-cluster-demoenv-1 get po
    NAME                         READY   STATUS        RESTARTS   AGE
    echo-demo-6dc5d84869-2v6jh   1/1     Running       0          7s
    echo-demo-6dc5d84869-l7fm2   1/1     Running       0          42m

Delete resources
================

- Issue the following commands to delete the ``echo-demo`` Kubernetes ``Application`` and the ``minikube-cluster-demoenv-1`` Kubernetes ``Cluster``.

.. prompt:: bash $ auto

    $ rok kube app delete echo-demo
    $ rok kube app list  # No Application resource is present
    $ rok kube cluster delete minikube-cluster-demoenv-1
    $ rok kube cluster list  # No Cluster resource is present
