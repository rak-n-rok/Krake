#!/bin/bash

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./k8s_backend_del.sh --k8s_name kubernetes1"
  exit 1

}

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

# Expand aliases in order for "--insecure" flag to be correctly used in the following openstack request.
shopt -s expand_aliases

source devstack/federate.openrc

# Remove K8S cluster
openstack coe cluster delete "$K8S_NAME"
