#!/bin/bash

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./devstack-remove.sh --openrc /path/to/f1a-openrc --central_idp_public_ip 185.128.118.124 --devstack_id 42"
  exit 1
}

if [[ $# -lt 6 ]]; then
  usage
fi

while [[ $# -gt 0 ]]; do
  key="$1"

  case $key in
    -o|--openrc)
    OPENRC_FILE="$2"
    shift # past argument
    shift # past value
    ;;
    -c|--central_idp_public_ip)
    CENTRAL_IDP_PUB_IP="$2"
    shift # past argument
    shift # past value
    ;;
    -d|--devstack_id)
    DEVSTACK_ID="$2"
    shift # past argument
    shift # past value
    ;;
    *)    # unknown option
    usage
    shift # past argument
    ;;
  esac
done

if ! [ -r "$OPENRC_FILE" ]; then
  fail "Cannot open $OPENRC_FILE"
fi

if ! [[ "$CENTRAL_IDP_PUB_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  fail "Central IdP IP is incorrect"
fi

if ! [[ "$DEVSTACK_ID" =~ ^[0-9]+$ ]]; then
  fail "devstack_id needs to be an integer"
fi

# Delete Heat stack
. "$OPENRC_FILE" || fail "Fail to source openrc file $OPENRC_FILE"

STACK_NAME="DevStack-$DEVSTACK_ID"

openstack stack delete "$STACK_NAME" -y || fail "Fail to delete Heat Stack"

# Remove DevStack Service Provider from the Central IdP
DEVSTACK_CIDP_NAME="devstack$DEVSTACK_ID"
ssh -o StrictHostKeyChecking=no ubuntu@$CENTRAL_IDP_PUB_IP ./git/krake/infra/central_idp/scripts/del_sp_from_idp.sh "$DEVSTACK_CIDP_NAME" || fail "Fail to launch deletion script on the central IdP"
