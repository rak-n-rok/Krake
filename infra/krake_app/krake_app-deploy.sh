#!/bin/bash

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./krake_app-deploy.sh --openrc /path/to/f1a-openrc
                                     --key_name name_of_your_SSH_key
                                     --user_data /path/to/krake_vm-deploy.sh
                                     --monitoring_public_ip 185.128.118.123
                                     --krake_name Krake-VM
                                     [--get_krake_ip_retry 40]
                                     [--property <key=value> (repeat option to set multiple properties)]

        List of currently supported properties:
          [
            IDENTITY_PROVIDER_HOSTNAME,
            GIT_BRANCH, GIT_URL,
            OPENSTACK_INSTANCES,
            KRAKE_URL,
            MYSQL_DEFAULT_PASS
          ]
      "
  exit 1
}

# Set Krake VM vars
IMAGE="3763d928-2ebd-11e9-a3fe-4b7ceb61b0b3"  # Ubuntu 18.04 LTS x64
FLAVOR="XS"
SECURITY_GROUP="default"
NETWORK="krake-network"

EDIT_TARGETS_PATH="/home/prometheus/git/krake/infra/prometheus/scripts/edit_targets.sh"
RETRY_MAX_VALUE=10
PRI_IP_REGEX="\b((127\.)|(10\.))[0-9]+\.[0-9]+\.[0-9]+|((172\.1[6-9]\.)|(172\.2[0-9]\.)|(172\.3[0-1]\.)|(192\.168\.))[0-9]+\.[0-9]+\b"

if [[ $# -eq 0 ]]; then
  usage
fi

PROPERTY_ARRAY=()

while [[ $# -gt 0 ]]; do key="$1"
  case $key in
    -o|--openrc)
    OPENRC_FILE="$2"
    shift # past argument
    shift # past value
    ;;
    -k|--key_name)
    KEY_NAME="$2"
    shift # past argument
    shift # past value
    ;;
    -u|--user_data)
    USER_DATA="$2"
    shift # past argument
    shift # past value
    ;;
    -n|--krake_name)
    KRAKE_NAME="$2"
    shift # past argument
    shift # past value
    ;;
    -m|--monitoring_public_ip)
    MONITORING_PUB_IP="$2"
    shift # past argument
    shift # past value
    ;;
    -r|--get_krake_ip_retry)
    RETRY_MAX_VALUE="$2"
    shift # past argument
    shift # past value
    ;;
    --property)
    PROPERTY_ARRAY+=("$1") # append key "--property"
    PROPERTY_ARRAY+=("$2") # append property value
    shift # past argument
    shift # past value
    ;;
    *)    # unknown option
    usage
    shift # past argument
    ;;
  esac
done

if [[ -z "$KRAKE_NAME" ]]; then
   fail "Undefined Krake name"
fi

if ! [[ -r "$USER_DATA" ]]; then
  fail "Cannot open $USER_DATA"
fi

if ! [[ -r "$OPENRC_FILE" ]]; then
  fail "Cannot open $OPENRC_FILE"
fi

if ! [[ "$MONITORING_PUB_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  fail "Monitoring IP is incorrect"
fi

if ! [[ "$RETRY_MAX_VALUE" =~ ^[0-9]+$ ]]; then
    fail "Number of retry needs to be an integer"
fi

. "$OPENRC_FILE" || fail "Fail to source openrc file $OPENRC_FILE"

# Deploy the Krake VM
openstack server create --image "$IMAGE" \
                        --flavor "$FLAVOR" \
                        --security-group  "$SECURITY_GROUP"\
                        --key-name "$KEY_NAME" \
                        --network "$NETWORK" \
                        --user-data "$USER_DATA" \
                        "${PROPERTY_ARRAY[@]}" \
                        "$KRAKE_NAME"


# Get Krake private IP address
RETRY=0
KRAKE_IP=`openstack server show "$KRAKE_NAME" -c addresses -f json | jq -r '.addresses' | grep -oE "$PRI_IP_REGEX"`

while [[ ! "$KRAKE_IP" =~ $PRI_IP_REGEX ]]; do
  (( RETRY++ ))
  if [[ "$RETRY" -ge "$RETRY_MAX_VALUE" ]]; then
    echo "Definitely couldn't get private Krake IP, aborting."
    exit 1
  else
    echo "Couldn't get Krake private IP, retrying ... ($RETRY/$RETRY_MAX_VALUE) "
    sleep 1
    KRAKE_IP=`openstack server show "$KRAKE_NAME" -c addresses -f json | jq -r '.addresses' | grep -oE "$PRI_IP_REGEX"`
  fi
done

# Add the newly created Krake VM to the Krake Monitoring
ssh -o StrictHostKeyChecking=no prometheus@$MONITORING_PUB_IP "$EDIT_TARGETS_PATH --krake_ip $KRAKE_IP --krake_name $KRAKE_NAME --register"
