#!/bin/bash

# Launch config script in background
# Note there is no Docker support for running commands after server (PID 1) is running
# https://stackoverflow.com/questions/30747469/how-to-add-initial-users-when-starting-a-rabbitmq-docker-container
/config_rabbit.sh &

# Launch
/usr/local/bin/docker-entrypoint.sh rabbitmq-server
