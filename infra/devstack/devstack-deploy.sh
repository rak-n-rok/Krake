#!/bin/bash

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./devstack-deploy.sh --openrc /path/to/f1a-openrc --stack_file /path/to/devstack-stack.yaml --stack_env_file /path/to/devstack-stackenv.yaml --central_idp_public_ip 185.128.118.124 --get_devstack_ip_retry 40"
  exit 1
}

RETRY_MAX_VALUE=10 # Default

if [[ $# -eq 0 ]]; then
  usage
fi

while [[ $# -gt 0 ]]
do
key="$1"

case $key in
    -o|--openrc)
    OPENRC_FILE="$2"
    shift # past argument
    shift # past value
    ;;
    -e|--stack_env_file)
    ENVIRONMENT_FILE="$2"
    shift # past argument
    shift # past value
    ;;
    -s|--stack_file)
    STACK_FILE="$2"
    shift # past argument
    shift # past value
    ;;
    -c|--central_idp_public_ip)
    CENTRAL_IDP_PUB_IP="$2"
    shift # past argument
    shift # past value
    ;;
    -r|--get_devstack_ip_retry)
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

if ! [ -r "$OPENRC_FILE" ]; then
  fail "Cannot open $OPENRC_FILE"
fi

if ! [ -r "$ENVIRONMENT_FILE" ]; then
  fail "Cannot open $ENVIRONMENT_FILE"
fi

if ! [ -r "$STACK_FILE" ]; then
  fail "Cannot open $STACK_FILE"
fi

if ! [[ "$RETRY_MAX_VALUE" =~ ^[0-9]+$ ]]; then
    fail "Number of retry needs to be an integer"
fi

if ! [[ "$CENTRAL_IDP_PUB_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  fail "Central IdP IP is incorrect"
fi

# Parse env file to get Devstack ID
DEVSTACK_ID=`grep devstack_id $ENVIRONMENT_FILE | awk '{print $2}'`
if ! [[ "$DEVSTACK_ID" =~ ^[0-9]+$ ]]; then
    fail "devstack_id needs to be an integer"
fi

# Start Heat stack to deploy the DevStack VM
. "$OPENRC_FILE"

STACK_NAME="DevStack-$DEVSTACK_ID"

openstack stack create "$STACK_NAME" --environment "$ENVIRONMENT_FILE" --template "$STACK_FILE"

# Get DevStack IP
RETRY=0
DEVSTACK_IP=`openstack stack output show "$STACK_NAME" instance_ip  -f json | jq -r '.output_value'`
while [[ ! "$DEVSTACK_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; do 
  (( RETRY++ ))
  if [[ $RETRY -ge $RETRY_MAX_VALUE ]]; then
    echo "Definitely couldn't get DevStack IP, aborting."
    exit 1
  else
    echo "Couldn't get DevStack IP, retrying ... ($RETRY/$RETRY_MAX_VALUE) "
    sleep 1
    DEVSTACK_IP=`openstack stack output show "$STACK_NAME" instance_ip -f json | jq -r '.output_value'`
  fi
done

# Add the newly created DevStack as a Service Provider on the Central IdP
DEVSTACK_CIDP_NAME="devstack$DEVSTACK_ID"
ssh -o StrictHostKeyChecking=no ubuntu@$CENTRAL_IDP_PUB_IP ./git/krake/infra/central_idp/scripts/add_sp_to_idp.sh "$DEVSTACK_CIDP_NAME" "$DEVSTACK_IP"
