#!/bin/bash

HOST_NAME="prometheus"
HOME_PROMETHEUS="/home/prometheus"
GIT_REPO_DIR="$HOME_PROMETHEUS/git"
GIT_KRAKE_DIR="$GIT_REPO_DIR/krake"

# Configure Prometheus VM defaults
PROMETHEUS_ADMIN_PASS="tmp"
GRAFANA_ADMIN_PASS="tmp"
GIT_URL="https://krake_app:vT3cMpDwbXzyz5vYUmkx@publicgitlab.cloudandheat.com/ragnarok/krake.git"
GIT_BRANCH="master"

function fail () {
  echo $1
  exit 1
}

# Set hostname
echo $HOST_NAME > /etc/hostname
hostname $HOST_NAME || fail "failed to set hostname"

# Add hostname to /etc/hosts
echo "127.0.0.1 $HOST_NAME" >> /etc/hosts

# Install packages
apt-get update || fail "apt-get update failed"
apt-get install -y docker.io docker-compose jq python3-pip haveged || fail "apt-get install failed"

# Install required python packages
pip3 install --no-cache-dir \
  jinja2-standalone-compiler~=1.3.1

# Override default values by Metadata
PROMETHEUS_META_DATA=`curl -f -s -m 1 http://169.254.169.254/openstack/latest/meta_data.json | jq -er .meta`
if [ $? -eq 0 ] ; then
  V=`echo $PROMETHEUS_META_DATA | jq -er .PROMETHEUS_ADMIN_PASS` && PROMETHEUS_ADMIN_PASS="$V"
  V=`echo $PROMETHEUS_META_DATA | jq -er .GRAFANA_ADMIN_PASS` && GRAFANA_ADMIN_PASS="$V"
  V=`echo $PROMETHEUS_META_DATA | jq -er .GIT_URL` && GIT_URL="$V"
  V=`echo $PROMETHEUS_META_DATA | jq -er .GIT_BRANCH` && GIT_BRANCH="$V"
fi

# Add prometheus user with sudo perm
if [ `grep -c '^prometheus:' /etc/passwd` = "0" ] ; then
  useradd -s /bin/bash -d $HOME_PROMETHEUS -G docker -m prometheus || fail "useradd failed"
  echo 'prometheus ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers
  SUDO_WHOAMI=`timeout 1 sudo whoami`
  test "$SUDO_WHOAMI" = "root" || fail "failed to create prometheus user with sudo perm"
fi

# Copy authorized keys from ubuntu user
if [ ! -d $HOME_PROMETHEUS/.ssh -a -r /home/ubuntu/.ssh/authorized_keys ] ; then
  AUTH_KEYS_UBUNTU=`sudo cat /home/ubuntu/.ssh/authorized_keys` || fail "failed to cat /home/ubuntu/.ssh/authorized_keys"
  ( cat << EOF | sudo -H -u prometheus /bin/bash ) || fail "failed to create ~/.ssh/authorized_keys"
  mkdir ~/.ssh
  chmod 770 ~/.ssh
  echo "$AUTH_KEYS_UBUNTU" >> ~/.ssh/authorized_keys
  chmod 600 ~/.ssh/authorized_keys
EOF
fi

# Clone Krake
if [ ! -d $GIT_KRAKE_DIR ] ; then
  sudo -H -u prometheus mkdir -p $GIT_REPO_DIR|| fail "failed to create dir $GIT_REPO_DIR"
  cd $GIT_REPO_DIR
  sudo -H -u prometheus git clone $GIT_URL -b $GIT_BRANCH || fail "failed to clone Krake"
  cd - > /dev/null
fi

# Create prometheus.yml file based on jinja2 template
sudo -H -u prometheus jinja2_standalone_compiler --silent --settings $GIT_KRAKE_DIR/infra/prometheus/cloud-init/prometheus_vm-template_settings.py \
  --path $GIT_KRAKE_DIR/infra/prometheus/docker-compose/prometheus/prometheus.yml.j2 || fail "failed to generate prometheus.yml"


# TODO Remove following line and referenced daemon.json file once C&H MTU issue is resolved
# C&H infra currently suffers from "MTU bug" when typical value of 1500 causes connectivity
# issues. Following is a workaround.
cp $GIT_KRAKE_DIR/docker/daemon.json /etc/docker || fail "failed to copy daemon.json"
/etc/init.d/docker restart || fail "failed to restart docker"

# Launch docker containers
sudo -H -u prometheus PROMETHEUS_ADMIN_PASS="$PROMETHEUS_ADMIN_PASS" GRAFANA_ADMIN_PASS="$GRAFANA_ADMIN_PASS" \
  docker-compose -f $GIT_KRAKE_DIR/infra/prometheus/docker-compose/docker-compose.yml up --build -d || fail "docker-compose failed"
