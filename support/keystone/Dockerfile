# Dockerfile for creating a secure HTTPS-enabled keystone server.
# This is needed for testing purposes, because the keystone script only creates a
# server with HTTP.
# The dockerfile takes an ubuntu image and installs some dependencies onto it.
# While running, a mysql service is started, the database is created and bootstrapped
# and the keystone environment is set up.
# !! WARNING: No persistence is build into this dockerfile for now.
#
# .. code:: bash
#
#     docker build -f ./Dockerfile -t keystone-https:latest ../..
#
# The double parent path call is necessary to have access to the certificate files in
# the ``tmp/pki`` folder. To use keystone, it is important to create a certificate for
# 'system:keystone' with the 'support/pki' script.
#
# It is also possible to copy the certifactes to the location of this file and set it as
# an argument for the dockerfile.
# Another thing that is changeable is the location of the configuration files.
#
# .. code:: bash
#
#     docker build -f ./Dockerfile -t keystone-https:latest . \
#                  --build-arg CONF_PATH=. --build-arg CERT_PATH=.
#
# To run the created image as a docker container, the following command can be used.
# This should expose the port 5000 to the localhost.
#
# .. code:: bash
#
#     docker run -p 5000:5000 -t -d --name keystone keystone-https:latest
#
#

FROM ubuntu:latest

ARG DEBIAN_FRONTEND=/tmp/pki/

ARG CERT_PATH=/tmp/pki/
ENV CERT_PATH ${CERT_PATH}

ARG CONF_PATH=/support/keystone
ENV CONF_PATH ${CONF_PATH}

RUN apt-get update && \
    apt-get install -y apt-transport-https && \
    apt-get install -y sysvinit-utils nano net-tools curl && \
    apt-get install -y apache2 libapache2-mod-wsgi && \
    apt-get install -y mariadb-server

RUN mkdir /run/mysqld
RUN chown -R mysql:root /run/mysqld

RUN a2enmod ssl

RUN apt-get install -y keystone

COPY ${CONF_PATH}/keystone-httpd.conf /etc/apache2/sites-available/keystone.conf
COPY ${CONF_PATH}/keystone.conf /etc/keystone/keystone.conf

COPY ${CERT_PATH}/system:keystone-key.pem /etc/pki/system:keystone-key.pem
COPY ${CERT_PATH}/system:keystone.pem /etc/pki/system:keystone.pem
COPY ${CERT_PATH}/ca.pem /etc/pki/ca.pem

RUN service mysql start && \
    mysql -e "CREATE DATABASE keystone" && \
    mysql -e "GRANT ALL PRIVILEGES ON keystone.* TO 'keystone'@'localhost' IDENTIFIED BY 'keystone'" && \
    mysql -e "GRANT ALL PRIVILEGES ON keystone.* TO 'keystone'@'%' IDENTIFIED BY 'keystone'"

CMD service mysql start && \
    keystone-manage fernet_setup --keystone-user keystone --keystone-group keystone && \
    keystone-manage credential_setup --keystone-user keystone --keystone-group keystone && \
    keystone-manage db_sync && \
    keystone-manage bootstrap --bootstrap-username system:admin --bootstrap-password admin --bootstrap-project-name system:admin --bootstrap-admin-url https://localhost:5000/v3/ --bootstrap-internal-url https://localhost:5000/v3/ --bootstrap-public-url https://localhost:5000/v3/ --bootstrap-region-id RegionOne && \
    service apache2 restart && \
    /bin/bash

EXPOSE 5000
