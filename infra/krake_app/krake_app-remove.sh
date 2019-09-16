#!/bin/bash

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./krake_app-remove.sh --openrc /path/to/f1a-openrc --monitoring_public_ip 185.128.118.123 --krake_name Krake-VM"
  exit 1
}

if [[ $# -lt 6 ]]; then
  usage
fi

EDIT_TARGETS_PATH="/home/prometheus/git/krake/infra/prometheus/scripts/edit_targets.sh"
PRI_IP_REGEX="\b((127\.)|(10\.))[0-9]+\.[0-9]+\.[0-9]+|((172\.1[6-9]\.)|(172\.2[0-9]\.)|(172\.3[0-1]\.)|(192\.168\.))[0-9]+\.[0-9]+\b"

while [[ $# -gt 0 ]]; do key="$1"
  case $key in
    -o|--openrc)
    OPENRC_FILE="$2"
    shift # past argument
    shift # past value
    ;;
    -m|--monitoring_public_ip)
    MONITORING_PUB_IP="$2"
    shift # past argument
    shift # past value
    ;;
    -n|--krake_name)
    KRAKE_NAME="$2"
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

if ! [[ "$MONITORING_PUB_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  fail "Monitoring IP is incorrect"
fi

. "$OPENRC_FILE" || fail "Fail to source openrc file $OPENRC_FILE"

# Get Krake private IP address
KRAKE_PRI_IP=`openstack server show "$KRAKE_NAME" -c addresses -f json | jq -r '.addresses' | grep -oE "$PRI_IP_REGEX"`

# Delete the Krake VM
openstack server delete "$KRAKE_NAME" || fail "Fail to delete Krake VM"

# Unregister Krake VM from the Krake Monitoring
ssh -o StrictHostKeyChecking=no prometheus@$MONITORING_PUB_IP "$EDIT_TARGETS_PATH --krake_ip $KRAKE_PRI_IP --krake_name $KRAKE_NAME --unregister"
