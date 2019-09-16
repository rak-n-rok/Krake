#!/bin/bash

function fail () {
  echo $1
  exit 1
}

HOME_STACK=/opt/stack

# Get DevStack private IP
DEVSTACK_IP=`ip -4 route get 8.8.8.8 | awk {'print $7'} | tr -d '\n'`

echo "$CENTRAL_IDP_IP central-idp" >> /etc/hosts || fail ""
echo "127.0.0.1 devstack$DEVSTACK_ID" >> /etc/hosts

# Fix locale settings
export LC_ALL="en_US.UTF-8"

# Default value for cloning the krake repository
GIT_URL="https://krake_app:vT3cMpDwbXzyz5vYUmkx@publicgitlab.cloudandheat.com/ragnarok/krake.git"
GIT_BRANCH="master"

# Clone Krake
if [ ! -d $HOME_STACK/git/krake ] ; then
  sudo -H -u stack mkdir -p $HOME_STACK/git || fail "failed to create dir git/krake"
  cd $HOME_STACK/git
  sudo -H -u stack git clone $GIT_URL -b $GIT_BRANCH || fail "failed to clone Krake"
  cd - > /dev/null
fi

# Install Shibboleth
curl -O http://pkg.switch.ch/switchaai/SWITCHaai-swdistrib.asc
echo 'deb http://pkg.switch.ch/switchaai/ubuntu xenial main' > /etc/apt/sources.list.d/SWITCHaai-swdistrib.list
apt-key add SWITCHaai-swdistrib.asc || fail "failed to add repository"
apt-get update || fail "apt get update failed"
apt-get install -y --install-recommends shibboleth || fail "failed to install shibboleth"

cp $HOME_STACK/git/krake/infra/devstack/federation/attribute-map.xml /etc/shibboleth/attribute-map.xml
cp $HOME_STACK/git/krake/infra/devstack/federation/shibboleth2.xml /etc/shibboleth/shibboleth2.xml
sed -i "s/<DEVSTACK_WITH_ID>/devstack$DEVSTACK_ID/g" /etc/shibboleth/shibboleth2.xml

# Adjust Keystone Apache config
cat << EOF >> /etc/apache2/sites-available/keystone-wsgi-admin.conf
Proxypass /identity_admin/Shibboleth.sso !
<Location /identity_admin/Shibboleth.sso>
    SetHandler shib
</Location>

<Location /identity_admin/v3/OS-FEDERATION/identity_providers/identity-central/protocols/mapped/auth>
    ShibRequestSetting requireSession 1
    AuthType shibboleth
    ShibExportAssertion Off
    Require valid-user

    <IfVersion < 2.4>
        ShibRequireSession On
        ShibRequireAll On
   </IfVersion>
</Location>
EOF

cat << EOF >> /etc/apache2/sites-available/keystone-wsgi-public.conf
Proxypass /identity/Shibboleth.sso !
<Location /identity/Shibboleth.sso>
    SetHandler shib
</Location>

<Location /identity/v3/OS-FEDERATION/identity_providers/identity-central/protocols/mapped/auth>
    ShibRequestSetting requireSession 1
    AuthType shibboleth
    ShibExportAssertion Off
    Require valid-user

    <IfVersion < 2.4>
        ShibRequireSession On
        ShibRequireAll On
   </IfVersion>
</Location>
EOF

# Adjust apache configuration to exclude Shibboleth from TLS Proxy
head -n-1 /etc/apache2/sites-enabled/http-services-tls-proxy.conf > /etc/apache2/sites-enabled/http-services-tls-proxy.conf.temp
mv /etc/apache2/sites-enabled/http-services-tls-proxy.conf.temp /etc/apache2/sites-enabled/http-services-tls-proxy.conf
cat << EOF >> /etc/apache2/sites-enabled/http-services-tls-proxy.conf
    <Location /Shibboleth.sso>
        ProxyPass "!"
    </Location>
</VirtualHost>
EOF

# Adjust apache configuration to forward the original client IP address
cat << EOF >> /etc/apache2/conf-available/proxy_ip.conf
RemoteIPHeader X-Forwarded-For
RemoteIPInternalProxy $DEVSTACK_IP/32
EOF

a2enconf proxy_ip || fail "Failed to enable proxy configuration"
a2enmod remoteip || fail "Failed to enable remoteip module"

# Restarting shibboleth and apache
systemctl restart shibd.service apache2.service
