# This Dockerfile follows Best practices for writing Dockerfiles
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/

# Instead of using official nginx image we use ubuntu image and install nginx using apt.
# This ensures compatibility of nginx with libnginx-mod-http-lua nginx plugin (lua interpreter) and other packages we install using apt.
# Relevant code from official nginx Dockerfile (other than nginx install) is included here.
FROM ubuntu:18.04

# Install packages (ABC order)
RUN apt-get update && apt-get install --no-install-recommends --no-install-suggests -y \
  apt-utils \
  libnginx-mod-http-lua \
  luarocks \
  net-tools \
  nginx=1.14.0-* \
  openssl \
  vim

RUN luarocks install nginx-lua-prometheus

# Copy custom nginx error message
RUN mkdir -p /etc/nginx/html
COPY 50x.html /etc/nginx/html/

# Krake uses self-signed certificate in the current development state.
# Let's Encrypt doesn't issue certificates for IP addresses, only domain names.
# Therefore we won't be able to use the trusted CA certificate without DNS.
# Certificates should not be part of repo in the production state.
# This should be done as a part of milestone (https://publicgitlab.cloudandheat.com/ragnarok/krake/milestones/11)
RUN mkdir -p /etc/nginx/ssl
RUN openssl req -newkey rsa:4096 -days 365 -nodes -x509 \
    -subj "/C=DE/ST=DE/L=DRESDEN/O=C&H/CN=localhost" \
    -keyout /etc/nginx/ssl/key.pem -out /etc/nginx/ssl/cert.pem

CMD ["nginx", "-g", "daemon off;"]
