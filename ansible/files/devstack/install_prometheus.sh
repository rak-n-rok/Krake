#!/bin/bash

function fail () {
  echo $1
  exit 1
}

HOME_STACK=/opt/stack

# Install ansible
apt-get update || fail "apt-get update failed"
apt-get install -y software-properties-common || fail "apt-get install failed"
apt-add-repository ppa:ansible/ansible -y  || fail "apt-get add repository failed"
apt-get update || fail "apt-get update failed"
apt-get install -y ansible || fail "apt-get install failed"

# Install Docker
apt-get update || fail "apt-get update failed"
apt-get install -y apt-transport-https ca-certificates curl software-properties-common jq python3-pip libssl-dev libffi-dev || fail "apt-get install failed"
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" || fail "apt-get add repository failed"
apt-get update || fail "apt-get update failed"
apt-get install -y docker-ce || fail "apt-get install failed"

usermod -a -G docker stack || fail "failed to add the docker group to the ubuntu user"

cat << EOF >> /etc/ansible/hosts
[prometheus]
127.0.0.1   ansible_connection=local

[exporters]
127.0.0.1   ansible_connection=local

[nginx-proxy]
127.0.0.1   ansible_connection=local
EOF

IP=$(/sbin/ip -o -4 addr list ens3 | awk '{print $4}' | cut -d/ -f1)
echo "OS_AUTH_URL=https://"$IP"/v3" >> $HOME_STACK/git/krake/infra/devstack/ansible/exporter_container/openstack/env_file

# Create docker network
docker network create --driver=bridge --subnet=172.25.0.0/24 proxy_network

# launch ansible playbook
sudo -H -u stack ansible-playbook $HOME_STACK/git/krake/infra/devstack/ansible/deploy.yml || fail "failed to deploy with ansible playbook"
