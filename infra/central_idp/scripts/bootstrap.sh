#!/bin/bash
set -xeo pipefail
. /var/lib/kolla/venv/bin/activate
echo "setting up keystone database"
keystone-manage db_sync
echo "bootstrapping keystone"
chown keystone:keystone /etc/keystone/fernet-keys
keystone-manage fernet_setup --keystone-user keystone --keystone-group keystone
keystone-manage bootstrap --bootstrap-username admin --bootstrap-password tmp --bootstrap-project-name admin --bootstrap-role-name admin --bootstrap-region-id $REGION_NAME --bootstrap-service-name keystone --bootstrap-public-url https://$PUBLIC_ENDPOINT_HOST --bootstrap-internal-url https://$PUBLIC_ENDPOINT_HOST --bootstrap-admin-url https://$ADMIN_ENDPOINT_HOST/v3
mkdir -p /run/lock/apache2
mkdir -p /var/run/apache2
mkdir -p /var/run/shibboleth
chmod ugo+rwx,o+t /run/lock
chown keystone:keystone /var/log/kolla/keystone/{main,admin}.log || true

