#!/bin/bash

# Generate Cert
MASTER_IP=`kubectl get node --selector='node-role.kubernetes.io/master' -o jsonpath={.items[*].status.addresses[?\(@.type==\"ExternalIP\"\)].address}`
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /tmp/infra-ingress-tls.key -out /tmp/infra-ingress-tls.crt -subj "/CN=${MASTER_IP}"
