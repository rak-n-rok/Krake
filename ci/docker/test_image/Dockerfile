ARG PYTHON_VER=3.12

FROM python:${PYTHON_VER}-slim

ARG ETCD_VER=3.3.13
ARG PROMETHEUS_VER=2.12.0
ARG CFSSL_VER=1.4.1
ARG CONFLUENT_VER=7.0

ENV LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common curl \
    && curl -sSo /etc/apt/keyrings/confluent.asc https://packages.confluent.io/deb/${CONFLUENT_VER}/archive.key \
    && echo "deb [signed-by=/etc/apt/keyrings/confluent.asc] https://packages.confluent.io/deb/${CONFLUENT_VER} stable main" > /etc/apt/sources.list.d/confluent.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        openjdk-17-jre-headless \
        zookeeper \
        confluent-kafka \
        confluent-ksqldb \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir /tmp/etcd \
    && curl -sSL https://github.com/etcd-io/etcd/releases/download/v${ETCD_VER}/etcd-v${ETCD_VER}-linux-amd64.tar.gz \
      | tar xzf - -C /tmp/etcd --strip-components=1 \
    && mv /tmp/etcd/etcd /usr/local/bin \
    && rm -rf /tmp/etcd

RUN mkdir /tmp/prometheus \
    && curl -sSL  https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VER}/prometheus-${PROMETHEUS_VER}.linux-amd64.tar.gz \
      | tar xzf - -C /tmp/prometheus --strip-components=1 \
    && mv /tmp/prometheus/prometheus /usr/local/bin \
    && rm -rf /tmp/prometheus

RUN curl -sSL https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VER}/cfssl_${CFSSL_VER}_linux_amd64 -o /usr/local/bin/cfssl \
    && curl -sSL https://github.com/cloudflare/cfssl/releases/download/v${CFSSL_VER}/cfssljson_${CFSSL_VER}_linux_amd64 -o /usr/local/bin/cfssljson \
    && chmod +x /usr/local/bin/cfssl /usr/local/bin/cfssljson

ENV PATH="/opt/venv/bin:${PATH}"
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir -U pip setuptools coverage pytest \
    && pip install --no-cache-dir tox
