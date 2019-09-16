# This Dockerfile follows Best practices for writing Dockerfiles
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/

# Image
FROM rabbitmq:3.7-management

# Install packages (ABC order)
RUN apt-get update && apt-get install -y \
  apt-utils \
  curl \
  less \
  net-tools \
  telnet \
  unzip \
  vim

WORKDIR /opt/rabbitmq/plugins

# Install Delayed Message Exchange plugin (community supported, used by Krake Worker)
# http://www.rabbitmq.com/community-plugins.html
RUN curl -f -s -m 1 \
  https://dl.bintray.com/rabbitmq/community-plugins/3.7.x/rabbitmq_delayed_message_exchange/rabbitmq_delayed_message_exchange-20171201-3.7.x.zip \
  -o rabbitmq_delayed_message_exchange-20171201-3.7.x.zip
RUN unzip rabbitmq_delayed_message_exchange-20171201-3.7.x.zip
RUN rm -f rabbitmq_delayed_message_exchange-20171201-3.7.x.zip
RUN rabbitmq-plugins enable rabbitmq_delayed_message_exchange

# Install RabbitMQ Prometheus.io exporter (Implemented as RabbitMQ Management Plugin plugin)
# https://github.com/deadtrickster/prometheus_rabbitmq_exporter
ARG base_url='https://github.com/deadtrickster/prometheus_rabbitmq_exporter/releases/download/v3.7.2.4'
RUN curl -LO $base_url/accept-0.3.3.ez
RUN curl -LO $base_url/prometheus-3.5.1.ez
RUN curl -LO $base_url/prometheus_cowboy-0.1.4.ez
RUN curl -LO $base_url/prometheus_httpd-2.1.8.ez
RUN curl -LO $base_url/prometheus_rabbitmq_exporter-3.7.2.4.ez
RUN rabbitmq-plugins enable prometheus_rabbitmq_exporter

# Launch init.sh
COPY init.sh /
COPY config_rabbit.sh /
RUN chmod +x /init.sh /config_rabbit.sh
ENTRYPOINT ["/init.sh"]
