#!/bin/bash

set -xeuo pipefail

function fail () {
  echo $1
  exit 1
}

# Check number of arguments
if [[ $# -ne 2 ]] ; then
  fail "usage: $0 <backend_name> <backend_ip>"
fi

# Set vars
BACKEND_NAME="$1"
BACKEND_IP="$2"

# Check if BACKEND_NAME is set
if [[ -z "$BACKEND_NAME" ]]; then
    fail "backend_name needs to be set"
fi

# Check if BACKEND_IP is an IP
if ! [[ "$BACKEND_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	fail "backend_ip is incorrect"
fi

BACKEND_SP="sp_$BACKEND_NAME"

IDP_NAME=identity-central

# Populate /etc/hosts
sudo sh -c "echo '$BACKEND_IP $BACKEND_NAME' >> /etc/hosts" || fail "Failed to add BackEnd to /etc/hosts"

. /home/ubuntu/git/krake/infra/central_idp/central-idp.openrc

openstack service provider create --service-provider-url "https://$BACKEND_IP/Shibboleth.sso/SAML2/ECP" --auth-url "https://$BACKEND_IP/v3/OS-FEDERATION/identity_providers/$IDP_NAME/protocols/mapped/auth" "$BACKEND_SP" || fail "Failed to create SP"
