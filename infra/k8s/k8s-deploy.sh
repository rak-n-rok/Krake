#!/bin/bash

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./k8s-deploy.sh --openrc /path/to/f1a-openrc --central_idp_public_ip 185.128.118.124 --devstack_id 42 --k8s_id 42"
  exit 1
}

PRI_IP_REGEX="\b((127\.)|(10\.))[0-9]+\.[0-9]+\.[0-9]+|((172\.1[6-9]\.)|(172\.2[0-9]\.)|(172\.3[0-1]\.)|(192\.168\.))[0-9]+\.[0-9]+\b"
PUB_IP_REGEX="\b(?!(10)|192\.168|172\.(2[0-9]|1[6-9]|3[0-2]))[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b"

if [[ $# -lt 8 ]]; then
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
    -k|--k8s_id)
    K8S_ID="$2"
    shift # past argument
    shift # past value
    ;;
    *)    # unknown option
    usage
    shift # past argument
    ;;
  esac
done

if ! [[ -r "$OPENRC_FILE" ]]; then
  fail "Cannot open $OPENRC_FILE"
fi

if ! [[ "$CENTRAL_IDP_PUB_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  fail "Central IdP IP is incorrect"
fi

if ! [[ "$DEVSTACK_ID" =~ ^[0-9]+$ ]]; then
  fail "devstack_id needs to be an integer"
fi

if ! [[ "$K8S_ID" =~ ^[0-9]+$ ]]; then
  fail "k8s_id needs to be an integer"
fi

# Heat stack
. "$OPENRC_FILE" || fail "Fail to source openrc file $OPENRC_FILE"

# Get DevStack server ID
STACK_NAME="DevStack-$DEVSTACK_ID"
DEVSTACK_SERVER_ID=`openstack stack resource list "$STACK_NAME" --filter name=devstack_vm -f json | jq -r '.[] | .physical_resource_id'`

if [[ -z "$DEVSTACK_SERVER_ID" ]]; then
  fail "$STACK_NAME not found."
fi

# Get DevStack public and private ip addresses
DEVSTACK_SERVER_IPS=`openstack server show "$DEVSTACK_SERVER_ID" -c addresses -f json | jq -r '.addresses'`
DEVSTACK_PRI_IP=`echo "$DEVSTACK_SERVER_IPS" | grep -oE "$PRI_IP_REGEX"`
DEVSTACK_PUB_IP=`echo "$DEVSTACK_SERVER_IPS" | grep -oP "$PUB_IP_REGEX"`

if [[ -z "$DEVSTACK_PRI_IP" ]] || [[ -z "$DEVSTACK_PUB_IP" ]]; then
    fail "Couldn't get DevStack IPs"
fi

K8S_NAME="kubernetes$K8S_ID"

# Add the new Service Provider in the Central IdP, for the k8s cluster, using the Underlying DevStack IPs for authentication
ssh -o StrictHostKeyChecking=no ubuntu@$CENTRAL_IDP_PUB_IP ./git/krake/infra/central_idp/scripts/add_sp_to_idp.sh "$K8S_NAME" "$DEVSTACK_PRI_IP" || fail "Fail to launch add script on the central IdP"

# Create K8S backend and setup K8S infra on the top of the Underlying DevStack
exec 5>&1 # Capture stdout to a variable but still display it in the console
OUTPUT=$(ssh -o StrictHostKeyChecking=no stack@$DEVSTACK_PUB_IP "./git/krake/infra/k8s/scripts/k8s_backend_add.sh --k8s_name $K8S_NAME" | tee /dev/fd/5 )

# TODO Temporary workaround needed for Krake CLI to work on K8S backend.
# TODO The logic will be fixed in the second iteration of
#  https://publicgitlab.cloudandheat.com/ragnarok/krake/milestones/32.
# Add  K8S master IP address to the CIDP.
K8S_MASTER_IP=`echo "$OUTPUT"  | tail -n 1`
K8S_MASTER_NAME="master_$K8S_NAME"

ssh -o StrictHostKeyChecking=no ubuntu@$CENTRAL_IDP_PUB_IP ./git/krake/infra/central_idp/scripts/add_sp_to_idp.sh "$K8S_MASTER_NAME" "$K8S_MASTER_IP" || fail "Fail to launch add script on the central IdP"
