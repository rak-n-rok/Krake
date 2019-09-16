#!/bin/bash

HOME_STACK=/opt/stack

function fail () {
  echo $1
  exit 1
}

# Install packages
apt update
apt install -y bridge-utils

# Enable nested virtualization
NESTED=`cat /sys/module/kvm_intel/parameters/nested`
if [ "$NESTED" <> "Y" ] ; then
  rmmod kvm-intel
  echo 'options kvm-intel nested=y' >> /etc/modprobe.d/dist.conf
  modprobe kvm-intel
  NESTED=`cat /sys/module/kvm_intel/parameters/nested`
  test "$NESTED" = "Y" || fail "failed to enable nested virtualization"
fi

# Add stack user with sudo perm
if [ `grep -c '^stack:' /etc/passwd` = "0" ] ; then
  useradd -s /bin/bash -d $HOME_STACK -m stack
  echo 'stack ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers
  SUDO_WHOAMI=`timeout 1 sudo whoami`
  test "$SUDO_WHOAMI" = "root" || fail "failed to create stack user with sudo perm"
fi

# Copy authorized keys from ubuntu user
if [ ! -d $HOME_STACK/.ssh -a -r /home/ubuntu/.ssh/authorized_keys ] ; then
  AUTH_KEYS_UBUNTU=`sudo cat /home/ubuntu/.ssh/authorized_keys` || fail "failed to cat /home/ubuntu/.ssh/authorized_keys"
  ( cat << EOF | sudo -H -u stack /bin/bash ) || fail "failed to create ~/.ssh/authorized_keys"
  mkdir ~/.ssh
  chmod 770 ~/.ssh
  echo "$AUTH_KEYS_UBUNTU" >> ~/.ssh/authorized_keys
  chmod 600 ~/.ssh/authorized_keys
EOF
fi

# Clone DevStack
if [ ! -d $HOME_STACK/devstack ] ; then
  cd $HOME_STACK
  sudo -H -u stack git clone https://git.openstack.org/openstack-dev/devstack -b stable/rocky || fail "failed to clone DevStack"
  cd -
fi

# Create local.conf
if [ ! -f $HOME_STACK/devstack/local.conf ] ; then
  cat << \EOF > $HOME_STACK/devstack/local.conf || fail "failed to create local.conf"
# This file overrides defaults from ~/devstack/stackrc
# Based on https://docs.openstack.org/devstack/latest/guides/single-machine.html
[[local|localrc]]

# Credentials
ADMIN_PASSWORD=tmp
DATABASE_PASSWORD=$ADMIN_PASSWORD
RABBIT_PASSWORD=$ADMIN_PASSWORD
SERVICE_PASSWORD=$ADMIN_PASSWORD

# Target branch for core OpenStack components (but not plugins), defaults to
# latest stable version
#
# TARGET_BRANCH=stable/queens

# Uncomment if you need specific branch of a component
# KEYSTONE_BRANCH=stable/queens
# NOVA_BRANCH=stable/queens
# NEUTRON_BRANCH=stable/queens
# CINDER_BRANCH=stable/queens
# GLANCE_BRANCH=stable/queens
# HORIZON_BRANCH=stable/queens

# Networking - uncomment if you want specific floating (public) IPs
# HOST_IP=192.168.122.165
# FLAT_INTERFACE=ens3

# Configure the public network range
IP_VERSION=4
FLOATING_RANGE=172.16.$DEVSTACK_ID.0/24
PUBLIC_NETWORK_GATEWAY=172.16.$DEVSTACK_ID.1
Q_FLOATING_ALLOCATION_POOL="start=172.16.$DEVSTACK_ID.100,end=172.16.$DEVSTACK_ID.254"

# Magnum dependencies
#
# Be sure to explicitly specify version because TARGET_BRANCH (set in
# ~/devstack/stackrc) applies to OpenStack core components only, not plugins.
# Not specifying version defaults to master branch for plugins.
#
# Note even when you do not specify version and thus using master branch for
# plugins, DevStack will announce (in ~/logs/stack.sh.log):
#
# DevStack Version: queens
#
# This is not completely true, see above.
enable_plugin heat https://git.openstack.org/openstack/heat $TARGET_BRANCH

# Magnum
enable_plugin magnum https://git.openstack.org/openstack/magnum $TARGET_BRANCH
enable_plugin magnum-ui https://github.com/openstack/magnum-ui $TARGET_BRANCH
enable_plugin python-magnumclient https://github.com/openstack/python-magnumclient $TARGET_BRANCH

# Note you can set different branch or even specific version of a
# component/plugin
#
# enable_plugin magnum https://git.openstack.org/openstack/magnum stable/queens
# enable_plugin magnum https://git.openstack.org/openstack/magnum 6.1.1

# Transparent TLS proxy
enable_service tls-proxy

# Log
LOGFILE=/opt/stack/logs/stack.sh.log
EOF
  chown stack: $HOME_STACK/devstack/local.conf
fi

# Create devstack-boot.sh
if [ ! -f $HOME_STACK/devstack-boot.sh ] ; then
  cat << \EOF > $HOME_STACK/devstack-boot.sh || fail "failed to create devstack-boot.sh"
#!/bin/bash

# Boot DevStack
#
# http://support.loomsystems.com/openstack-made-easy/how-to-properly-reboot-a-machine-running-devstack
# DevStack is not intended to support restoring a running stack after a reboot.
# Instead, you will need to run stack.sh and create a new cloud.
#
# Stopping devstack@* services takes surprisingly long time, so they are
# disabled (not starting during boot) - no need to run unstack.sh.
#
# There should not be a need to run clean.sh. Note it would remove all *.pyc
# files. 

function fail () {
  echo $1
  exit 1
}

cd ~/devstack/

# We do not run following commands because they take a long time, however
# DevStack documentation recommends them, so keeping them in a comment.
# ./unstack.sh
# ./clean.sh

# DevStack uses following certificates:
# ~/data/devstack-cert.pem
# ~/data/ca-bundle.pem
# ~/data/CA/ (dir, you can check exact content from a live DevStack instance)
#
# If provided, files are used by DevStack installation below, so one could
# provide real certificates, e.g. generated by Let's Encrypt service.

# Install DevStack
./stack.sh || fail "failed to launch stack.sh"

# Source openrc
. ~/devstack/openrc || fail "failed to source openrc"

# Allow icmp and ssh in default security group, so instances created
# using "openstack server create" can be easily accessed
openstack security group rule create default --ethertype IPv4 --ingress --protocol icmp || fail "failed to add icmp rule"
openstack security group rule create default --ethertype IPv4 --ingress --protocol tcp --dst-port 22:22 || fail "failed to add ssh rule"

# Disable DevStack services
# Note devstack@* did not work, so we are listing all services manually
# sudo systemctl disable devstack@*
sudo systemctl disable devstack@n-super-cond.service
sudo systemctl disable devstack@dstat.service
sudo systemctl disable devstack@n-novnc.service
sudo systemctl disable devstack@c-sch.service
sudo systemctl disable devstack@q-agt.service
sudo systemctl disable devstack@h-eng.service
sudo systemctl disable devstack@c-vol.service
sudo systemctl disable devstack@n-cpu.service
sudo systemctl disable devstack@q-svc.service
sudo systemctl disable devstack@n-sch.service
sudo systemctl disable devstack@g-reg.service
sudo systemctl disable devstack@q-dhcp.service
sudo systemctl disable devstack@q-meta.service
sudo systemctl disable devstack@magnum-api.service
sudo systemctl disable devstack@q-l3.service
sudo systemctl disable devstack@magnum-cond.service
sudo systemctl disable devstack@n-cond-cell1.service
sudo systemctl disable devstack@n-cauth.service
sudo systemctl disable devstack@h-api.service
sudo systemctl disable devstack@g-api.service
sudo systemctl disable devstack@keystone.service
sudo systemctl disable devstack@h-api-cfn.service
sudo systemctl disable devstack@n-api.service
sudo systemctl disable devstack@n-api-meta.service
sudo systemctl disable devstack@c-api.service
sudo systemctl disable devstack@placement-api.service
sudo systemctl disable devstack@etcd.service
EOF
  chown stack: $HOME_STACK/devstack-boot.sh
  chmod +x $HOME_STACK/devstack-boot.sh
fi

# Adjust rc.local
sed -i "s,^exit 0$,sudo -H -u stack $HOME_STACK/devstack-boot.sh," /etc/rc.local || fail "failed to adjust /etc/rc.local"

# Source openrc if it exists
if [ `grep -c '^F=~/devstack/openrc' $HOME_STACK/.bashrc` = "0" ] ; then
  echo 'F=~/devstack/openrc ; test -r $F && . $F' >> $HOME_STACK/.bashrc
fi

# Launch rc.local, which will launch devstack-boot.sh, installing DevStack
/etc/rc.local

# Downgrade OpenStack python packages to fix federation.
# See https://storyboard.openstack.org/#!/story/2004016
pip install python-openstackclient==3.14.2 osc-lib==1.9.0 openstacksdk==0.11.3 os-client-config==1.29.0


