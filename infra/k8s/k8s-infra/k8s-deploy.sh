#!/bin/bash

kubectl create namespace infra
kubectl create -f ~/k8s-infra/rbac.yaml
kubectl create secret tls infra-secret --key /tmp/infra-ingress-tls.key --cert /tmp/infra-ingress-tls.crt -n infra
# Exporters
kubectl create -f ~/k8s-infra/cadvisor.yaml
kubectl create -f ~/k8s-infra/kube-state-metrics.yaml
kubectl create -f ~/k8s-infra/prometheus-dummy-exporter.yaml
# Ingress
kubectl create -f ~/k8s-infra/default-backend.yaml
kubectl create -f ~/k8s-infra/ingress-controller-config-dummy-exporter.yaml
kubectl create -f ~/k8s-infra/ingress-controller.yaml
# Prometheus
kubectl create -f ~/k8s-infra/prometheus-config-dummy-exporter.yaml
kubectl create -f ~/k8s-infra/prometheus.yaml
