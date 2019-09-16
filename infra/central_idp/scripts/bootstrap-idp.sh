#!/bin/bash
set -xeo pipefail
. /var/lib/kolla/venv/bin/activate
echo "generating IDP metadata"
keystone-manage saml_idp_metadata > /etc/keystone/saml2_idp_metadata.xml

