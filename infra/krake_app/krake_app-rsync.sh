#!/bin/bash

function fail () {
  echo $1
  exit 1
}

# Check number of arguments
if [ $# -ne 1 ] ; then
  fail "usage: $0 185.128.119.XX"
fi

# Set vars
KRAKE_APP_IP="$1"

# Check CWD
if [ ! -d .git -o ! -d documentation ] ; then
  fail "this script must be executed from krake git dir"
fi

# Checksum based rsync over ssh, use --dry-run param to test
#
# In case performance is not sufficient, consider changing --checksum to
# --times.  This has a disadvantage of transferring all files during first
# transfer (because timestamps are different).
#
# See following link for --itemize-changes description:
# http://web.archive.org/web/20160904174444/http://andreafrancia.it/2010/03/understanding-the-output-of-rsync-itemize-changes.html
RSYNCED_FILES=`rsync --checksum --itemize-changes -e "ssh -l krake -o StrictHostKeyChecking=no" --recursive --exclude-from=infra/krake_app/krake_app-rsync.exclude ./ $KRAKE_APP_IP:git/krake/ | grep -E '^<' | cut -d ' ' -f 2-` || fail "rsync failed"

if [ -z "$RSYNCED_FILES" ] ; then
  echo "No changes detected"
  exit 0
fi

echo $RSYNCED_FILES

# Rebuild docker if needed
if [ -z "${RSYNCED_FILES##*docker-compose.yml*}" -o \
     -z "${RSYNCED_FILES##*Dockerfile*}" ]
then
  ( cat << EOF | ssh -T krake@$KRAKE_APP_IP ) || fail "docker-compose failed"
  cd ~/git/krake/infra/krake_app/docker-compose
  docker-compose up -d --build
EOF
fi

# Restart krake_api_ctrl container if needed
# Note krake_api_ctrl uses Flask which automatically detects changes in files, however that does not always work
RESTART_COMPONENTS=""
if [ -z "${RSYNCED_FILES##*krake_api/*}" ] ; then
  RESTART_COMPONENTS="$RESTART_COMPONENTS krake_api_ctrl"
fi

# Restart krake_worker container if needed
if [ -z "${RSYNCED_FILES##*krake_worker/*}" ] ; then
  RESTART_COMPONENTS="$RESTART_COMPONENTS krake_worker"
fi

# Restart scheduler container if needed
if [ -z "${RSYNCED_FILES##*krake_scheduler/*}" ] ; then
  RESTART_COMPONENTS="$RESTART_COMPONENTS krake_scheduler"
fi

# Restart components
echo
for i in $RESTART_COMPONENTS ; do
  echo "restarting $i"
  ssh krake@$KRAKE_APP_IP docker restart -t 1 $i
  if [ $? -eq 0 ] ; then
    echo "$i successfully restarted"
  else
    echo "$i restart failed"
  fi
  echo
done
