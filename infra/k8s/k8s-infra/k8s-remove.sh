#!/bin/bash

kubectl delete namespace infra
kubectl delete -f rbac.yaml
# Remove Cert
rm /tmp/infra-ingress-tls.*
