#!/bin/bash

set -xeuo pipefail

function fail () {
  echo $1
  exit 1
}

# Check number of arguments
if [[ $# -ne 1 ]] ; then
  fail "usage: $0 <backend_name>"
fi

# Set vars
BACKEND_NAME="$1"

# Check if BACKEND_NAME is set
if [[ -z "$BACKEND_NAME" ]]; then
    fail "backend_name needs to be set"
fi
BACKEND_SP="sp_$BACKEND_NAME"

# Clean /etc/hosts
sudo sh -c "grep -v $BACKEND_NAME /etc/hosts >> /tmp/hosts.tmp && mv /tmp/hosts.tmp /etc/hosts" || fail "Failed to remove BackEnd to /etc/hosts"

. /home/ubuntu/git/krake/infra/central_idp/central-idp.openrc || fail "Fail to source openrc file"

# Removing Service Provider
openstack service provider delete "$BACKEND_SP" || fail "Failed to delete SP"
