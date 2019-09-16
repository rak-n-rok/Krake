#!/bin/bash

# Note '_' char is is not allowed in hostname
HOST_NAME="central-idp"
HOME_UBUNTU="/home/ubuntu"

function fail () {
  echo $1
  exit 1
}

# Set hostname
echo $HOST_NAME > /etc/hostname
hostname $HOST_NAME || fail "failed to set hostname"
SUDO_WHOAMI=`timeout 1 sudo -u ubuntu sudo whoami`
test "$SUDO_WHOAMI" = "root" || fail "failed to create ubuntu user with sudo perm"

# Add hostname to /etc/hosts to avoid following message:
#
# sudo -s
# sudo: unable to resolve host central-idp
echo "127.0.0.1 $HOST_NAME" >> /etc/hosts
echo 'ubuntu ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers

# Install docker and docker-compose
apt-get update || fail "apt-get update failed"
apt-get install -y apt-transport-https ca-certificates curl software-properties-common jq python3-pip libssl-dev libffi-dev || fail "apt-get install failed"
# apt-get install -y build-essential libssl-dev libffi-dev python-dev
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" || fail "apt-get add repository failed"
apt-get update || fail "apt-get update failed"
apt-get install -y docker-ce || fail "apt-get install failed"

curl -L "https://github.com/docker/compose/releases/download/1.22.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose || fail "curl docker-compose failed"
chmod +x /usr/local/bin/docker-compose

# Install OpenStack client
export LC_ALL="en_US.UTF-8"
pip3 install python-openstackclient

usermod -a -G docker ubuntu || fail "failed to add the docker group to the ubuntu user"

# Default value for cloning the krake repository
GIT_URL="https://krake_app:vT3cMpDwbXzyz5vYUmkx@publicgitlab.cloudandheat.com/ragnarok/krake.git"
GIT_BRANCH="master"

# Clone Krake
if [ ! -d $HOME_UBUNTU/git/krake ] ; then
  sudo -H -u ubuntu mkdir -p $HOME_UBUNTU/git || fail "failed to create dir git/krake"
  cd $HOME_UBUNTU/git
  sudo -H -u ubuntu git clone $GIT_URL -b $GIT_BRANCH || fail "failed to clone Krake"
  cd - > /dev/null
fi

# Connect to C&H's docker registery
sudo -H -u ubuntu docker login -u krake -p 3E5JVzb25cm7T2fy8kHm gitlab-registry.cloudandheat.com || fail "Connection to docker registery failed"

# Create certificates for Federation Signing
openssl req -x509 -newkey rsa:4096 -keyout $HOME_UBUNTU/git/krake/infra/central_idp/scripts/signing_key.pem -out $HOME_UBUNTU/git/krake/infra/central_idp/scripts/signing_cert.pem -days 365 -nodes -subj "/C=DE/ST=Saxony/L=Dresden/O=CLOUD&HEAT Technologies/OU=Krake/CN=Krake Identity Federation Signing" || fail "Failed to created necessary certificated for Federation Signing"

# Create SSL Certificates
openssl req -x509 -newkey rsa:4096 -keyout $HOME_UBUNTU/git/krake/infra/central_idp/scripts/privkey.pem -out $HOME_UBUNTU/git/krake/infra/central_idp/scripts/cert.pem -days 365 -nodes -subj "/C=DE/ST=Saxony/L=Dresden/O=CLOUD&HEAT Technologies/OU=Krake/CN=central-idp" || fail "Failed to created certificates for SSL"

# Launch docker-compose
sudo -H -u ubuntu docker-compose -f $HOME_UBUNTU/git/krake/infra/central_idp/docker-compose.yml up --build -d || fail "docker-compose failed"

# Wait for Keystone docker to be ready
echo "Wait for keystone docker to be up on port 5001"
while ! curl --output /dev/null --silent --head --fail --cacert $HOME_UBUNTU/git/krake/infra/central_idp/scripts/cert.pem https://central-idp:5001; do
  echo -n .
  sleep 1
done

. $HOME_UBUNTU/git/krake/infra/central_idp/central-idp.openrc
# Add demo users to test Federation
openstack project show demo || openstack project create demo --domain default || fail "Failed to create demo project"
openstack user show demo || openstack user create demo --project demo --password tmp || fail "Failed to create demo user"
openstack user show krake_service_account || openstack user create krake_service_account --project demo --password tmp || fail "Failed to create krake_service_account user"
openstack role add --user demo --project demo _member_ || fail "Failed to add role _member_ to the demo user"
openstack role add --user krake_service_account --project demo _member_ || fail "Failed to add role _member_ to the krake_service_account user"

# Add ssl krake service and ssl endpoint
openstack service create --name krake_ssl krake_ssl || fail "Failed to create krake_ssl service"
openstack endpoint create krake_ssl public https://localhost || fail "Failed to create endpoint for krake_ssl"
