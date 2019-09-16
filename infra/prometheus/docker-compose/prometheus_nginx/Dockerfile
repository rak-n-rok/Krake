# This Dockerfile follows Best practices for writing Dockerfiles
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/

# Image
FROM nginx:1.14.2

# Dockerfile admin_pass argument is defined in docker-compose.yml through PROMETHEUS_ADMIN_PASS variable
ARG admin_pass

# Install packages (ABC order)
RUN apt-get update && apt-get install -y \
  apache2-utils \
  apt-utils \
  net-tools \
  openssl \
  vim

# Remove default Nginx conf
RUN rm /etc/nginx/conf.d/default.conf

# TODO For development purposes only. For production purposes need to be re-visited.
# Add Nginx BasicAuth admin user
RUN htpasswd -b -c /etc/nginx/.htpasswd admin $admin_pass

# TODO Krake uses self-signed certificate in the current development state.
# Let's Encrypt doesn't issue certificates for IP addresses, only domain names.
# Therefore we won't be able to use the trusted CA certificate without DNS.
# Certificates should not be part of repo in the production state.
# This should be done as a part of milestone (https://publicgitlab.cloudandheat.com/ragnarok/krake/milestones/11)
RUN mkdir -p /etc/nginx/ssl
RUN openssl req -newkey rsa:4096 -days 365 -nodes -x509 \
    -subj "/C=DE/ST=DE/L=DRESDEN/O=C&H/CN=localhost" \
    -keyout /etc/nginx/ssl/key.pem -out /etc/nginx/ssl/cert.pem
