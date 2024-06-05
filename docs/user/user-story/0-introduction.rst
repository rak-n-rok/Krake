============
Introduction
============

This guide
==========

This guide aims at providing an introduction in some concepts and mechanisms of Krake. It provides guidances and commands that readers are encouraged to try out by themselves on a demo environment as described in the next section.

It does not aim at providing an exhaustive list of commands nor all the possible ways how to use them.

This guide is structured into independent Scenarios which usually start with a Preparation section, and end with a Cleanup section.

Demo Environment
================

.. note::
    The demo environment described in this section refers to a standard development environment deployed with Ansible. See :ref:`admin/setup:Set up Krake with Ansible`

The demo environment is comprised of 3 virtual machines in the same private network:

- The Krake VM: It runs all the Krake components in docker containers, as well as a Prometheus Server to simulate scheduling data for the backends.
- The two Minikube VMs ``minikube-cluster-1`` and ``minikube-cluster-2``: They run an all-in-one Kubernetes "cluster". They are used as backends by Krake to deploy the users' applications.

.. note::
    Scenario :ref:`user/user-story/4-openstack:OpenStack backends` additionally requires to have an OpenStack project at hand.

On the Krake VM, the two Kubernetes clusters ``kubeconfig`` files are present:

.. prompt:: bash $ auto

    $ ll clusters/config/
    $ cat clusters/config/minikube-cluster-1
    $ cat clusters/config/minikube-cluster-2

.. note::
    Unless stated otherwise (generally in the prompt), all commands are run on the Krake VM, with the ``krake`` user.

A simple manifest file will be used as a demo application. It can be found at the following path:

.. prompt:: bash $ auto

    $ cat git/krake/templates/applications/k8s/echo-demo.yaml
