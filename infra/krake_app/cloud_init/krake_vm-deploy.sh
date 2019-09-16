#!/bin/bash

# Note '_' char is is not allowed in hostname
#
# krake@queens:~$ sudo hostname krake_app
# hostname: the specified hostname is invalid
HOST_NAME="krake-app"
HOME_KRAKE="/home/krake"
GIT_REPO_DIR="$HOME_KRAKE/git"
GIT_KRAKE_DIR="$GIT_REPO_DIR/krake"

function fail () {
  echo $1
  exit 1
}

# Set hostname
echo $HOST_NAME > /etc/hostname
hostname $HOST_NAME || fail "failed to set hostname"

# Get Krake private IP address
KRAKE_PRIVATE_IP=`ip addr show ens3 | grep 'inet ' | awk '{print $2}' | cut -f1 -d'/'`

# Add hostname to /etc/hosts to avoid following message:
#
# sudo -s
# sudo: unable to resolve host krake-app
echo "127.0.0.1 $HOST_NAME" >> /etc/hosts

# Install packages
apt-get update || fail "apt-get update failed"
apt-get install -y docker.io docker-compose jq python3-pip joe haveged prometheus-node-exporter || fail "apt-get install failed"
sudo snap install kubectl --classic || fail "kubectl installation failed"

# Install required python packages for Krake
pip3 install --no-cache-dir \
  attrs~=18.2.0 \
  flake8 \
  flask~=1.0.2 \
  jinja2-standalone-compiler~=1.3.1 \
  jsonschema~=2.6.0 \
  keystoneauth1~=3.11.0 \
  kubernetes~=10.0.0a1 \
  mock \
  mysql-connector-python~=8.0.15 \
  pika~=0.12.0 \
  pyOpenSSL~=18.0.0 \
  pytest \
  pytest-cov \
  python-magnumclient~=2.10.0 \
  urllib3~=1.24.3 \
  responses~=0.10.4 \
  requests~=2.20.1 \
  retrying~=1.3.3 \
  texttable~=1.5.0 || fail "pip3 install failed"

# Add krake user with sudo perm
if [ `grep -c '^krake:' /etc/passwd` = "0" ] ; then
  useradd -s /bin/bash -d $HOME_KRAKE -G docker -m krake || fail "useradd failed"
  echo 'krake ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers
  SUDO_WHOAMI=`timeout 1 sudo whoami`
  test "$SUDO_WHOAMI" = "root" || fail "failed to create krake user with sudo perm"

  # Disable motd message for following case:
  #
  # ( cat << EOF | ssh -T krake@$KRAKE_APP_IP ) || fail "docker-compose failed"
  # ...
  # EOF
  sudo -H -u krake touch $HOME_KRAKE/.hushlogin
fi

# Copy authorized keys from ubuntu user
if [ ! -d $HOME_KRAKE/.ssh -a -r /home/ubuntu/.ssh/authorized_keys ] ; then
  AUTH_KEYS_UBUNTU=`sudo cat /home/ubuntu/.ssh/authorized_keys` || fail "failed to cat /home/ubuntu/.ssh/authorized_keys"
  ( cat << EOF | sudo -H -u krake /bin/bash ) || fail "failed to create ~/.ssh/authorized_keys"
  mkdir ~/.ssh
  chmod 770 ~/.ssh
  echo "$AUTH_KEYS_UBUNTU" >> ~/.ssh/authorized_keys
  chmod 600 ~/.ssh/authorized_keys
EOF
fi

# Configure Krake, set defaults
IDENTITY_PROVIDER_HOSTNAME="192.168.0.14:5001"
MYSQL_DEFAULT_PASS="tmp"
GIT_URL="https://krake_app:vT3cMpDwbXzyz5vYUmkx@publicgitlab.cloudandheat.com/ragnarok/krake.git"
GIT_BRANCH="master"
KRAKE_URL="https://$KRAKE_PRIVATE_IP/applications"

# Comma separated list of dictionaries with OpenStack instances attributes managed by
# this Krake-App instance (use Python syntax)
OPENSTACK_INSTANCES="[ \
  { 'deployment_uuid': 'See KrakeApp wiki: https://publicgitlab.cloudandheat.com/ragnarok/krake/wikis/krake-app#add-devstack-instance-to-scheduler-config', \
    'deployment_backend': 'See KrakeApp wiki: https://publicgitlab.cloudandheat.com/ragnarok/krake/wikis/krake-app#add-devstack-instance-to-scheduler-config', \
    'deployment_ip': 'Deployment IP address', \
    'federated_project_uuid': 'See KrakeApp wiki: https://publicgitlab.cloudandheat.com/ragnarok/krake/wikis/krake-app#add-devstack-instance-to-scheduler-config', \
  } \
]"

# Override default values by Metadata
KRAKE_META_DATA=`curl -f -s -m 1 http://169.254.169.254/openstack/latest/meta_data.json | jq -er .meta`
if [ $? -eq 0 ] ; then
  V=`echo $KRAKE_META_DATA | jq -er .IDENTITY_PROVIDER_HOSTNAME` && IDENTITY_PROVIDER_HOSTNAME="$V"
  V=`echo $KRAKE_META_DATA | jq -er .GIT_URL` && GIT_URL="$V"
  V=`echo $KRAKE_META_DATA | jq -er .GIT_BRANCH` && GIT_BRANCH="$V"
  V=`echo $KRAKE_META_DATA | jq -er .OPENSTACK_INSTANCES` && OPENSTACK_INSTANCES="$V"
  V=`echo $KRAKE_META_DATA | jq -er .KRAKE_URL` && KRAKE_URL="$V"
  V=`echo $KRAKE_META_DATA | jq -er .MYSQL_DEFAULT_PASS` && MYSQL_DEFAULT_PASS="$V"
fi

# Set derived values
IDENTITY_PROVIDER_AUTH_URL="https://$IDENTITY_PROVIDER_HOSTNAME/identity/v3"

# Clone Krake
if [ ! -d $GIT_KRAKE_DIR ] ; then
  sudo -H -u krake mkdir -p $GIT_REPO_DIR|| fail "failed to create dir $GIT_REPO_DIR"
  cd $GIT_REPO_DIR
  sudo -H -u krake git clone $GIT_URL -b $GIT_BRANCH || fail "failed to clone Krake"
  cd - > /dev/null
fi

# TODO Remove following line and referenced daemon.json file once C&H MTU issue is resolved
# C&H infra currently suffers from "MTU bug" when typical value of 1500 causes connectivity
# issues. Following is a workaround.
cp $GIT_KRAKE_DIR/docker/daemon.json /etc/docker || fail "failed to copy daemon.json"
/etc/init.d/docker restart || fail "failed to restart docker"

# Generate config.py for krake scheduler
$GIT_KRAKE_DIR/infra/krake_app/cloud_init/krake_vm_gen_scheduler_cfg.py "$OPENSTACK_INSTANCES" > $GIT_KRAKE_DIR/krake_scheduler/config.py

# Adjust config files
# TODO Add krake_worker/config_dev.py once it exists
sed -i \
  -e "s,^IDENTITY_PROVIDER_HOSTNAME = .*$,IDENTITY_PROVIDER_HOSTNAME = '$IDENTITY_PROVIDER_HOSTNAME'," \
  -e "s,^    KRAKE_URL = .*$,    KRAKE_URL = '$KRAKE_URL'," \
  -e "s,^    DB_PASSWORD = .*$,    DB_PASSWORD = '$MYSQL_DEFAULT_PASS'," \
  $GIT_KRAKE_DIR/krake_common/config.py \
  $GIT_KRAKE_DIR/krake_api/config_dev.py ||
  fail "adjustment of config files failed"


# Create uwsgi.ini and nginx.conf files based on jinja2 templates
jinja2_standalone_compiler --silent --settings $GIT_KRAKE_DIR/infra/krake_app/cloud_init/krake_vm-template_settings.py \
  --path $GIT_KRAKE_DIR/infra/krake_app/docker-compose/krake_nginx/nginx.conf.j2 || fail "failed to generate nginx.conf"
jinja2_standalone_compiler --silent --settings $GIT_KRAKE_DIR/infra/krake_app/cloud_init/krake_vm-template_settings.py \
  --path $GIT_KRAKE_DIR/infra/krake_app/docker-compose/krake_api_ctrl/uwsgi.ini.j2 || fail "failed to generate uwsgi.ini"

# Add environment variables .bashrc needed for Krake's CLI to work
echo "source $GIT_KRAKE_DIR/krake_cli/sample_openrc.sh" >> "$HOME_KRAKE/.bashrc"

# Add Krake's directory to PYTHONPATH
echo "export PYTHONPATH=$GIT_KRAKE_DIR" >> "$HOME_KRAKE/.bashrc"

# Add convenience aliases
echo 'alias rok="python3 -m krake_cli"' >> "$HOME_KRAKE/.bashrc"
echo 'alias recreate_env="MYSQL_DEFAULT_PASS='"$MYSQL_DEFAULT_PASS" "$GIT_KRAKE_DIR"'/dev_utils/recreate_env.sh"' >> "$HOME_KRAKE/.bashrc"

# Launch docker containers
sudo -H -u krake MYSQL_DEFAULT_PASS="$MYSQL_DEFAULT_PASS" docker-compose -f $GIT_KRAKE_DIR/infra/krake_app/docker-compose/docker-compose.yml up --build -d || fail "docker-compose failed"
