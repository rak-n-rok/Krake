#!/bin/bash

# This script can be used to generate compose and configuration files from jinja2
# templates for Krake and Prometheus docker infrastructure bundles
#
# The mandatory variables source for templating is defined by `--config` argument.
#
# J2cli (https://github.com/kolypto/j2cli) command-line tool for
# templating in bash-scripts is a prerequisite.

function fail () {
  echo $1
  exit 1
}

function usage () {
  echo "usage: ./generate.sh --config docker.yaml [--src /home/krake/docker] [--krake] [--prometheus]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  key="$1"

  case $key in
    -c|--config)
    CONFIG="$2"
    shift # past argument
    shift # past value
    ;;
    -s|--src)
    SOURCE_DIR="$2"
    shift # past argument
    shift # past value
    ;;
    -k|--krake)
    KRAKE=true
    shift # past argument
    ;;
    -p|--prometheus)
    PROMETHEUS=true
    shift # past argument
    ;;
    *)    # unknown option
    usage
    shift # past argument
    ;;
  esac
done


if ! [[ -r "$CONFIG" ]]; then
  fail "Cannot open $CONFIG"
fi

if [[ -z ${KRAKE+x} && -z ${PROMETHEUS+x} ]]; then
  fail "Define at least one infrastructure bundle to be configured."
fi

if [[ -z ${SOURCE_DIR+x} ]]; then
  SOURCE_DIR=.
fi

if [[ "$KRAKE" = true ]] ; then
  KRAKE_PATH="$SOURCE_DIR/krake"
  j2 -f yaml "$KRAKE_PATH/docker-compose.yaml.j2" $CONFIG -o "$KRAKE_PATH/docker-compose.yaml" || fail "j2cli failed."
  echo "Krake infrastructure bundle is configured."
fi

if [[ "$PROMETHEUS" = true ]] ; then
  PROM_PATH="$SOURCE_DIR/prometheus"
  j2 -f yaml "$PROM_PATH/docker-compose.yaml.j2" $CONFIG -o "$PROM_PATH/docker-compose.yaml" || fail "j2cli failed."
  j2 -f yaml "$PROM_PATH/prometheus.yaml.j2" $CONFIG -o "$PROM_PATH/prometheus.yaml" || fail "j2cli failed."
  j2 -f yaml "$PROM_PATH/bootstrap.yaml.j2" $CONFIG -o "$PROM_PATH/bootstrap.yaml" || fail "j2cli failed."
  echo "Prometheus infrastructure bundle is configured."
fi
