# Kubernetes Resources Setup

We are glad that you are interested in setting up a proof of concept (POC) system for Krake. This document is here to help make the process as simple as possible.

## Installation

``` shell
kubectl apply -f namespace.yaml    # Create the namespace
kubectl apply -f database/.        # Create the database components
kubectl apply -f backend/.         # Create the backend  components
kubectl apply -f frontend/.        # Create the frontend components
```

## Uninstall

``` shell
kubectl delete -f frontend/.        # Delete the frontend components
kubectl delete -f backend/.         # Delete the backend components
kubectl delete -f database/.        # Delete the database components 
kubectl delete -f namespace.yaml    # Delete the namespace
```