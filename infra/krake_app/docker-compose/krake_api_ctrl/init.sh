#!/bin/bash
set -e

# Start Supervisor, with uWSGI
/usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
