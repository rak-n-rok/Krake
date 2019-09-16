#!/bin/bash

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./k8s_backend_add.sh --k8s_name kubernetes1 [--k8s_create_cluster_retry 30]"
  exit 1

}

RETRY_MAX_VALUE=60 # [min] Default
STACK_HOME="/opt/stack"

if [[ $# -eq 0 ]]; then
  usage
fi

while [[ $# -gt 0 ]]; do key="$1"
  case $key in
    -k|--k8s_name)
    K8S_NAME="$2"
    shift # past argument
    shift # past value
    ;;
    -r|--k8s_create_cluster_retry)
    RETRY_MAX_VALUE="$2"
    shift # past argument
    shift # past value
    ;;
    *)    # unknown option
    usage
    shift # past argument
    ;;
  esac
done


# Check if K8S_NAME is set
if [[ -z "$K8S_NAME" ]]; then
    fail "k8s_name needs to be set"
fi

if ! [[ "$RETRY_MAX_VALUE" =~ ^[0-9]+$ ]]; then
    fail "Number of retry needs to be an integer"
fi

# Expand aliases in order for "--insecure" flag to be correctly used in the following openstack request.
shopt -s expand_aliases

source devstack/federate.openrc

# Check if ct1 template is created
echo "K8S BackEnd $K8S_NAME template:"
openstack coe cluster template show ct1
if [[ $? != 0 ]]; then
  fail "ct1 template needs to be created"
fi

# Create K8S cluster
openstack coe cluster create --cluster-template ct1 "$K8S_NAME"

# Wait loop for create complete status of K8S cluster
RETRY=0
K8S_STATUS=`openstack coe cluster show "$K8S_NAME" -f json | jq '.status'`
while [[ "$K8S_STATUS" != '"CREATE_COMPLETE"' ]]; do
  (( RETRY++ ))
  if [[ "$RETRY" -ge "$RETRY_MAX_VALUE" ]]; then
    fail "Failed to create K8S cluster in $RETRY_MAX_VALUE minutes. Current status: $K8S_STATUS"
  else
    echo "K8S BackEnd $K8S_NAME ... $K8S_STATUS ... ($RETRY/$RETRY_MAX_VALUE)"
    sleep 1m
    K8S_STATUS=`openstack coe cluster show "$K8S_NAME" -f json | jq '.status'`
  fi
done

K8S_MASTER_IP=`openstack coe cluster show "$K8S_NAME" -f json | jq '.master_addresses[0]' | tr -d '"'`

# SCP K8S infra scripts to the K8S master node
scp -o StrictHostKeyChecking=no -r "$STACK_HOME/git/krake/infra/k8s/scripts/k8s-infra/" fedora@$K8S_MASTER_IP:

# Execute K8S infra scripts
ssh -o StrictHostKeyChecking=no fedora@$K8S_MASTER_IP "bash ~/k8s-infra/k8s-deploy.sh"

echo "K8S infra deployed"
echo "$K8S_MASTER_IP" # Don't remove this print. It is used in the parent script `k8s-deploy.sh`.
