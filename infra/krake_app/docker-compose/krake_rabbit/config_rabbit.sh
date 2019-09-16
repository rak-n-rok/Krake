#!/bin/bash

# This script needs to be executed just once
if [ -f /$0.completed ] ; then
  echo "$0 `date` /$0.completed found, skipping run"
  exit 0
fi

# Wait for RabbitMQ startup
for (( ; ; )) ; do
  sleep 5
  rabbitmqctl -q node_health_check > /dev/null 2>&1
  if [ $? -eq 0 ] ; then
    echo "$0 `date` rabbitmq is now running"
    break
  else
    echo "$0 `date` waiting for rabbitmq startup"
  fi
done

# Add Rabbit user
rabbitmqctl add_user krake tmp
rabbitmqctl set_permissions -p / krake "" ".*" ".*"
echo "$0 `date` user krake created"

# Create exchange
rabbitmqadmin declare exchange name=delayed.exchange type=x-delayed-message arguments='{"x-delayed-type": "direct"}'
echo "$0 `date` exchange created"

# Create queues
rabbitmqadmin declare queue name=create.application durable=true
rabbitmqadmin declare queue name=delete.application durable=true
rabbitmqadmin declare queue name=monitor.application.status durable=true
rabbitmqadmin declare queue name=save.application.status durable=true
rabbitmqadmin declare queue name=spawn.containers durable=true
rabbitmqadmin declare queue name=save.deployment.selection durable=true
rabbitmqadmin declare queue name=cluster.resources.sufficient durable=true
rabbitmqadmin declare queue name=scheduler durable=true
rabbitmqadmin declare queue name=update.cluster durable=true
rabbitmqadmin declare queue name=update.application durable=true
echo "$0 `date` queues created"

# Create bindings
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="create.application" routing_key="create.application"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="delete.application" routing_key="delete.application"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="monitor.application.status" routing_key="monitor.application.status"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="save.application.status" routing_key="save.application.status"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="spawn.containers" routing_key="spawn.containers"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="save.deployment.selection" routing_key="save.deployment.selection"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="cluster.resources.sufficient" routing_key="cluster.resources.sufficient"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="scheduler" routing_key="scheduler"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="update.cluster" routing_key="update.cluster"
rabbitmqadmin declare binding source="delayed.exchange" destination_type="queue" destination="update.application" routing_key="update.application"
echo "$0 `date` bindings created"

# Create mark so script is not ran again
touch /$0.completed
