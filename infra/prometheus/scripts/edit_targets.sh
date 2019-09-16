#!/bin/bash

set -e

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./edit_targets.sh --[register|unregister] --krake_ip 192.168.0.10 --krake_name krake-vm-1"
  exit 1

}

# Check number of arguments
if [[ $# -ne 5 ]]; then
  usage
fi

while [[ $# -gt 0 ]]; do key="$1"
  case $key in
    -r|--register)
    REGISTER=true
    shift # past argument
    ;;
    -u|--unregister)
    REGISTER=false
    shift # past argument
    ;;
    -k|--krake_ip)
    KRAKE_IP="$2"
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

# Set vars
TARGETS_PATH="/home/prometheus/git/krake/infra/prometheus/docker-compose/prometheus/targets.json"

if ! [[ "$KRAKE_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  fail "Krake IP is incorrect"
fi

if [[ "$REGISTER" = false ]] ; then

  if ! grep -Fq \"${KRAKE_IP}\" "$TARGETS_PATH" ; then
    UNREG_FAIL_MSG="IP $KRAKE_IP not present in $TARGETS_PATH"
  elif ! grep -Fq \"${KRAKE_NAME}\" "$TARGETS_PATH" ; then
    UNREG_FAIL_MSG="Name '$KRAKE_NAME' not present in $TARGETS_PATH"
  fi
  if [[ -n "$UNREG_FAIL_MSG" ]]; then
    fail "Failed to unregister Krake IP and name from monitoring. $UNREG_FAIL_MSG"
  fi

  jq --arg IP "$KRAKE_IP" --arg NAME "$KRAKE_NAME" '. - [{"targets": [$IP], "labels": {"job": "krake", "node_name": $NAME}}]' "$TARGETS_PATH" > "$TARGETS_PATH.tmp" || fail "Failed to modify targets."
  TO_PRINT="unregistered from"

elif [[ "$REGISTER" = true ]] ; then

  if grep -Fq \"${KRAKE_IP}\" "$TARGETS_PATH" ; then
    REG_FAIL_MSG="IP $KRAKE_IP already registered in $TARGETS_PATH"
  elif grep -Fq \"${KRAKE_NAME}\" "$TARGETS_PATH" ; then
    REG_FAIL_MSG="Name '$KRAKE_NAME' already registered in $TARGETS_PATH"
  fi
  if [[ -n "$REG_FAIL_MSG" ]]; then
    fail "Failed to register Krake IP and name to monitoring. $REG_FAIL_MSG"
  fi

  jq --arg IP "$KRAKE_IP" --arg NAME "$KRAKE_NAME" '. + [{"targets": [$IP], "labels": {"job": "krake", "node_name": $NAME}}]' "$TARGETS_PATH" > "$TARGETS_PATH.tmp" || fail "Failed to modify targets."
  TO_PRINT="registered to"

else
  fail "Unrecognized $REGISTER option"
fi

# We can't change the inode of target file.
# If changed, modification of a file outside of docker container (on a VM level) is not reflected in mounted volume.
# https://github.com/moby/moby/issues/6011
cat "$TARGETS_PATH.tmp" > "$TARGETS_PATH" && rm "$TARGETS_PATH.tmp" || fail "Failed to write targets to the targets file."

echo "'$KRAKE_NAME' (IP: $KRAKE_IP) was successfully $TO_PRINT the Krake monitoring."
